"""`ToolExecution`: one admitted call's durable, monotonic execution state.

The three dispatch states exist because "no result" has two very different meanings. Before the
dispatch mark commits, no external effect can have happened. After it commits, the effect may
have escaped and no local evidence can prove otherwise. Collapsing those into "failed" is how a
retry becomes a second payment.

`indeterminate_needs_attention` is a truthful terminal resolution, not a placeholder. It is what
the harness records when the effect truth cannot be recovered, and it stays visible rather than
being tidied into a fabricated failure.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

from cerebro.harness.exceptions import HarnessStateError
from cerebro.harness.ids import (
    AgentTurnId,
    ArtifactRef,
    CerebroCallId,
    InferenceItemId,
    StepSnapshotId,
    ToolBindingGeneration,
)
from cerebro.harness.tooling import ToolKey, ToolRecoveryCapability, ToolResultStatus

__all__ = [
    "IndeterminateResolution",
    "KnownResolution",
    "TOOL_EXECUTION_FORMAT_VERSION",
    "ToolDispatchState",
    "ToolExecution",
    "ToolResolution",
]

TOOL_EXECUTION_FORMAT_VERSION = 1

ToolDispatchState = Literal["not_dispatched", "dispatch_may_have_escaped", "resolved"]

_DISPATCH_RANK: dict[str, int] = {
    "not_dispatched": 0,
    "dispatch_may_have_escaped": 1,
    "resolved": 2,
}

# Outcomes that are provable without ever invoking the executor.
_PRE_DISPATCH_STATUSES = frozenset(
    {"denied", "cancelled_before_dispatch", "unavailable", "error"}
)


class KnownResolution(BaseModel):
    """The executor gave an authoritative outcome."""

    model_config = {"frozen": True}

    resolution_kind: Literal["known"] = "known"
    status: ToolResultStatus

    @model_validator(mode="after")
    def _known_is_not_indeterminate(self) -> "KnownResolution":
        if self.status == "indeterminate":
            raise ValueError(
                "status='indeterminate' is not a known outcome; use IndeterminateResolution"
            )
        return self


class IndeterminateResolution(BaseModel):
    """The effect may have happened and no authority can say whether it did."""

    model_config = {"frozen": True}

    resolution_kind: Literal["indeterminate"] = "indeterminate"
    reason: str
    reconciliation_attempted: bool = False


ToolResolution = Annotated[
    Union[KnownResolution, IndeterminateResolution],
    Field(discriminator="resolution_kind"),
]


class ToolExecution(BaseModel):
    """One `CerebroCallId`'s durable execution record.

    Assignment validation is off because the transitions below move two fields at once and
    the invariant only holds across the pair. Each transition re-checks it explicitly when it
    is done, so the state machine is still the contract.
    """

    model_config = {"validate_assignment": False}

    call_id: CerebroCallId
    format_version: int = TOOL_EXECUTION_FORMAT_VERSION

    agent_turn_id: AgentTurnId
    step_snapshot_id: StepSnapshotId
    tool_call_item_id: InferenceItemId
    tool_key: ToolKey
    admitted_turn_version: int = 0

    dispatch_state: ToolDispatchState = "not_dispatched"
    resolution: ToolResolution | None = None

    binding_generation: ToolBindingGeneration
    recovery_capability: ToolRecoveryCapability
    stable_operation_key: str | None = None

    raw_output_ref: ArtifactRef | None = None
    model_output_item_id: InferenceItemId | None = None

    admitted_at: str
    dispatch_marked_at: str | None = None
    resolved_at: str | None = None

    @model_validator(mode="after")
    def _resolution_matches_state(self) -> "ToolExecution":
        if self.dispatch_state == "resolved" and self.resolution is None:
            raise ValueError("a resolved ToolExecution must carry its resolution")
        if self.dispatch_state != "resolved" and self.resolution is not None:
            raise ValueError("only a resolved ToolExecution may carry a resolution")
        return self

    # -- queries --------------------------------------------------------------------

    @property
    def may_have_escaped(self) -> bool:
        return _DISPATCH_RANK[self.dispatch_state] >= 1 and self.dispatch_marked_at is not None

    @property
    def is_unresolved_effect(self) -> bool:
        """Whether this execution contributes to the turn's attention projection (AR-04).

        An execution that may have escaped and has no known outcome counts. A terminal
        `indeterminate` resolution keeps counting, because the effect is still unreconciled and
        turn termination must not make it disappear.
        """
        if not self.may_have_escaped:
            return False
        if self.resolution is None:
            return True
        return self.resolution.resolution_kind == "indeterminate"

    @property
    def dispatch_eligible(self) -> bool:
        """Whether the pre-dispatch barrier's operation-key precondition (E2) is satisfied."""
        if self.recovery_capability.requires_stable_operation_key:
            return bool(self.stable_operation_key)
        return True

    def may_repeat_dispatch(self) -> bool:
        """Whether a second dispatch is permitted after the first may have escaped.

        Only executor-proved semantics authorise this. Everything else resolves or suspends;
        Cerebro does not promise generic exactly-once external effects.
        """
        if not self.may_have_escaped:
            return True
        return self.recovery_capability.allows_automatic_repeat_after_escape

    # -- transitions ----------------------------------------------------------------

    def _advance(self, target: ToolDispatchState) -> None:
        if _DISPATCH_RANK[target] < _DISPATCH_RANK[self.dispatch_state]:
            raise HarnessStateError(
                f"tool dispatch_state cannot move {self.dispatch_state} -> {target}"
            )
        if self.dispatch_state == "resolved":
            raise HarnessStateError(
                "a resolved ToolExecution is terminal; a later timeout or cancellation cannot "
                "overwrite a recorded outcome"
            )
        self.dispatch_state = target

    def assign_stable_operation_key(self, key: str) -> None:
        """Persist the durable operation key before dispatch eligibility (AR-06, E2).

        Reused unchanged across every retry, which is the whole reason it is durable rather than
        regenerated: a fresh key on retry is a second mutation with extra steps.
        """
        if self.stable_operation_key is not None and self.stable_operation_key != key:
            raise HarnessStateError(
                "stable_operation_key is already assigned; reusing a different key would defeat "
                "externally enforced idempotency"
            )
        if self.may_have_escaped:
            raise HarnessStateError(
                "stable_operation_key must be assigned before the dispatch mark commits"
            )
        self.stable_operation_key = key

    def mark_dispatch_may_have_escaped(self, *, at: str) -> None:
        """Commit the dispatch mark. Must precede any executor invocation."""
        if not self.dispatch_eligible:
            raise HarnessStateError(
                f"tool {self.tool_key.canonical()} declares "
                f"repeat_semantics='stable_idempotency_key' but no stable_operation_key is "
                f"persisted; dispatch is not eligible"
            )
        self._advance("dispatch_may_have_escaped")
        self.dispatch_marked_at = at
        self._resolution_matches_state()

    def resolve_known(
        self,
        status: ToolResultStatus,
        *,
        at: str,
        raw_output_ref: ArtifactRef | None = None,
        model_output_item_id: InferenceItemId | None = None,
    ) -> None:
        """Record an authoritative outcome."""
        if status == "indeterminate":
            raise HarnessStateError(
                "use resolve_indeterminate for an unknown outcome; 'indeterminate' is not a "
                "known status"
            )
        if not self.may_have_escaped and status not in _PRE_DISPATCH_STATUSES:
            raise HarnessStateError(
                f"status={status!r} cannot be recorded for a call that was never dispatched"
            )
        self._advance("resolved")
        self.resolution = KnownResolution(status=status)
        self.resolved_at = at
        if raw_output_ref is not None:
            self.raw_output_ref = raw_output_ref
        if model_output_item_id is not None:
            self.model_output_item_id = model_output_item_id
        self._resolution_matches_state()

    def resolve_indeterminate(
        self, reason: str, *, at: str, reconciliation_attempted: bool = False
    ) -> None:
        """Record the truthful terminal outcome when effect truth cannot be recovered."""
        if not self.may_have_escaped:
            raise HarnessStateError(
                "a call that never passed the dispatch mark has a known non-effect; recording "
                "it as indeterminate would invent uncertainty"
            )
        self._advance("resolved")
        self.resolution = IndeterminateResolution(
            reason=reason, reconciliation_attempted=reconciliation_attempted
        )
        self.resolved_at = at
        self._resolution_matches_state()
