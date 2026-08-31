"""Portable canonical content and instruction types.

Content is deliberately small: text, JSON and media/artifact references. A vendor wire block is
not generic content merely because a provider serializes it next to messages. Anything that
carries ordering, execution or replay semantics is an `InferenceItem`, not a `ContentPart`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

from cerebro.harness.ids import ArtifactRef

__all__ = [
    "ContentPart",
    "Instruction",
    "InstructionAuthority",
    "JsonPart",
    "MediaPart",
    "MediaSource",
    "OmissionMetadata",
    "Provenance",
    "TextPart",
    "text_of",
]

InstructionAuthority = Literal["system", "developer"]
MediaSource = Literal["inline", "uri", "artifact_ref"]


class Provenance(BaseModel):
    """Where a canonical object came from, in Cerebro's own terms."""

    model_config = {"frozen": True}

    source_kind: str
    source_id: str | None = None
    author_id: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextPart(BaseModel):
    model_config = {"frozen": True}

    part_type: Literal["text"] = "text"
    text: str


class JsonPart(BaseModel):
    model_config = {"frozen": True}

    part_type: Literal["json"] = "json"
    value: Any


class MediaPart(BaseModel):
    """Media carried inline, by URI, or by durable artifact reference."""

    model_config = {"frozen": True}

    part_type: Literal["media"] = "media"
    media_type: str
    mime_type: str | None = None
    source: MediaSource
    data_or_ref: str
    artifact_ref: ArtifactRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _artifact_source_needs_ref(self) -> "MediaPart":
        if self.source == "artifact_ref" and self.artifact_ref is None:
            raise ValueError("MediaPart with source='artifact_ref' requires artifact_ref")
        return self


ContentPart = Annotated[
    Union[TextPart, JsonPart, MediaPart],
    Field(discriminator="part_type"),
]


class OmissionMetadata(BaseModel):
    """Explicit record that a model-visible projection is smaller than the durable truth.

    A bounded projection without this is indistinguishable from a small result, which is how a
    truncated tool output silently becomes a wrong answer.
    """

    model_config = {"frozen": True}

    reason: str
    omitted_bytes: int | None = None
    omitted_items: int | None = None
    original_size: int | None = None
    detail: str | None = None


class Instruction(BaseModel):
    """System/developer authority text. Not part of the ordered item history."""

    model_config = {"frozen": True}

    authority: InstructionAuthority
    content: list[ContentPart]
    provenance: Provenance


def text_of(parts: list[ContentPart]) -> str:
    """Concatenate the text parts of a content list.

    Adapters use this at the wire edge where a dialect only accepts a string. JSON and media
    parts are the adapter's problem to encode or reject, never something to stringify blindly
    here.
    """
    return "".join(p.text for p in parts if isinstance(p, TextPart))
