"""Agents watch their own channels (§6).

Right now every agent hand-rolls a watcher outside Cerebro — Claude has one, Antigravity has one,
Codex has one. Three implementations of one thing, none of which survive their session closing,
which is why Codex is asleep and why Dante went unanswered for three hours this morning. This is
that thing, once, inside the process that already knows who is in which channel.

The design is Dante's, and it is not the one I originally specified. There is no moderator model
deciding who may speak: each agent looks at what it has not seen and decides for itself, exactly
as the humans-and-agents war room worked. Two consequences shape everything here.

**Deciding and speaking are one call.** Asking an agent "should you speak?" and then asking it to
speak costs two inferences to produce one message. Instead the agent takes an ordinary turn and
replies `PASS` if it has nothing to add; the runtime discards that. One inference either way.

**Batching is what makes it affordable.** An agent waking to five new messages evaluates them in
a single turn, not five. With N agents in a channel the cost is N inferences per polling round
rather than per message, and the poll interval is the dial.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from cerebro.models import Agent

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 45.0
DEFAULT_TICK_S = 5.0
MAX_BACKOFF_S = 1800.0
MAX_CONSECUTIVE_FAILURES = 4


@dataclass
class AgentState:
    """What the poller remembers between ticks."""

    agent_id: str
    interval_s: float
    last_polled_at: float = 0.0
    cursors: dict[str, int] = field(default_factory=dict)
    consecutive_failures: int = 0

    @property
    def backoff_s(self) -> float:
        """Wait longer after each failure, and stop entirely after enough of them.

        A misconfigured agent polling on a fixed interval retries forever and posts its error
        every cycle. Codex did exactly that: a bad line in its own config produced an identical
        failure message every 45 seconds, which is noise, rows, and — for a backend that gets far
        enough to start — real money.
        """
        if self.consecutive_failures == 0:
            return 0.0
        return min(self.interval_s * (2 ** self.consecutive_failures), MAX_BACKOFF_S)

    @property
    def given_up(self) -> bool:
        return self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES


class ChannelPoller:
    """Wakes each agent on its own interval when its channels have moved.

    Dependencies are injected rather than imported so this can be tested without a database, a
    provider or a running app -- the same seam the runtime uses.
    """

    def __init__(
        self,
        list_agents: Callable[[], Awaitable[list[Agent]]],
        channels_for: Callable[[str], Awaitable[list[str]]],
        latest_message_id: Callable[[str], Awaitable[int]],
        run_turn: Callable[[Agent, str], Awaitable[object]],
        tick_s: float = DEFAULT_TICK_S,
        default_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.list_agents = list_agents
        self.channels_for = channels_for
        self.latest_message_id = latest_message_id
        self.run_turn = run_turn
        self.tick_s = tick_s
        self.default_interval_s = default_interval_s
        self._clock = clock
        self._states: dict[str, AgentState] = {}
        self._task: asyncio.Task | None = None
        self._running = asyncio.Event()
        self._in_flight: set[str] = set()

    # -- lifecycle ----------------------------------------------------------------

    async def start(self) -> None:
        self._running.set()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running.clear()
        if self._task:
            self._task.cancel()
            self._task = None

    def pause(self) -> None:
        """§8.6. The kill switch stops agents waking as well as stopping turns in flight."""
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    # -- the loop -----------------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.tick_s)
                if self.paused:
                    continue
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 - one bad tick must not end the loop
                logger.exception("poller tick failed")

    async def tick(self) -> int:
        """One pass over every agent. Returns how many turns were started."""
        started = 0
        for agent in await self.list_agents():
            if await self._consider(agent):
                started += 1
        return started

    async def _consider(self, agent: Agent) -> bool:
        state = self._state(agent)
        now = self._clock()

        if state.given_up:
            # Stop rather than retry forever. A human fixes the cause and turns polling back on;
            # the alternative is an agent that fails identically every interval until someone
            # notices, which is how a broken config became a message every 45 seconds.
            return False

        wait = max(state.interval_s, state.backoff_s)
        if now - state.last_polled_at < wait:
            return False
        state.last_polled_at = now

        # An agent already mid-turn must not be woken again: a slow harness would otherwise
        # accumulate overlapping subprocesses, each with a stale view of the channel.
        if agent.id in self._in_flight:
            return False

        for channel_id in await self.channels_for(agent.id):
            latest = await self.latest_message_id(channel_id)
            seen = state.cursors.get(channel_id)
            if seen is None:
                # First sight of a channel is not news. Joining a room should not make an agent
                # respond to a year of backlog.
                state.cursors[channel_id] = latest
                continue
            if latest <= seen:
                continue

            state.cursors[channel_id] = latest
            self._in_flight.add(agent.id)
            try:
                await self.run_turn(agent, channel_id)
                state.consecutive_failures = 0
            except Exception:  # noqa: BLE001 - a failed turn is not a failed poller
                state.consecutive_failures += 1
                logger.exception(
                    "poll turn failed for %s in %s (failure %d of %d before giving up)",
                    agent.id, channel_id, state.consecutive_failures, MAX_CONSECUTIVE_FAILURES,
                )
            finally:
                self._in_flight.discard(agent.id)
            return True

        return False

    # -- helpers ------------------------------------------------------------------

    def _state(self, agent: Agent) -> AgentState:
        state = self._states.get(agent.id)
        if state is None:
            state = AgentState(
                agent_id=agent.id,
                interval_s=_interval_for(agent, self.default_interval_s),
            )
            self._states[agent.id] = state
        return state

    def mark_seen(self, agent_id: str, channel_id: str, message_id: int) -> None:
        """Move a cursor forward without polling — used when an agent speaks for another reason."""
        state = self._states.get(agent_id)
        if state is not None:
            state.cursors[channel_id] = max(state.cursors.get(channel_id, 0), message_id)


def _interval_for(agent: Agent, default_s: float) -> float:
    import json

    try:
        params = json.loads(agent.params_json) if agent.params_json else {}
    except (json.JSONDecodeError, TypeError):
        params = {}
    try:
        return float(params.get("poll_interval_s", default_s))
    except (TypeError, ValueError):
        return default_s
