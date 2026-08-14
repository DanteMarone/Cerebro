"""Connects inbound messages to agent replies.

The WebSocket layer publishes `message.new` and knows nothing about agents. The runtime produces
a reply and knows nothing about channels. This service is the piece in between: it watches the
hub, decides who should answer, and starts the turn.

Slice 1 rule: **only a human message triggers a reply, and only in a DM.** Multi-agent channels
wait for the moderator in Slice 3. Until then an agent's own message can never trigger another
agent, which is the cheapest possible guarantee against a conversation that never ends.
"""

import asyncio
import logging

from cerebro import store
from cerebro.config import settings
from cerebro.hub import Hub
from cerebro.models import Agent
from cerebro.persistence import StoreAdapter
from cerebro.providers.lmstudio import LMStudioProvider
from cerebro.runtime import AgentRuntime
from cerebro.turnguard import TurnGuard, TurnLimits, new_turn_id

logger = logging.getLogger(__name__)


def build_runtime(hub: Hub) -> AgentRuntime:
    limits = TurnLimits(
        max_depth=settings.max_depth,
        max_agent_messages=settings.max_agent_messages_per_turn,
        max_wallclock_s=settings.max_turn_wallclock_s,
    )
    return AgentRuntime(
        hub=hub,
        store=StoreAdapter(),
        provider_for=_provider_for,
        guard=TurnGuard(limits),
        concurrency={
            "lmstudio": settings.lmstudio_concurrency,
            "gemini": settings.gemini_concurrency,
        },
        history_window=settings.history_window,
        max_tool_iterations=settings.max_tool_iterations,
    )


def _provider_for(agent: Agent):
    if agent.provider == "lmstudio":
        return LMStudioProvider(
            self_id=agent.id,
            model=agent.model or None,
            base_url=settings.lmstudio_base_url,
        )
    raise NotImplementedError(f"provider {agent.provider!r} arrives in a later slice")


class RuntimeService:
    """Watches the hub and runs an agent turn when a human speaks."""

    def __init__(self, hub: Hub, runtime: AgentRuntime | None = None) -> None:
        self.hub = hub
        self.runtime = runtime or build_runtime(hub)
        self._sub = None
        self._pump: asyncio.Task | None = None
        self._turns: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub = self.hub.subscribe("message.new")
        self._pump = asyncio.create_task(self._run())

    async def stop(self) -> None:
        for task in tuple(self._turns):
            task.cancel()
        if self._pump:
            self._pump.cancel()
        if self._sub:
            self._sub.close()

    async def _run(self) -> None:
        while True:
            try:
                event = await self._sub.get()
                await self._consider(event.payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - the pump must outlive any single message
                logger.exception("runtime service failed on an event: %r", exc)

    async def _consider(self, payload: dict) -> None:
        message = payload.get("message") or {}
        if message.get("author_kind") != "user" or not (message.get("body")
                                                        or message.get("content")):
            return

        channel_id = payload.get("channel_id") or message.get("channel_id")
        agent = await self._responder(channel_id)
        if agent is None:
            return

        # Run off the pump: a slow model must not stop the next message being considered.
        task = asyncio.create_task(
            self.runtime.run_turn(
                agent,
                channel_id,
                turn_id=message.get("turn_id") or new_turn_id(),
                depth=int(message.get("depth") or 0) + 1,
            )
        )
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)

    async def _responder(self, channel_id: str) -> Agent | None:
        """Slice 1: the single agent member of a DM. Slice 3 replaces this with the moderator."""
        if not channel_id:
            return None
        channel = await store.get_channel(channel_id)
        if not channel or channel.get("kind") != "dm":
            return None

        members = await store.get_channel_members(channel_id)
        agent_ids = [m["member_id"] for m in members if m.get("member_kind") == "agent"]
        if len(agent_ids) != 1:
            return None

        row = await store.get_agent(agent_ids[0])
        if not row or not row.get("enabled"):
            return None
        return Agent(**{k: v for k, v in row.items() if k in Agent.model_fields})
