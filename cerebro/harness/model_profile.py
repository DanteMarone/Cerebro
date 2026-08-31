"""`ProviderConfig` and `ModelProfile`.

Two different questions, kept apart because conflating them is how "OpenAI-compatible" came to
mean "behaves like OpenAI":

- `ProviderConfig` answers *where and how do I reach this endpoint*;
- `ModelProfile` answers *how does this model behave when I plan a request for it*.

An endpoint speaking the OpenAI chat-completions wire format is a wire family, not proof of
semantic capability. A server that accepts a `tools` array and silently ignores it is not a
tool-calling model, and only the profile can say so.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from cerebro.harness.ids import ModelProfileId, ProviderConfigId

__all__ = [
    "InstructionRoleFidelity",
    "ModelProfile",
    "OpaqueReplayBehavior",
    "ProviderConfig",
    "ReasoningSummarySupport",
    "ToolCallingMode",
]

ToolCallingMode = Literal["unsupported", "emulated", "native"]

OpaqueReplayBehavior = Literal[
    "none_required",
    "optional_fidelity",
    "required_for_correctness",
]

ReasoningSummarySupport = Literal["none", "summary", "full_visible"]

InstructionRoleFidelity = Literal[
    "system_only",
    "system_and_developer",
    "instructions_field",
]


class ProviderConfig(BaseModel):
    """How to reach one provider endpoint.

    There is no credential field. `credential_reference` names a secret that the transport layer
    resolves at call time, so a snapshot, an event or a serialized request can never carry one.
    """

    model_config = {"frozen": True}

    config_id: ProviderConfigId
    provider_id: str
    endpoint: str
    dialect_id: str
    dialect_version: str
    api_version: str | None = None
    credential_reference: str | None = None
    timeout_s: float = 300.0
    transport_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_inline_secret(self) -> "ProviderConfig":
        forbidden = {"api_key", "authorization", "token", "secret", "password"}
        leaked = forbidden & {k.lower() for k in self.transport_options}
        if leaked:
            raise ValueError(
                f"transport_options must not carry credentials: {sorted(leaked)}; use "
                f"credential_reference instead"
            )
        return self


class ModelProfile(BaseModel):
    """Versioned behaviour and capability data for one model."""

    model_config = {"frozen": True, "protected_namespaces": ()}

    profile_id: ModelProfileId
    version: int = 1
    model_id: str

    context_window_tokens: int
    usable_context_tokens: int
    max_output_tokens: int | None = None
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])

    tool_calling_mode: ToolCallingMode = "native"
    tool_input_forms: list[str] = Field(default_factory=lambda: ["json"])
    supports_parallel_client_tools: bool = False
    supports_structured_output: bool = False

    reasoning_control_modes: list[str] = Field(default_factory=list)
    reasoning_summary_support: ReasoningSummarySupport = "none"
    opaque_replay_behavior: OpaqueReplayBehavior = "none_required"
    instruction_role_fidelity: InstructionRoleFidelity = "system_only"
    stateless_lossless_replay: bool = True
    hosted_tool_capability_names: list[str] = Field(default_factory=list)
    parameter_incompatibilities: list[str] = Field(default_factory=list)
    token_estimation_policy: str = "provider_reported"

    @model_validator(mode="after")
    def _budget_is_coherent(self) -> "ModelProfile":
        if self.usable_context_tokens > self.context_window_tokens:
            raise ValueError("usable_context_tokens cannot exceed context_window_tokens")
        if self.usable_context_tokens <= 0:
            raise ValueError("usable_context_tokens must be positive")
        return self

    @property
    def requires_opaque_replay(self) -> bool:
        return self.opaque_replay_behavior == "required_for_correctness"
