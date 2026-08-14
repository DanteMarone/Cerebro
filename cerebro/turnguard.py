"""Loop control for multi-agent conversations.

Cerebro agents talk to each other. Two agents that each feel obliged to reply will keep replying
until something stops them, and under decision D3 (full autonomy, no approval prompts) nothing
else will. This module is that something.

Every message carries a `turn_id` -- the conversational impulse that caused it -- and a `depth`.
A human message starts a new turn at depth 0; anything an agent says in response inherits the
turn and increments the depth. A turn that exceeds any of its limits is *frozen*: no further
agent messages are accepted on it, a system message asks for Dante, and only a human can start
things moving again by opening a new turn.

`AgentRateLimiter` covers the other loop shape -- an agent waking itself repeatedly via cron or
`create_channel` -- with a sliding window of self-initiated messages per agent.

Both classes take an injected clock so tests never sleep.
"""

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class Decision(str, Enum):
    ALLOW = "allow"
    FREEZE = "freeze"


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


ALLOWED = Verdict(Decision.ALLOW)


@dataclass(frozen=True, slots=True)
class TurnLimits:
    """Defaults mirror config.py; the runtime passes the configured values in."""

    max_depth: int = 8
    max_agent_messages: int = 12
    max_wallclock_s: float = 600.0


@dataclass(slots=True)
class TurnState:
    turn_id: str
    started_at: float
    agent_messages: int = 0
    max_depth_seen: int = 0
    frozen_reason: str | None = None
    last_activity: float = 0.0

    @property
    def frozen(self) -> bool:
        return self.frozen_reason is not None


class TurnFrozen(RuntimeError):
    """Raised when something tries to speak on a frozen turn."""

    def __init__(self, turn_id: str, reason: str) -> None:
        super().__init__(f"turn {turn_id} is frozen: {reason}")
        self.turn_id = turn_id
        self.reason = reason


def new_turn_id() -> str:
    return uuid.uuid4().hex[:16]


class TurnGuard:
    """Tracks live turns and decides whether another agent message may be produced.

    The runtime calls `check()` *before* asking a provider for a completion, and
    `record_agent_message()` after one is produced. Checking before spending tokens is the whole
    point -- freezing after the fact would still have paid for the inference.
    """

    def __init__(
        self,
        limits: TurnLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits or TurnLimits()
        self._clock = clock
        self._turns: dict[str, TurnState] = {}

    # -- lifecycle ----------------------------------------------------------------

    def start(self, turn_id: str | None = None) -> TurnState:
        """Open a turn. Called for every human message and every cron fire."""
        tid = turn_id or new_turn_id()
        now = self._clock()
        state = TurnState(turn_id=tid, started_at=now, last_activity=now)
        self._turns[tid] = state
        return state

    def get(self, turn_id: str) -> TurnState | None:
        return self._turns.get(turn_id)

    def _state(self, turn_id: str) -> TurnState:
        state = self._turns.get(turn_id)
        if state is None:
            state = self.start(turn_id)
        return state

    # -- the actual guard ---------------------------------------------------------

    def check(self, turn_id: str, depth: int) -> Verdict:
        """May an agent speak at `depth` on this turn? Freezes the turn if not.

        Freezing here (rather than merely refusing) is deliberate: if one agent has hit the
        ceiling, the conversation as a whole has run away, and letting its peers continue would
        just burn the budget more slowly.
        """
        state = self._state(turn_id)
        if state.frozen:
            return Verdict(Decision.FREEZE, state.frozen_reason or "frozen")

        if depth > self.limits.max_depth:
            return self._freeze(state, f"conversation depth {depth} exceeded the limit of "
                                       f"{self.limits.max_depth}")

        if state.agent_messages >= self.limits.max_agent_messages:
            return self._freeze(state, f"{state.agent_messages} agent messages exceeded the "
                                       f"limit of {self.limits.max_agent_messages} for one turn")

        elapsed = self._clock() - state.started_at
        if elapsed >= self.limits.max_wallclock_s:
            return self._freeze(state, f"turn ran for {elapsed:.0f}s, over the "
                                       f"{self.limits.max_wallclock_s:.0f}s limit")

        return ALLOWED

    def record_agent_message(self, turn_id: str, depth: int) -> TurnState:
        """Account for a message an agent actually produced."""
        state = self._state(turn_id)
        if state.frozen:
            raise TurnFrozen(turn_id, state.frozen_reason or "frozen")
        state.agent_messages += 1
        state.max_depth_seen = max(state.max_depth_seen, depth)
        state.last_activity = self._clock()
        return state

    def _freeze(self, state: TurnState, reason: str) -> Verdict:
        state.frozen_reason = reason
        state.last_activity = self._clock()
        return Verdict(Decision.FREEZE, reason)

    def freeze(self, turn_id: str, reason: str) -> Verdict:
        """Freeze explicitly -- used by the kill switch and by budget exhaustion."""
        return self._freeze(self._state(turn_id), reason)

    def is_frozen(self, turn_id: str) -> bool:
        state = self._turns.get(turn_id)
        return bool(state and state.frozen)

    def freeze_message(self, turn_id: str) -> str:
        """The system message posted into the channel when a turn freezes."""
        state = self._turns.get(turn_id)
        reason = (state.frozen_reason if state else None) or "turn budget exhausted"
        return f"Paused: {reason}. Reply to pick this back up."

    # -- housekeeping -------------------------------------------------------------

    def sweep(self, older_than_s: float = 3600.0) -> int:
        """Drop turn state that nothing can reference any more. Returns how many were dropped."""
        cutoff = self._clock() - older_than_s
        stale = [tid for tid, s in self._turns.items() if s.last_activity < cutoff]
        for tid in stale:
            del self._turns[tid]
        return len(stale)

    @property
    def live_turns(self) -> int:
        return len(self._turns)


class AgentRateLimiter:
    """Sliding-window cap on self-initiated messages, per agent.

    "Self-initiated" means anything an agent starts that a human did not: cron fires,
    `create_channel`, `post_message` into a channel it is not currently answering in. Replies
    within a turn are governed by `TurnGuard`, not here.
    """

    def __init__(
        self,
        max_per_hour: int = 6,
        window_s: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_per_hour = max_per_hour
        self.window_s = window_s
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, agent_id: str, now: float) -> deque[float]:
        events = self._events[agent_id]
        cutoff = now - self.window_s
        while events and events[0] < cutoff:
            events.popleft()
        return events

    def check(self, agent_id: str) -> Verdict:
        now = self._clock()
        events = self._prune(agent_id, now)
        if len(events) >= self.max_per_hour:
            wait = self.window_s - (now - events[0])
            return Verdict(
                Decision.FREEZE,
                f"{agent_id} has started {len(events)} conversations in the last hour "
                f"(limit {self.max_per_hour}); try again in {wait / 60:.0f} min",
            )
        return ALLOWED

    def record(self, agent_id: str) -> None:
        now = self._clock()
        self._prune(agent_id, now)
        self._events[agent_id].append(now)

    def remaining(self, agent_id: str) -> int:
        return max(0, self.max_per_hour - len(self._prune(agent_id, self._clock())))
