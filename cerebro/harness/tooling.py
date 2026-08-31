"""Canonical tool identity, definition, binding and recovery-capability types.

These are the tool-side contracts the Harness needs before anything is persisted or executed.
The projection of live CoreTools/MCP state into a frozen `ToolPlanSnapshot` is PR 3 work and is
deliberately absent here.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

from cerebro.harness.content import Provenance
from cerebro.harness.ids import ToolBindingGeneration

__all__ = [
    "EffectClass",
    "JsonToolInput",
    "ProviderOpaqueToolInput",
    "RepeatSemantics",
    "TextToolInput",
    "ToolBinding",
    "ToolDefinition",
    "ToolInput",
    "ToolKey",
    "ToolRecoveryCapability",
    "ToolResultStatus",
    "ToolSourceType",
]

ToolSourceType = Literal["core", "mcp", "connector", "extension"]

EffectClass = Literal["read_only", "side_effecting"]

RepeatSemantics = Literal[
    "idempotent",
    "stable_idempotency_key",
    "reconcile_before_repeat",
    "never_automatic_repeat",
]

ToolResultStatus = Literal[
    "success",
    "error",
    "denied",
    "cancelled_before_dispatch",
    "timeout",
    "unavailable",
    "indeterminate",
]

_KEY_SEPARATOR = "/"


class ToolKey(BaseModel):
    """Canonical tool identity.

    A provider wire name (`fs_read`, `filesystem__read_file`) is an edge serialization detail of
    one dialect. It is never this identity, because two providers may name the same executable
    binding differently and one provider may rename it between requests.
    """

    model_config = {"frozen": True}

    source_type: ToolSourceType
    source_id: str
    namespace: str
    name: str

    @model_validator(mode="after")
    def _no_separator_in_parts(self) -> "ToolKey":
        for field in ("source_id", "namespace", "name"):
            value = getattr(self, field)
            if not value:
                raise ValueError(f"ToolKey.{field} must not be empty")
            if _KEY_SEPARATOR in value:
                raise ValueError(
                    f"ToolKey.{field} must not contain {_KEY_SEPARATOR!r}: {value!r}"
                )
        return self

    def canonical(self) -> str:
        """Stable text encoding, used for equality in logs and durable references."""
        return _KEY_SEPARATOR.join(
            [self.source_type, self.source_id, self.namespace, self.name]
        )

    @classmethod
    def parse(cls, text: str) -> "ToolKey":
        parts = text.split(_KEY_SEPARATOR)
        if len(parts) != 4:
            raise ValueError(f"not a canonical ToolKey: {text!r}")
        source_type, source_id, namespace, name = parts
        return cls(
            source_type=source_type,  # type: ignore[arg-type]
            source_id=source_id,
            namespace=namespace,
            name=name,
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.canonical()


class JsonToolInput(BaseModel):
    """Canonical JSON arguments. The only form current CoreTools/MCP execution accepts."""

    model_config = {"frozen": True}

    input_form: Literal["json"] = "json"
    value: Any


class TextToolInput(BaseModel):
    """Free text arguments.

    Representable so that a model which emitted unparseable arguments produces a truthful
    canonical item rather than a fabricated JSON object. Not executable by current tools.
    """

    model_config = {"frozen": True}

    input_form: Literal["text"] = "text"
    text: str


class ProviderOpaqueToolInput(BaseModel):
    """Provider-defined argument encoding. Representable, not currently executable."""

    model_config = {"frozen": True}

    input_form: Literal["provider_opaque"] = "provider_opaque"
    provider_id: str
    payload: str


ToolInput = Annotated[
    Union[JsonToolInput, TextToolInput, ProviderOpaqueToolInput],
    Field(discriminator="input_form"),
]


class ToolRecoveryCapability(BaseModel):
    """What the executor actually promises about repeating one call.

    This is the only thing that may authorise an automatic second dispatch after the first one
    may have escaped. A static `parallel_safe` flag is not a recovery guarantee and is
    deliberately not modelled here.
    """

    model_config = {"frozen": True}

    effect_class: EffectClass
    repeat_semantics: RepeatSemantics
    reconciliation_binding: str | None = None
    operation_key_policy: str | None = None

    @model_validator(mode="after")
    def _reconcile_needs_binding(self) -> "ToolRecoveryCapability":
        if self.repeat_semantics == "reconcile_before_repeat" and not self.reconciliation_binding:
            raise ValueError(
                "repeat_semantics='reconcile_before_repeat' requires a reconciliation_binding; "
                "an unnamed reconciliation is not an authoritative lookup"
            )
        return self

    @property
    def requires_stable_operation_key(self) -> bool:
        return self.repeat_semantics == "stable_idempotency_key"

    @property
    def allows_automatic_repeat_after_escape(self) -> bool:
        """True only when the executor proves repeating is safe.

        `read_only` alone is not enough: the executor must also say the operation has no
        externally relevant effect, which is what `idempotent` means here.
        """
        if self.repeat_semantics == "idempotent":
            return True
        if self.repeat_semantics == "stable_idempotency_key":
            return True
        return False


class ToolDefinition(BaseModel):
    """A tool as offered to a model for one step."""

    model_config = {"frozen": True}

    key: ToolKey
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class ToolBinding(BaseModel):
    """The executable identity a call is frozen against.

    Execution re-checks this exact binding generation; it never rebinds a stale call to whatever
    currently answers to the same name.
    """

    model_config = {"frozen": True}

    key: ToolKey
    executor_identity: str
    binding_generation: ToolBindingGeneration
    catalog_version: int
    policy_version: int
    recovery_capability: ToolRecoveryCapability
