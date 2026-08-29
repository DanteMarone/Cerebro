"""Canonical ordered `InferenceItem` history.

Canonical history is an ordered item stream, not a role/message transcript. Every persisted item
carries the same envelope: its own identity, its own `format_version`, the attempt that produced
it (AR-10/AR-02), its ordering metadata and its supersession metadata.

`producing_attempt_id` is the field that makes an interrupted provider attempt recoverable
without contaminating the next request. Without it, the harness cannot tell which finalized
output belongs to an attempt it must abandon.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

from cerebro.harness.content import ContentPart, OmissionMetadata, Provenance
from cerebro.harness.ids import (
    AgentTurnId,
    ArtifactRef,
    CerebroCallId,
    InferenceAttemptId,
    InferenceItemId,
)
from cerebro.harness.provider_ref import ProviderCallRef
from cerebro.harness.tooling import ToolInput, ToolKey, ToolResultStatus

__all__ = [
    "INFERENCE_ITEM_FORMAT_VERSION",
    "InferenceItem",
    "ItemOrigin",
    "MessageItem",
    "ProviderOpaqueItem",
    "ReasoningSummaryItem",
    "ReplayRequirement",
    "ReplayRetentionScope",
    "ReplaySensitivity",
    "SENSITIVE_REPLAY_SENSITIVITIES",
    "ToolCallItem",
    "ToolResultItem",
    "is_provider_originated",
    "item_sort_key",
]

INFERENCE_ITEM_FORMAT_VERSION = 1

ItemOrigin = Literal["provider_attempt", "context_projection", "harness_local"]

ReplayRequirement = Literal[
    "required_for_correctness",
    "fidelity_preserving",
    "optimization_only",
]

ReplayRetentionScope = Literal[
    "current_tool_cycle",
    "current_turn",
    "conversation",
    "provider_defined",
]

ReplaySensitivity = Literal[
    "ordinary",
    "hidden_reasoning",
    "signature_or_encrypted_reasoning",
    "secret_like",
]

SENSITIVE_REPLAY_SENSITIVITIES: frozenset[str] = frozenset(
    {"hidden_reasoning", "signature_or_encrypted_reasoning", "secret_like"}
)


class _ItemEnvelope(BaseModel):
    """Fields every canonical item carries, whatever its variant.

    `format_version` is per item, not per schema epoch: a stored item has to be readable on its
    own terms years after the epoch that wrote it moved on.
    """

    model_config = {"frozen": True}

    item_id: InferenceItemId
    format_version: int = INFERENCE_ITEM_FORMAT_VERSION
    origin: ItemOrigin
    producing_attempt_id: InferenceAttemptId | None = None

    # Ordering and attribution. `inference_items` is conversation-owned (AR-03); turn attribution
    # is required on every item so turn-scoped reads are a filter, not a different model.
    agent_turn_id: AgentTurnId | None = None
    sequence_no: int | None = None

    # Supersession is durable metadata, never a delete (AR-02).
    superseded_at: str | None = None
    superseded_reason: str | None = None
    superseding_attempt_id: InferenceAttemptId | None = None

    @model_validator(mode="after")
    def _attempt_identity_matches_origin(self) -> "_ItemEnvelope":
        if self.origin == "provider_attempt" and self.producing_attempt_id is None:
            raise ValueError(
                "a provider-originated item requires producing_attempt_id; generic provenance "
                "is not a substitute for attempt identity"
            )
        if self.origin != "provider_attempt" and self.producing_attempt_id is not None:
            raise ValueError(
                f"origin={self.origin!r} item must not claim a producing_attempt_id"
            )
        return self

    @property
    def is_superseded(self) -> bool:
        return self.superseded_at is not None


class MessageItem(_ItemEnvelope):
    """One user or assistant message."""

    item_type: Literal["message"] = "message"
    role: Literal["user", "assistant"]
    content: list[ContentPart]
    provenance: Provenance


class ToolCallItem(_ItemEnvelope):
    """A finalized tool call. Only ever created from `OutputItemCompleted`, never from a delta."""

    item_type: Literal["tool_call"] = "tool_call"
    call_id: CerebroCallId
    tool_key: ToolKey
    input: ToolInput
    provider_ref: ProviderCallRef | None = None


class ToolResultItem(BaseModel):
    """The bounded model-visible projection of one tool result.

    Produced by Cerebro's executor, so its origin is `harness_local` and it carries no producing
    attempt. `content` is explicitly a projection, and `raw_output_ref`/`omission` say so.
    """

    model_config = {"frozen": True}

    item_id: InferenceItemId
    format_version: int = INFERENCE_ITEM_FORMAT_VERSION
    origin: ItemOrigin = "harness_local"
    producing_attempt_id: InferenceAttemptId | None = None
    agent_turn_id: AgentTurnId | None = None
    sequence_no: int | None = None
    superseded_at: str | None = None
    superseded_reason: str | None = None
    superseding_attempt_id: InferenceAttemptId | None = None

    item_type: Literal["tool_result"] = "tool_result"
    call_id: CerebroCallId
    tool_key: ToolKey
    status: ToolResultStatus
    content: list[ContentPart]
    raw_output_ref: ArtifactRef | None = None
    original_size: int | None = None
    omission: OmissionMetadata | None = None
    provider_ref: ProviderCallRef | None = None
    timing: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _result_is_harness_local(self) -> "ToolResultItem":
        if self.origin != "harness_local":
            raise ValueError(
                "a ToolResultItem is produced by Cerebro's executor, not by a provider attempt"
            )
        if self.producing_attempt_id is not None:
            raise ValueError("a ToolResultItem must not claim a producing_attempt_id")
        return self

    @property
    def is_superseded(self) -> bool:
        return self.superseded_at is not None


class ReasoningSummaryItem(_ItemEnvelope):
    """Provider-supported visible/summarized reasoning that Cerebro intentionally exposes.

    Hidden chain-of-thought retained only so a provider will accept the next request is not this
    type; that is a `ProviderOpaqueItem` whose sensitivity keeps it out of generic surfaces.
    """

    item_type: Literal["reasoning_summary"] = "reasoning_summary"
    content: list[ContentPart]
    provenance: Provenance


class ProviderOpaqueItem(_ItemEnvelope):
    """Ordered adapter-owned protocol state.

    Generic harness code persists and sequences this and never reads the payload. Nothing here
    may decide a tool call, a completion or a product outcome. The moment generic code branches
    on the payload, the adapter boundary has stopped existing.
    """

    item_type: Literal["provider_opaque"] = "provider_opaque"
    provider_id: str
    adapter_dialect: str
    kind: str
    exact_payload: str
    payload_encoding: str = "json"
    replay_requirement: ReplayRequirement
    retention_scope: ReplayRetentionScope
    sensitivity: ReplaySensitivity = "ordinary"

    @model_validator(mode="after")
    def _opaque_is_provider_originated(self) -> "ProviderOpaqueItem":
        if self.origin != "provider_attempt":
            raise ValueError("a ProviderOpaqueItem can only originate from a provider attempt")
        return self

    @property
    def is_sensitive(self) -> bool:
        return self.sensitivity in SENSITIVE_REPLAY_SENSITIVITIES

    def log_projection(self) -> dict[str, Any]:
        """What generic logs, Hub events and UI are allowed to see.

        The payload is absent for every sensitivity, not only the sensitive ones. Generic code
        has no legitimate reason to read adapter-owned bytes, and a projection that leaks them
        for `ordinary` items is one mislabelled adapter away from leaking a signature.
        """
        return {
            "item_id": str(self.item_id),
            "item_type": self.item_type,
            "provider_id": self.provider_id,
            "adapter_dialect": self.adapter_dialect,
            "kind": self.kind,
            "replay_requirement": self.replay_requirement,
            "retention_scope": self.retention_scope,
            "sensitivity": self.sensitivity,
            "payload_bytes": len(self.exact_payload),
            "payload": "<redacted>",
        }

    def __repr__(self) -> str:
        return (
            f"ProviderOpaqueItem(item_id={str(self.item_id)!r}, "
            f"provider_id={self.provider_id!r}, kind={self.kind!r}, "
            f"replay_requirement={self.replay_requirement!r}, "
            f"sensitivity={self.sensitivity!r}, "
            f"exact_payload=<redacted {len(self.exact_payload)} chars>)"
        )

    __str__ = __repr__


InferenceItem = Annotated[
    Union[
        MessageItem,
        ToolCallItem,
        ToolResultItem,
        ReasoningSummaryItem,
        ProviderOpaqueItem,
    ],
    Field(discriminator="item_type"),
]


def is_provider_originated(item: Any) -> bool:
    """True when the item came out of a provider attempt via `OutputItemCompleted`."""
    return getattr(item, "origin", None) == "provider_attempt"


def item_sort_key(item: Any) -> tuple[int, str]:
    """Canonical ordering: `(sequence_no, item_id)`.

    An unsequenced item sorts after every sequenced one rather than silently taking position 0.
    """
    seq = item.sequence_no
    return (seq if seq is not None else 2**62, str(item.item_id))
