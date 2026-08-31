"""Canonical Harness v1 identity types.

Every Harness identity is an opaque, stable, Cerebro-generated value unless it is explicitly
marked provider-owned. They are modelled as prefixed `str` subclasses so that:

- a serialized identity is a plain JSON string (no envelope, no adapter special-casing);
- an identity carries its own family in its text, so a mis-wired value fails loudly at
  construction instead of silently addressing the wrong object three layers down;
- provider-owned correlation state cannot be assigned into a Cerebro identity field, because
  provider state is a structured `ProviderCallRef` and never a `CerebroCallId`.

The prefix is part of the value, not metadata about it. `CerebroCallId("call_abc")` from an
OpenAI `tool_call_id` raises rather than quietly becoming canonical execution identity.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

__all__ = [
    "AgentTurnId",
    "ArtifactRef",
    "ConversationTurnId",
    "CerebroCallId",
    "ExternalExecutionId",
    "HarnessId",
    "InferenceAttemptId",
    "InferenceItemId",
    "InvalidHarnessId",
    "ModelProfileId",
    "ProviderConfigId",
    "StepSnapshotId",
    "ToolBindingGeneration",
]


class InvalidHarnessId(ValueError):
    """A value was offered as a Harness identity but does not belong to that identity family."""


class HarnessId(str):
    """Base class for prefixed opaque Harness identities."""

    __slots__ = ()

    prefix: ClassVar[str] = ""

    def __new__(cls, value: Any) -> "HarnessId":
        if cls.prefix == "":
            raise TypeError("HarnessId is abstract; instantiate a concrete identity type")
        if isinstance(value, HarnessId) and type(value) is not cls:
            raise InvalidHarnessId(
                f"{type(value).__name__} value {str.__str__(value)!r} cannot be reused as "
                f"{cls.__name__}"
            )
        if not isinstance(value, str):
            raise InvalidHarnessId(f"{cls.__name__} must be a string, got {type(value).__name__}")
        text = str(value)
        expected = f"{cls.prefix}_"
        if not text.startswith(expected):
            raise InvalidHarnessId(
                f"{cls.__name__} must start with {expected!r}, got {text!r}"
            )
        if len(text) <= len(expected):
            raise InvalidHarnessId(f"{cls.__name__} has an empty body: {text!r}")
        return super().__new__(cls, text)

    @classmethod
    def generate(cls) -> "HarnessId":
        """Mint a fresh identity. Uniqueness is local and does not depend on any provider."""
        return cls(f"{cls.prefix}_{uuid.uuid4().hex}")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}({str.__str__(self)!r})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def _validate(value: str) -> "HarnessId":
            return cls(value)

        return core_schema.no_info_after_validator_function(
            _validate,
            core_schema.str_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str.__str__, return_schema=core_schema.str_schema()
            ),
        )


class AgentTurnId(HarnessId):
    """One durable agent execution admitted from one causal wake."""

    __slots__ = ()
    prefix: ClassVar[str] = "atn"


class ConversationTurnId(HarnessId):
    """The conversation-level turn an agent turn belongs to."""

    __slots__ = ()
    prefix: ClassVar[str] = "ctn"


class StepSnapshotId(HarnessId):
    """An immutable executable step definition. The snapshot body itself lands in PR 3."""

    __slots__ = ()
    prefix: ClassVar[str] = "snap"


class InferenceAttemptId(HarnessId):
    """One provider dispatch identity, durable before any bytes may leave the process."""

    __slots__ = ()
    prefix: ClassVar[str] = "att"


class InferenceItemId(HarnessId):
    """One ordered canonical history item."""

    __slots__ = ()
    prefix: ClassVar[str] = "item"


class CerebroCallId(HarnessId):
    """Canonical execution identity for one admitted client-tool call.

    Never derived from and never replaced by a provider-native tool call id.
    """

    __slots__ = ()
    prefix: ClassVar[str] = "ccall"


class ModelProfileId(HarnessId):
    """Versioned model behaviour profile identity, separate from provider configuration."""

    __slots__ = ()
    prefix: ClassVar[str] = "mprof"


class ProviderConfigId(HarnessId):
    """Where/how to reach a provider. Holds credential references, never credentials."""

    __slots__ = ()
    prefix: ClassVar[str] = "pcfg"


class ArtifactRef(HarnessId):
    """Reference to durable out-of-band content. Storage backend is a PR 3 decision."""

    __slots__ = ()
    prefix: ClassVar[str] = "artf"


class ToolBindingGeneration(HarnessId):
    """Opaque generation marker for one executable tool binding.

    Deliberately opaque: how CoreTools versions and MCP reconnect/`tools/list_changed`
    generations become stable binding identities is an open PR 3 decision, and encoding a
    guess here would freeze it.
    """

    __slots__ = ()
    prefix: ClassVar[str] = "tbg"


class ExternalExecutionId(HarnessId):
    """One external-agent harness execution. Not a provider inference attempt."""

    __slots__ = ()
    prefix: ClassVar[str] = "xex"
