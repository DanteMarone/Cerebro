"""Conservative, side-effect-free restart admission for durable Harness turns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from cerebro.harness.ids import AgentTurnId
from cerebro.harness.store import HarnessStore

RecoveryAction = Literal["already_suspended", "suspended"]


@dataclass(frozen=True)
class RecoveryDecision:
    """One durable disposition produced from stored facts only."""

    turn_id: AgentTurnId
    action: RecoveryAction
    reason: str
    resulting_state_version: int


class TurnRecoveryDriver:
    """TurnCoordinator-owned startup primitive for the active execution epoch.

    Phase 1B has no reducer and accepts no provider adapter or tool executor. Consequently the
    only safe disposition for queued/running work is durable suspension. Already suspended work
    remains suspended until a future explicit resume disposition exists.
    """

    def __init__(self, store: HarnessStore) -> None:
        self._store = store

    async def scan(self, *, at: str | None = None) -> list[RecoveryDecision]:
        """Classify every active-epoch non-terminal turn without external side effects."""
        recovery_at = at or datetime.now(timezone.utc).isoformat()
        metadata = await self._store.metadata()
        turns = await self._store.list_non_terminal_turns(metadata.active_execution_epoch)
        decisions: list[RecoveryDecision] = []
        for turn in turns:
            if turn.lifecycle == "suspended":
                decisions.append(
                    RecoveryDecision(
                        turn.id,
                        "already_suspended",
                        turn.suspension_reason or "turn was already suspended",
                        turn.state_version,
                    )
                )
                continue
            unresolved = await self._store.list_unresolved_tool_executions(turn.id)
            if unresolved:
                reason = (
                    "restart found unresolved tool effect truth; Phase 1B cannot reconcile or "
                    "repeat external work"
                )
            elif turn.active_inference_attempt_id is not None:
                attempt = await self._store.get_inference_attempt(
                    turn.active_inference_attempt_id
                )
                if attempt.attempt.may_have_reached_provider:
                    reason = (
                        "restart found a provider attempt whose dispatch may have escaped; "
                        "Phase 1B has no provider reconciliation"
                    )
                else:
                    reason = (
                        "restart found durable pre-dispatch work, but the Phase 1B reducer is "
                        "not implemented"
                    )
            else:
                reason = "restart recovery requires the Phase 1C/1D durable reducer"
            suspended = await self._store.transition_turn(
                turn.id,
                expected_version=turn.state_version,
                lifecycle="suspended",
                suspension_reason=reason,
                at=recovery_at,
            )
            decisions.append(
                RecoveryDecision(turn.id, "suspended", reason, suspended.state_version)
            )
        return decisions
