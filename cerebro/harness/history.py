"""Canonical ordered inference history and AR-02 supersession.

Two views of the same append-only collection:

- `canonical_request_history()` is what the next `InferenceRequest` may contain;
- `audit_history()` is everything that ever happened, including superseded evidence.

Supersession is the mechanism that lets an interrupted provider attempt be forgotten by the next
request without forgetting it happened. It is metadata, never a delete, and it never crosses a
committed or possibly-escaped external effect.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from cerebro.harness.exceptions import HarnessStateError
from cerebro.harness.ids import CerebroCallId, ConversationTurnId, InferenceAttemptId
from cerebro.harness.items import InferenceItem, ToolCallItem, ToolResultItem, item_sort_key

__all__ = ["InferenceHistory"]


def _replace(item: Any, **changes: Any) -> Any:
    """Frozen models are copied, not mutated, so supersession is an explicit new object."""
    return item.model_copy(update=changes)


class InferenceHistory:
    """An ordered, versioned, conversation-owned item collection.

    Ownership is conversation-scoped from the start (AR-03): a `conversation` retention-scope
    replay item has to outlive the turn that produced it, and re-keying that collection later
    would be a migration of exactly the state that must not move.
    """

    def __init__(
        self,
        conversation_turn_id: ConversationTurnId,
        items: Iterable[InferenceItem] = (),
        *,
        version: int = 0,
    ) -> None:
        self.conversation_turn_id = conversation_turn_id
        self.version = version
        self._items: list[Any] = sorted(items, key=item_sort_key)
        self._next_sequence = self._initial_sequence()

    def _initial_sequence(self) -> int:
        used = [i.sequence_no for i in self._items if i.sequence_no is not None]
        return (max(used) + 1) if used else 0

    # -- reads ----------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def audit_history(self) -> list[Any]:
        """Everything, superseded items included, in canonical order."""
        return list(self._items)

    def canonical_request_history(self) -> list[Any]:
        """The items a subsequent provider request may legitimately contain."""
        return [item for item in self._items if not item.is_superseded]

    def items_for_attempt(self, attempt_id: InferenceAttemptId) -> list[Any]:
        return [item for item in self._items if item.producing_attempt_id == attempt_id]

    # -- writes ---------------------------------------------------------------------

    def append(self, item: InferenceItem) -> Any:
        """Append one finalized item, assigning its sequence number if it has none.

        Only finalized items reach here. A streaming delta has no identity, no ordering and no
        authority, and there is deliberately no path from one to this method.
        """
        if item.sequence_no is None:
            item = _replace(item, sequence_no=self._next_sequence)
        elif item.sequence_no < self._next_sequence:
            raise HarnessStateError(
                f"sequence_no {item.sequence_no} is behind the history head "
                f"{self._next_sequence}; canonical history is append-only"
            )
        self._next_sequence = item.sequence_no + 1
        self._items.append(item)
        self._items.sort(key=item_sort_key)
        self.version += 1
        return item

    def extend(self, items: Iterable[InferenceItem]) -> list[Any]:
        return [self.append(item) for item in items]

    def supersede_abandoned_attempt(
        self,
        attempt_id: InferenceAttemptId,
        *,
        reason: str,
        at: str,
        protected_call_ids: Sequence[CerebroCallId] = (),
        superseding_attempt_id: InferenceAttemptId | None = None,
    ) -> list[Any]:
        """Mark an abandoned attempt's unprotected output superseded (AR-02).

        The rule, and why it is shaped this way:

        - output that authorised no dispatched side effect is attempt-scoped, so on abandonment
          it becomes audit evidence and leaves the next request. Otherwise an incomplete
          assistant turn silently becomes a prefill the model is asked to continue;
        - the smallest ordered prefix that preserves the causal history of a dispatched or
          committed effect stays active. Cerebro never rewinds across an effect that may already
          have escaped, so that prefix is not superseded merely to retry the provider;
        - trailing output after the last protected effect boundary may be superseded.

        Active committed `ToolResultItem`s are protection evidence in their own right. Caller-
        supplied ids remain necessary for possibly escaped calls that have no result yet.

        Returns the items that were superseded.
        """
        active_attempt_calls = {
            item.call_id
            for item in self._items
            if isinstance(item, ToolCallItem)
            and item.producing_attempt_id == attempt_id
            and not item.is_superseded
        }
        committed_result_calls = {
            item.call_id
            for item in self._items
            if isinstance(item, ToolResultItem)
            and not item.is_superseded
            and item.call_id in active_attempt_calls
        }
        protected = set(protected_call_ids) | committed_result_calls
        positions = [
            index for index, item in enumerate(self._items)
            if item.producing_attempt_id == attempt_id and not item.is_superseded
        ]
        if not positions:
            return []

        boundary = -1
        for rank, position in enumerate(positions):
            item = self._items[position]
            if getattr(item, "item_type", None) == "tool_call" and item.call_id in protected:
                boundary = rank

        superseded: list[Any] = []
        for rank, position in enumerate(positions):
            if rank <= boundary:
                continue
            updated = _replace(
                self._items[position],
                superseded_at=at,
                superseded_reason=reason,
                superseding_attempt_id=superseding_attempt_id,
            )
            self._items[position] = updated
            superseded.append(updated)

        if superseded:
            self.version += 1
        return superseded
