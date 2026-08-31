"""The `ExternalAgentAdapter` boundary for CLI/ACP/vendor harnesses.

`claude -p`, `codex exec`, `agy` and `goose run` are not inference providers. Each launches a
harness that owns its own context, its own approvals, its own tools and its own side effects.
Cerebro sends a prompt and reads a reply; it does not see the steps in between and cannot
reconstruct them.

That is why this contract is separate from `ProviderAdapter` rather than a subclass of it. The
two share no base class and no request type on purpose: an external execution has no canonical
`InferenceItem` history, no `InferenceAttempt`, and no provider replay state, and modelling it as
though it did would let generic recovery code make promises about a subprocess it cannot keep.

Phase 1 claims nothing about restart recovery here. `reconcile_orphan` exists so the boundary is
complete, and it answers honestly: not supported, suspend the turn.
"""

from __future__ import annotations

from typing import Annotated, Any, AsyncIterator, Literal, Protocol, Union, runtime_checkable

from pydantic import BaseModel, Field

from cerebro.harness.ids import AgentTurnId, ExternalExecutionId

__all__ = [
    "ExternalAgentAdapter",
    "ExternalAgentEvent",
    "ExternalExecutionCompleted",
    "ExternalExecutionFailed",
    "ExternalExecutionRequest",
    "ExternalPromptTurn",
    "ExternalReasoningDelta",
    "ExternalRecoveryCapability",
    "ExternalTextDelta",
    "OrphanReconciliation",
]


class ExternalPromptTurn(BaseModel):
    """One labelled speaker turn in the prompt handed to an external harness.

    Not an `InferenceItem`. A CLI harness has no role protocol, so this is the smallest honest
    shape: who spoke and what they said.
    """

    model_config = {"frozen": True}

    author_id: str
    author_kind: str
    body: str


class ExternalRecoveryCapability(BaseModel):
    """What an external adapter promises across a Cerebro restart.

    Every field defaults to "no". An adapter that wants to claim more has to say so explicitly,
    and Phase 1 has nothing that does.
    """

    model_config = {"frozen": True}

    supports_reconnect: bool = False
    supports_orphan_reconciliation: bool = False
    supports_resume: bool = False
    notes: str = ""


class ExternalExecutionRequest(BaseModel):
    """What an external harness needs to run one turn's worth of work."""

    model_config = {"frozen": True}

    execution_id: ExternalExecutionId
    agent_turn_id: AgentTurnId | None = None
    agent_id: str
    prompt_turns: list[ExternalPromptTurn]
    cwd: str | None = None
    timeout_s: float | None = None
    adapter_options: dict[str, Any] = Field(default_factory=dict)


class _ExternalEvent(BaseModel):
    model_config = {"frozen": True}

    execution_id: ExternalExecutionId


class ExternalTextDelta(_ExternalEvent):
    event_type: Literal["external_text_delta"] = "external_text_delta"
    text: str


class ExternalReasoningDelta(_ExternalEvent):
    """Harness-internal thinking. Private, exactly as it is today."""

    event_type: Literal["external_reasoning_delta"] = "external_reasoning_delta"
    text: str


class ExternalExecutionCompleted(_ExternalEvent):
    event_type: Literal["external_execution_completed"] = "external_execution_completed"
    reason: str = "stop"


class ExternalExecutionFailed(_ExternalEvent):
    event_type: Literal["external_execution_failed"] = "external_execution_failed"
    message: str
    unavailable: bool = False


ExternalAgentEvent = Annotated[
    Union[
        ExternalTextDelta,
        ExternalReasoningDelta,
        ExternalExecutionCompleted,
        ExternalExecutionFailed,
    ],
    Field(discriminator="event_type"),
]


class OrphanReconciliation(BaseModel):
    """The honest answer to "what happened to that subprocess we lost?"."""

    model_config = {"frozen": True}

    execution_id: ExternalExecutionId
    supported: bool
    disposition: Literal["resolved", "suspend"] = "suspend"
    reason: str


@runtime_checkable
class ExternalAgentAdapter(Protocol):
    """External harness execution. Structurally distinct from `ProviderAdapter`."""

    adapter_id: str
    recovery_capability: ExternalRecoveryCapability

    async def start_or_resume(
        self, request: ExternalExecutionRequest, cancel_token: Any
    ) -> Any:
        """Begin (or, when supported, resume) one external execution."""
        ...

    def stream_events(self, handle: Any) -> AsyncIterator[ExternalAgentEvent]:
        """Yield events from a started execution."""
        ...

    async def cancel(self, execution_id: ExternalExecutionId) -> None:
        """Stop the execution and any child process it owns."""
        ...

    async def reconcile_orphan(self, execution_id: ExternalExecutionId) -> OrphanReconciliation:
        """Say what became of an execution this process lost track of."""
        ...
