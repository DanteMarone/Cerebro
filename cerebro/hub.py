"""In-process asynchronous event bus.

Every state change in Cerebro is published here as an `Event`; the WebSocket layer, the
scheduler and the audit log are all just subscribers. Nothing writes to the browser directly.

The hub is deliberately dependency-free: it imports nothing from the rest of Cerebro, so it can
be reasoned about and tested in isolation.

Back-pressure policy
--------------------
A subscriber that cannot keep up must never stall the publisher -- a wedged browser tab would
otherwise freeze every agent in the process. Each subscription owns a bounded queue; when it
overflows the oldest events are discarded and the subscription is marked lagged. Consumers are
expected to notice `Subscription.lagged` and resynchronise from the database rather than trusting
the stream. This mirrors what the UI already has to do after a reconnect.
"""

from __future__ import annotations

import asyncio
import fnmatch
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

DEFAULT_QUEUE_SIZE = 256


@dataclass(frozen=True, slots=True)
class Event:
    """A single published fact. `seq` is assigned by the hub and is process-monotonic."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    ts: float = 0.0

    def matches(self, patterns: tuple[str, ...]) -> bool:
        return any(fnmatch.fnmatchcase(self.type, p) for p in patterns)


class Subscription:
    """A bounded view of the event stream, filtered to a set of topic patterns.

    Patterns are fnmatch-style against the event type: `"message.*"`, `"agent.status"`, `"*"`.
    """

    __slots__ = ("patterns", "_queue", "_closed", "dropped", "_hub")

    def __init__(self, hub: "Hub", patterns: tuple[str, ...], maxsize: int) -> None:
        self._hub = hub
        self.patterns = patterns
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self.dropped = 0

    @property
    def lagged(self) -> bool:
        """True once any event has been discarded. Consumers must resync when they see this."""
        return self.dropped > 0

    def clear_lag(self) -> None:
        """Called by a consumer after it has resynchronised from the database."""
        self.dropped = 0

    def _offer(self, event: Event) -> None:
        """Non-blocking delivery. Drops the oldest event when full -- never blocks the publisher."""
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover - only under pathological racing
                pass
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover
                self.dropped += 1

    async def get(self) -> Event:
        return await self._queue.get()

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[Event]:
        while not self._closed:
            try:
                yield await self._queue.get()
            except asyncio.CancelledError:
                break

    def close(self) -> None:
        self._closed = True
        self._hub._remove(self)

    async def __aenter__(self) -> "Subscription":
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.close()


class Hub:
    """Publish/subscribe fan-out. One instance per process."""

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE, clock=time.time) -> None:
        self._subs: list[Subscription] = []
        self._seq = itertools.count(1)
        self._queue_size = queue_size
        self._clock = clock
        self._closed = False

    def subscribe(self, *patterns: str, queue_size: int | None = None) -> Subscription:
        """Open a subscription. With no patterns, subscribes to everything.

        Use as an async context manager so the subscription is always removed::

            async with hub.subscribe("message.*") as sub:
                async for event in sub:
                    ...
        """
        if self._closed:
            raise RuntimeError("hub is closed")
        pats = patterns or ("*",)
        sub = Subscription(self, pats, queue_size or self._queue_size)
        self._subs.append(sub)
        return sub

    async def publish(self, type: str, payload: dict[str, Any] | None = None) -> Event:
        """Publish an event. Never blocks on a slow subscriber; see the module docstring."""
        event = Event(
            type=type,
            payload=payload or {},
            seq=next(self._seq),
            ts=self._clock(),
        )
        for sub in tuple(self._subs):
            if event.matches(sub.patterns):
                sub._offer(event)
        return event

    def _remove(self, sub: Subscription) -> None:
        try:
            self._subs.remove(sub)
        except ValueError:
            pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    async def aclose(self) -> None:
        self._closed = True
        for sub in tuple(self._subs):
            sub.close()
        self._subs.clear()
