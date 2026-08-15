"""Connects inbound messages to agent replies.

The WebSocket layer publishes `message.new` and knows nothing about agents. The runtime produces
a reply and knows nothing about channels. This service is the piece in between: it watches the
hub, decides who should answer, and starts the turn.

Slice 1 rule: **only a human message triggers a reply, and only in a DM.** Multi-agent channels
wait for the moderator in Slice 3. Until then an agent's own message can never trigger another
agent, which is the cheapest possible guarantee against a conversation that never ends.
"""

import asyncio
import contextlib
import json
import logging
import re
from pathlib import Path

from cerebro import db, store
from cerebro.config import settings
from cerebro.context import ContextBuilder
from cerebro.hub import Hub
from cerebro.models import Agent
from cerebro.persistence import StoreAdapter
from cerebro.mcp import CompositeToolExecutor, MCPRegistry
from cerebro.poller import ChannelPoller
from cerebro.providers.cli_agent import CliAgentProvider
from cerebro.providers.lmstudio import LMStudioProvider
from cerebro.runtime import AgentRuntime
from cerebro.tools import CoreTools
from cerebro.turnguard import TurnGuard, TurnLimits, new_turn_id

logger = logging.getLogger(__name__)

# Which harness each seeded agent is, absent an explicit backend in its profile.
_DEFAULT_BACKENDS = {
    "claude": "claude",
    "sonnet": "claude",
    "opus": "claude",
    "antigravity": "agy",
    "codex": "codex",
    "goose": "goose",
}


_CORE_TOOLS = CoreTools(agents_root=settings.agents_path)
_MCP_REGISTRY = MCPRegistry(repo_root=Path(__file__).resolve().parent.parent)
_COMPOSITE_TOOLS = CompositeToolExecutor(core_tools=_CORE_TOOLS, mcp_registry=_MCP_REGISTRY)


def _profile_of(agent: Agent) -> dict:
    """The agent's profile.json, which carries its trust tier (§8.8).

    Read from disk rather than the database row because trust is Dante's decision, recorded in a
    file he edits; §8.3 forbids an agent writing its own profile, which is what keeps a sandboxed
    agent from promoting itself.
    """
    path = settings.agents_path / agent.id / "profile.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _tools_for(agent: Agent):
    return _COMPOSITE_TOOLS.specs_for(agent, _profile_of(agent))


async def _run_tool(agent_id: str, name: str, args: dict) -> str:
    row = await store.get_agent(agent_id)
    agent = Agent(**{k: v for k, v in (row or {}).items() if k in Agent.model_fields})
    return await _COMPOSITE_TOOLS.execute(agent, name, args, _profile_of(agent))


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
        tools_for=_tools_for,
        tool_executor=_run_tool,
        concurrency={
            "lmstudio": settings.lmstudio_concurrency,
            "gemini": settings.gemini_concurrency,
        },
        history_window=settings.history_window,
        max_tool_iterations=settings.max_tool_iterations,
        context=ContextBuilder(
            agents_root=settings.agents_path,
            budget_tokens=settings.context_budget,
            operating_manual=_operating_manual(),
        ),
    )


def _operating_manual() -> str:
    """The house rules every agent reads, rendered once at startup.

    Read as plain text rather than a Jinja render: the template's variables are per-agent and the
    packet already states identity, channel and roster separately. A half-interpolated template
    would be worse than the prose.
    """
    path = Path(__file__).resolve().parent / "prompts" / "operating_manual.md.j2"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    # Strip the Jinja bits rather than shipping `{{ agent.name }}` to a model.
    text = re.sub(r"\{%.*?%\}", "", text, flags=re.S)
    text = re.sub(r"\{\{.*?\}\}", "", text, flags=re.S)
    return text.strip()


def _agent_params(agent: Agent) -> dict:
    try:
        return json.loads(agent.params_json) if agent.params_json else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _provider_for(agent: Agent):
    if agent.provider == "lmstudio":
        return LMStudioProvider(
            self_id=agent.id,
            model=agent.model or None,
            base_url=settings.lmstudio_base_url,
        )

    if agent.provider == "cli_agent":
        # §9.3. Cerebro invokes the harness itself, so the agent exists without anyone holding a
        # CLI window open. Note that each turn is a *fresh* process with no memory of previous
        # ones: continuity comes from the context packet and the scratchpad, not from the harness.
        params = _agent_params(agent)
        backend = params.get("backend") or _DEFAULT_BACKENDS.get(agent.id, "claude")
        cmd = params.get("command")
        if not cmd and backend == "claude" and agent.model and agent.model not in ("claude-code", ""):
            cmd = ["claude", "-p", "--model", agent.model]
        cwd = params.get("cwd")
        if not cwd:
            agent_home = (
                Path(agent.home_path)
                if agent.home_path
                else settings.agents_path / agent.id
            ).resolve()
            workspace_dir = agent_home / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            cwd = str(workspace_dir)
        else:
            Path(cwd).mkdir(parents=True, exist_ok=True)

        return CliAgentProvider(
            self_id=agent.id,
            backend=backend,
            cwd=cwd,
            timeout_s=float(params.get("timeout_s", 900)),
            command=cmd,
        )

    if agent.provider in ("openai_compatible", "openrouter", "deepseek", "glm", "openai"):
        from cerebro.providers.openai_compatible import OpenAICompatibleProvider
        params = _agent_params(agent)
        return OpenAICompatibleProvider(
            self_id=agent.id,
            model=agent.model or None,
            base_url=params.get("base_url"),
            api_key=params.get("api_key"),
            name=agent.provider,
        )

    raise NotImplementedError(f"provider {agent.provider!r} arrives in a later slice")


async def _polling_agents() -> list[Agent]:
    """Agents that have opted in to being woken.

    Opt-in rather than opt-out, and false by default. Switching four agents on at once would have
    every one of them answer every message in every channel they belong to, which is a message
    storm and a token bill before anyone has watched a single agent wake, answer and stop. Turn
    them on one at a time.
    """
    rows = await store.list_agents()
    agents = []
    for row in rows:
        if not row.get("enabled"):
            continue
        agent = Agent(**{k: v for k, v in row.items() if k in Agent.model_fields})
        if _agent_params(agent).get("poll_enabled") is True:
            agents.append(agent)
    return agents


async def _channels_for(agent_id: str) -> list[str]:
    """Channels the poller should wake this agent for.

    Excludes rooms where the agent is muted: a mute is a kick that keeps the member on the roster
    (§ channel_members.listen_mode), so it must still stop the poller from waking it, not just stop
    it appearing as a DM responder.
    """
    rows = await db.fetch_all(
        "SELECT channel_id FROM channel_members WHERE member_id = ? AND listen_mode != 'muted';",
        (agent_id,),
    )
    return [r["channel_id"] for r in rows]


async def _latest_message_id(channel_id: str) -> int:
    row = await db.fetch_one(
        "SELECT MAX(id) AS latest FROM messages WHERE channel_id = ?;", (channel_id,)
    )
    return int((row or {}).get("latest") or 0)


class RuntimeService:
    """Watches the hub and runs an agent turn when a human speaks, and wakes agents on a timer."""

    def __init__(self, hub: Hub, runtime: AgentRuntime | None = None) -> None:
        self.hub = hub
        self.runtime = runtime or build_runtime(hub)
        self._sub = None
        self._pump: asyncio.Task | None = None
        self._turns: set[asyncio.Task] = set()
        self.poller = ChannelPoller(
            list_agents=_polling_agents,
            channels_for=_channels_for,
            latest_message_id=_latest_message_id,
            run_turn=self._poll_turn,
        )

    async def _poll_turn(self, agent: Agent, channel_id: str) -> None:
        """A poll-produced turn is an ordinary turn: same caps, same guard, same attribution.

        The runtime deliberately turns provider failures into error *messages* rather than
        exceptions, so a broken backend is visible in the channel instead of silent. That means
        the poller cannot see a failure unless we re-raise it: without this, a misconfigured agent
        looks successful every cycle and backs off never. Codex posted the same config error every
        45 seconds for exactly this reason.
        """
        result = await self.runtime.run_turn(agent, channel_id, depth=1)

        if result is not None and result.id is not None:
            # An agent's own reply is a new message in the channel, so without this the next tick
            # sees "news" and wakes it to respond to itself -- forever, and on a paid backend that
            # is a bill. Jarvis did exactly this: it answered, then immediately woke again.
            self.poller.mark_seen(agent.id, channel_id, result.id)

        if result is not None and result.kind == "error":
            raise RuntimeError(f"{agent.id} turn failed: {result.body[:200]}")

    async def start(self) -> None:
        await self._sweep_orphaned_placeholders()
        self._sub = self.hub.subscribe("message.new")
        self._pump = asyncio.create_task(self._run())
        self._lease_sweeper = asyncio.create_task(self._sweep_leases_loop())
        await self.poller.start()

    async def _sweep_leases_loop(self) -> None:
        """Periodically sweep expired leases and dispatch lease.expired events (§8.7)."""
        while True:
            try:
                await asyncio.sleep(15)
                await store.sweep_expired_leases(hub=self.hub)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("periodic lease sweep error: %r", exc)

    async def _sweep_orphaned_placeholders(self) -> None:
        """Remove empty agent rows left behind by legacy runs before completion-ordered chat."""
        where = "author_kind = 'agent' AND (body IS NULL OR TRIM(body) = '')"
        rows = await db.fetch_all(f"SELECT id FROM messages WHERE {where};")
        if not rows:
            return
        future = await db.enqueue_write(f"DELETE FROM messages WHERE {where};")
        await future
        logger.info("swept %d orphaned empty agent message(s) from a previous run", len(rows))

    async def stop(self) -> None:
        if hasattr(self, "_lease_sweeper") and self._lease_sweeper:
            self._lease_sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._lease_sweeper
        await self.poller.stop()
        for task in tuple(self._turns):
            task.cancel()
        if self._pump:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump
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
                quote_msg_id=message.get("id"),
            )
        )
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)

    async def _responder(self, channel_id: str) -> Agent | None:
        """Slice 1: the single agent member of a DM. Slice 3 replaces this with the moderator.

        A muted member is filtered out before the count check, so a muted DM partner behaves like
        an empty room rather than a still-eligible responder: it stays on the roster and keeps the
        channel's history, it just never answers again until unmuted.
        """
        if not channel_id:
            return None
        channel = await store.get_channel(channel_id)
        if not channel or channel.get("kind") != "dm":
            return None

        members = await store.get_channel_members(channel_id)
        agent_ids = [
            m["member_id"] for m in members
            if m.get("member_kind") == "agent" and m.get("listen_mode") != "muted"
        ]
        if len(agent_ids) != 1:
            return None

        row = await store.get_agent(agent_ids[0])
        if not row or not row.get("enabled"):
            return None
        return Agent(**{k: v for k, v in row.items() if k in Agent.model_fields})
