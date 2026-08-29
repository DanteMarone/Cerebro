"""`InferenceAttempt`: durable provider dispatch identity.

The dispatch barrier here is the whole point of the type. Before any byte can leave the process
the attempt is marked `dispatch_may_have_escaped`, which means a crash can leave a false
positive — an attempt that looks dispatched when the socket never opened. That is the safe
direction. The unsafe inference, and the one this ordering forbids, is concluding that a missing
local completion proves the provider was never called.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from cerebro.harness.errors import InferenceError
from cerebro.harness.exceptions import HarnessStateError
from cerebro.harness.ids import AgentTurnId, InferenceAttemptId, StepSnapshotId

__all__ = [
    "INFERENCE_ATTEMPT_FORMAT_VERSION",
    "InferenceAttempt",
    "InferenceCompletionStatus",
    "ProviderAttemptSemanticState",
    "ProviderDispatchState",
]

INFERENCE_ATTEMPT_FORMAT_VERSION = 1

ProviderDispatchState = Literal[
    "admitted",
    "dispatch_may_have_escaped",
    "terminal",
]

ProviderAttemptSemanticState = Literal[
    "active",
    "completed",
    "failed",
    "abandoned",
    "cancelled_before_dispatch",
]

InferenceCompletionStatus = Literal[
    "end_turn",
    "tool_calls_pending",
    "provider_continuation_required",
    "max_output_reached",
    "content_filtered_or_refused",
    "incomplete",
]

_DISPATCH_RANK: dict[str, int] = {
    "admitted": 0,
    "dispatch_may_have_escaped": 1,
    "terminal": 2,
}

_TERMINAL_SEMANTIC_STATES = frozenset(
    {"completed", "failed", "abandoned", "cancelled_before_dispatch"}
)


class InferenceAttempt(BaseModel):
    """One provider request identity, bound to one immutable step snapshot.

    Mutable on purpose: an attempt is a state machine, and the transitions below are the
    contract. Every transition is monotonic and refuses to move backwards.
    """

    model_config = {"validate_assignment": True}

    attempt_id: InferenceAttemptId
    format_version: int = INFERENCE_ATTEMPT_FORMAT_VERSION

    agent_turn_id: AgentTurnId
    step_snapshot_id: StepSnapshotId
    attempt_generation: int = 1
    turn_version_admitted: int = 0

    dispatch_state: ProviderDispatchState = "admitted"
    semantic_state: ProviderAttemptSemanticState = "active"

    # Kept separately from dispatch_state because `terminal` is reached by both a completed
    # request and a cancellation that never opened a socket. Folding the two together would
    # make every terminal attempt look like it may have escaped.
    dispatch_barrier_committed: bool = False

    request_semantic_hash: str
    provider_request_id: str | None = None
    error: InferenceError | None = None
    completion_status: InferenceCompletionStatus | None = None

    started_at: str | None = None
    completed_at: str | None = None

    abandonment_reason: str | None = None
    superseded_by_attempt_id: InferenceAttemptId | None = None

    trace_metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent_terminal_state(self) -> "InferenceAttempt":
        if self.attempt_generation < 1:
            raise ValueError("attempt_generation starts at 1")
        if self.semantic_state == "completed" and self.completion_status is None:
            raise ValueError("a completed attempt must record its completion_status")
        if self.semantic_state == "failed" and self.error is None:
            raise ValueError("a failed attempt must record its InferenceError")
        if self.dispatch_state == "dispatch_may_have_escaped" and not self.dispatch_barrier_committed:
            raise ValueError(
                "dispatch_state='dispatch_may_have_escaped' requires the barrier flag"
            )
        if self.semantic_state == "cancelled_before_dispatch" and self.dispatch_barrier_committed:
            raise ValueError(
                "an attempt past the dispatch barrier cannot be cancelled_before_dispatch"
            )
        return self

    # -- state queries -------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        return self.semantic_state in _TERMINAL_SEMANTIC_STATES

    @property
    def may_have_reached_provider(self) -> bool:
        """True once the dispatch barrier committed, whether or not bytes actually left.

        Deliberately conservative. Recovery reads this as "assume the provider saw it".
        """
        return self.dispatch_barrier_committed

    def accepts_late_event(
        self,
        *,
        active_attempt_id: InferenceAttemptId,
        expected_snapshot_id: StepSnapshotId,
    ) -> bool:
        """Whether an event from this attempt may still affect current turn semantics.

        A late `OutputItemCompleted` from an abandoned attempt is audit evidence. It cannot
        authorise a tool, enter canonical history or complete a turn.
        """
        if self.attempt_id != active_attempt_id:
            return False
        if self.step_snapshot_id != expected_snapshot_id:
            return False
        return self.semantic_state == "active"

    # -- transitions ---------------------------------------------------------------

    def _advance_dispatch(self, target: ProviderDispatchState) -> None:
        if _DISPATCH_RANK[target] < _DISPATCH_RANK[self.dispatch_state]:
            raise HarnessStateError(
                f"dispatch_state cannot move {self.dispatch_state} -> {target}"
            )
        self.dispatch_state = target

    def mark_dispatch_may_have_escaped(self, *, started_at: str | None = None) -> None:
        """Commit the pre-dispatch barrier. Must precede any adapter network call."""
        if self.semantic_state != "active":
            raise HarnessStateError(
                f"cannot dispatch an attempt in semantic_state={self.semantic_state!r}"
            )
        self.dispatch_barrier_committed = True
        self._advance_dispatch("dispatch_may_have_escaped")
        if started_at is not None and self.started_at is None:
            self.started_at = started_at

    def mark_cancelled_before_dispatch(self, *, completed_at: str | None = None) -> None:
        """Terminal cancellation that provably happened before the barrier committed."""
        if self.may_have_reached_provider:
            raise HarnessStateError(
                "attempt already passed the dispatch barrier; it cannot be recorded as "
                "cancelled_before_dispatch"
            )
        self._finish("cancelled_before_dispatch", completed_at=completed_at)

    def mark_completed(
        self,
        status: InferenceCompletionStatus,
        *,
        completed_at: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        if not self.may_have_reached_provider:
            raise HarnessStateError(
                "an attempt cannot complete without passing the dispatch barrier first"
            )
        self.completion_status = status
        if provider_request_id is not None:
            self.provider_request_id = provider_request_id
        self._finish("completed", completed_at=completed_at)

    def mark_failed(self, error: InferenceError, *, completed_at: str | None = None) -> None:
        self.error = error
        self._finish("failed", completed_at=completed_at)

    def mark_abandoned(
        self,
        reason: str,
        *,
        superseded_by_attempt_id: InferenceAttemptId | None = None,
        completed_at: str | None = None,
    ) -> None:
        """Durably abandon this attempt.

        Abandonment is the semantic boundary a provider/model switch needs. It says nothing
        about whether the provider saw the request: `dispatch_state` keeps that separately.
        """
        self.abandonment_reason = reason
        self.superseded_by_attempt_id = superseded_by_attempt_id
        self._finish("abandoned", completed_at=completed_at)

    def _finish(
        self, semantic_state: ProviderAttemptSemanticState, *, completed_at: str | None
    ) -> None:
        if self.is_terminal:
            raise HarnessStateError(
                f"attempt already terminal ({self.semantic_state}); refusing to move to "
                f"{semantic_state}"
            )
        self.semantic_state = semantic_state
        self._advance_dispatch("terminal")
        if completed_at is not None:
            self.completed_at = completed_at
