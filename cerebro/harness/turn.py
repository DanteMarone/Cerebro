"""`AgentTurn`: the durable unit of agent execution.

This is the contract type only. Admission, the recovery driver and every table that will hold it
belong to later Harness PRs. What matters here is that the fields exist with their exact
meanings, because the rest of the model refers to them:

- `product_outcome_kind` is the finalization discriminator (AR-05). `final_message_id` is
  evidence, never the predicate — a topic PASS legitimately has no final row, and treating a
  missing id as "not finalized yet" is how a completed turn finalizes twice;
- `needs_attention` / `unresolved_effect_count` are the attention projection (AR-04). A turn that
  ends while an external effect is still uncertain stays flagged; termination is not resolution.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from cerebro.harness.exceptions import HarnessStateError
from cerebro.harness.ids import (
    AgentTurnId,
    ConversationTurnId,
    InferenceAttemptId,
    StepSnapshotId,
)
from cerebro.harness.wake import CausalWakeKey

__all__ = [
    "AGENT_TURN_FORMAT_VERSION",
    "AgentTurn",
    "AgentTurnLifecycle",
    "ProductOutcomeKind",
]

AGENT_TURN_FORMAT_VERSION = 1

AgentTurnLifecycle = Literal[
    "queued",
    "running",
    "suspended",
    "completed",
    "cancelled",
    "failed",
]

ProductOutcomeKind = Literal[
    "final_message",
    "topic_pass",
    "topic_silent_stop",
    "fail_closed_error",
]

_TERMINAL_LIFECYCLES = frozenset({"completed", "cancelled", "failed"})

# Outcomes that must be backed by a collaboration row.
_OUTCOMES_WITH_MESSAGE = frozenset({"final_message", "fail_closed_error"})


class AgentTurn(BaseModel):
    """One agent execution admitted from one causal wake.

    Assignment validation is off for the same reason as `ToolExecution`: the attention
    projection is two fields that are only coherent together. The transitions re-check.
    """

    model_config = {"validate_assignment": False}

    id: AgentTurnId
    format_version: int = AGENT_TURN_FORMAT_VERSION
    state_version: int = 0
    execution_epoch: int = 0

    conversation_turn_id: ConversationTurnId
    causal_wake_key: CausalWakeKey
    trigger_message_id: int | None = None
    channel_id: str
    agent_id: str

    root_agent_turn_id: AgentTurnId | None = None
    parent_agent_turn_id: AgentTurnId | None = None
    product_task_id: str | None = None

    lifecycle: AgentTurnLifecycle = "queued"
    suspension_reason: str | None = None
    cancel_requested_at: str | None = None

    current_step_index: int = 0
    active_step_snapshot_id: StepSnapshotId | None = None
    active_inference_attempt_id: InferenceAttemptId | None = None

    product_outcome_kind: ProductOutcomeKind | None = None
    final_message_id: int | None = None
    failure_kind: str | None = None
    failure_detail: dict[str, Any] | None = None

    # AR-04 attention projection, maintained with the ToolExecution transitions that cause it.
    needs_attention: bool = False
    unresolved_effect_count: int = 0

    created_at: str
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    trace_metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _terminal_state_is_coherent(self) -> "AgentTurn":
        if self.unresolved_effect_count < 0:
            raise ValueError("unresolved_effect_count cannot be negative")
        if self.lifecycle == "completed" and self.product_outcome_kind is None:
            raise ValueError("a completed turn requires an explicit product outcome")
        if (
            self.product_outcome_kind in _OUTCOMES_WITH_MESSAGE
            and self.lifecycle == "completed"
            and self.final_message_id is None
        ):
            raise ValueError(
                f"product_outcome_kind={self.product_outcome_kind!r} requires a final_message_id"
            )
        if self.lifecycle == "suspended" and not self.suspension_reason:
            raise ValueError("a suspended turn requires an explicit suspension_reason")
        if self.unresolved_effect_count > 0 and not self.needs_attention:
            raise ValueError(
                "a turn with unresolved external effects must be flagged needs_attention"
            )
        return self

    @property
    def is_terminal(self) -> bool:
        return self.lifecycle in _TERMINAL_LIFECYCLES

    @property
    def is_finalized(self) -> bool:
        """The AR-05 idempotency predicate: the outcome discriminator, not the message id."""
        return self.product_outcome_kind is not None

    def bump_state_version(self, *, at: str | None = None) -> int:
        """Every authoritative transition advances this. Nothing else may."""
        self.state_version += 1
        if at is not None:
            self.updated_at = at
        return self.state_version

    def record_unresolved_effects(self, count: int) -> None:
        """Set the attention projection from current tool-execution truth.

        Only reconciliation clears the flag. Cancelling or failing a turn does not, because a
        mutation that may already have run does not become irrelevant when the turn gives up.
        """
        if count < 0:
            raise HarnessStateError("unresolved_effect_count cannot be negative")
        self.needs_attention = count > 0
        self.unresolved_effect_count = count
        self._terminal_state_is_coherent()
