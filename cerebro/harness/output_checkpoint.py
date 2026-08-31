"""Authoritative finalized provider output checkpointing (section 17 A-C, G, H).

One rule holds this module together: **a delta is never authority**. A provider can stream a
complete-looking tool name and complete-looking JSON arguments and then never finalize the item,
or finalize it without the replay handle the continuation needs. Nothing here persists a delta,
so nothing downstream can mistake one for an admitted call.

The second rule is attribution. A finalized item names the attempt that produced it, and an
attempt that has been abandoned or superseded no longer speaks for the turn. Late output from
such an attempt is kept out of current history and current tool admission rather than being
merged in because it arrived last.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from cerebro.harness.events import OutputItemCompleted, is_authoritative
from cerebro.harness.exceptions import HarnessStateError
from cerebro.harness.ids import InferenceAttemptId, StepSnapshotId
from cerebro.harness.items import InferenceItem
from cerebro.harness.turn import AgentTurn

__all__ = [
    "OutputAdmission",
    "ProviderOutputCoordinator",
    "RejectedOutput",
]


@dataclass(frozen=True)
class RejectedOutput:
    """Output that was observed but may not change current semantic history."""

    reason: str
    attempt_id: InferenceAttemptId | None
    item_type: str | None = None

    def describe(self) -> dict[str, Any]:
        """Log-safe projection. Carries no payload, opaque or otherwise."""
        return {
            "reason": self.reason,
            "attempt_id": str(self.attempt_id) if self.attempt_id is not None else None,
            "item_type": self.item_type,
        }


@dataclass(frozen=True)
class OutputAdmission:
    """The result of offering one provider event stream to the durable checkpoint."""

    accepted: tuple[InferenceItem, ...]
    rejected: tuple[RejectedOutput, ...]
    observed_deltas: int
    history_version: int
    replay_version: int

    @property
    def admitted_any(self) -> bool:
        return bool(self.accepted)


class ProviderOutputCoordinator:
    """Persists finalized provider output for the active attempt, and nothing else."""

    def __init__(self, store: Any) -> None:
        self.store = store

    async def accept(
        self,
        events: Iterable[Any],
        *,
        turn: AgentTurn,
        snapshot_id: StepSnapshotId,
        active_attempt_id: InferenceAttemptId,
        expected_history_version: int,
        at: str | None = None,
    ) -> OutputAdmission:
        """Append the authoritative finalized items from one attempt, in provider order.

        Returns the admission result instead of raising for stale output: a late item from an
        abandoned attempt is legitimate audit evidence, and treating it as a crash would make
        every provider/model switch look like a failure.
        """
        if turn.active_inference_attempt_id != active_attempt_id:
            raise HarnessStateError(
                "the output checkpoint only accepts output from the turn's active attempt"
            )
        if turn.active_step_snapshot_id != snapshot_id:
            raise HarnessStateError(
                "the output checkpoint only accepts output for the turn's active snapshot"
            )
        stored_attempt = await self.store.get_inference_attempt(active_attempt_id)
        attempt = stored_attempt.attempt
        if not attempt.accepts_late_event(
            active_attempt_id=active_attempt_id, expected_snapshot_id=snapshot_id
        ):
            raise HarnessStateError(
                f"attempt {active_attempt_id} is {attempt.semantic_state} and bound to "
                f"{attempt.step_snapshot_id}; it cannot commit current output"
            )

        accepted: list[InferenceItem] = []
        rejected: list[RejectedOutput] = []
        deltas = 0

        for event in events:
            if not is_authoritative(event):
                # Deltas exist for the interface and for parser progress. They are counted so a
                # test can prove they arrived, and then discarded.
                deltas += 1
                continue
            if not isinstance(event, OutputItemCompleted):
                continue
            if event.attempt_id != active_attempt_id:
                rejected.append(
                    RejectedOutput(
                        reason="stale_or_non_active_attempt",
                        attempt_id=event.attempt_id,
                        item_type=getattr(event.item, "item_type", None),
                    )
                )
                continue
            item = event.item
            if getattr(item, "origin", None) != "provider_attempt":
                rejected.append(
                    RejectedOutput(
                        reason="not_provider_originated",
                        attempt_id=event.attempt_id,
                        item_type=getattr(item, "item_type", None),
                    )
                )
                continue
            if item.producing_attempt_id != active_attempt_id:
                rejected.append(
                    RejectedOutput(
                        reason="attempt_attribution_mismatch",
                        attempt_id=item.producing_attempt_id,
                        item_type=item.item_type,
                    )
                )
                continue
            accepted.append(item)

        if not accepted:
            replay_version = await self.store.replay_version(turn.conversation_turn_id)
            return OutputAdmission(
                accepted=(),
                rejected=tuple(rejected),
                observed_deltas=deltas,
                history_version=expected_history_version,
                replay_version=replay_version,
            )

        stored_items, history_version = await self.store.append_inference_items(
            turn.conversation_turn_id,
            turn.id,
            accepted,
            expected_history_version=expected_history_version,
            at=at,
        )
        replay_version = await self.store.replay_version(turn.conversation_turn_id)
        return OutputAdmission(
            accepted=tuple(stored_items),
            rejected=tuple(rejected),
            observed_deltas=deltas,
            history_version=history_version,
            replay_version=replay_version,
        )

    async def reject_stale(
        self,
        events: Iterable[Any],
        *,
        active_attempt_id: InferenceAttemptId,
    ) -> tuple[RejectedOutput, ...]:
        """Classify output from an attempt that is no longer current, persisting nothing.

        Used where a late stream has to be drained: the caller gets a truthful record that the
        output arrived, and current history is untouched.
        """
        rejected: list[RejectedOutput] = []
        for event in events:
            if not isinstance(event, OutputItemCompleted):
                continue
            if event.attempt_id == active_attempt_id:
                continue
            rejected.append(
                RejectedOutput(
                    reason="stale_or_non_active_attempt",
                    attempt_id=event.attempt_id,
                    item_type=getattr(event.item, "item_type", None),
                )
            )
        return tuple(rejected)
