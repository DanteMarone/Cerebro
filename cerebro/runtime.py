"""The agent turn loop.

One `run_turn` is one agent producing one reply: assemble what it should see, stream a completion,
run any tools it asks for, and persist the result. Everything else in Cerebro decides *whether* an
agent speaks; this decides what happens once it does.

Ordering matters and is deliberate:

1. `TurnGuard.check` runs **before** the provider call. Freezing a runaway conversation after
   paying for the inference would defeat the point.
2. The reply row is persisted empty and announced *before* the first token, so streamed deltas have
   a durable id to attach to and a client that reconnects mid-stream finds the message already
   there.
3. The body is written once, on completion. Deltas are a live view, the row is the truth.

Slice 1 passes no tools. The loop is written with them because retrofitting a tool loop into a
streaming path is exactly the kind of surgery that introduces races, and because Slice 2 plugs an
MCP executor into `tool_executor` without touching this file.
"""

import asyncio
import json
from typing import Any, Awaitable, Callable, Protocol

from cerebro.hub import Hub
from cerebro.models import Agent, Message, TextDelta, ToolCallDelta, Usage
from cerebro.providers.base import Params, Provider, ToolSpec
from cerebro.providers.lmstudio import ProviderError, ProviderUnavailable
from cerebro.turnguard import TurnGuard, new_turn_id

DEFAULT_HISTORY_WINDOW = 30
DEFAULT_MAX_TOOL_ITERATIONS = 12


class Persistence(Protocol):
    """The slice of storage the runtime needs.

    Declared here rather than imported so the runtime and the store can be built in parallel; any
    object with these four methods satisfies it.
    """

    async def append_message(self, message: Message) -> Message: ...

    async def update_message_body(self, message_id: int, body: str) -> None: ...

    async def history(self, channel_id: str, limit: int) -> list[Message]: ...

    async def system_prompt(self, agent: Agent) -> str: ...


ToolExecutor = Callable[[str, str, dict[str, Any]], Awaitable[str]]


class AgentRuntime:
    """Runs agent turns, one at a time per provider, streaming into the hub."""

    def __init__(
        self,
        hub: Hub,
        store: Persistence,
        provider_for: Callable[[Agent], Provider],
        guard: TurnGuard | None = None,
        tool_executor: ToolExecutor | None = None,
        tools_for: Callable[[Agent], list[ToolSpec]] | None = None,
        concurrency: dict[str, int] | None = None,
        history_window: int = DEFAULT_HISTORY_WINDOW,
        max_tool_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
    ) -> None:
        self.hub = hub
        self.store = store
        self.provider_for = provider_for
        self.guard = guard or TurnGuard()
        self.tool_executor = tool_executor
        self.tools_for = tools_for or (lambda agent: [])
        self.history_window = history_window
        self.max_tool_iterations = max_tool_iterations
        self._limits = {
            name: asyncio.Semaphore(n)
            for name, n in (concurrency or {"lmstudio": 2, "gemini": 4}).items()
        }

    def _semaphore(self, provider: Provider) -> asyncio.Semaphore:
        return self._limits.setdefault(provider.name, asyncio.Semaphore(2))

    async def _status(self, agent: Agent, channel_id: str, status: str) -> None:
        await self.hub.publish(
            "agent.status",
            {"agent_id": agent.id, "channel_id": channel_id, "status": status},
        )

    async def run_turn(
        self,
        agent: Agent,
        channel_id: str,
        turn_id: str | None = None,
        depth: int = 0,
    ) -> Message | None:
        """Produce one reply from `agent` in `channel_id`.

        Returns the persisted message, or None when the turn was refused or the backend failed.
        """
        turn_id = turn_id or new_turn_id()

        verdict = self.guard.check(turn_id, depth)
        if not verdict.allowed:
            await self._post_system(channel_id, turn_id, self.guard.freeze_message(turn_id))
            await self.hub.publish(
                "turn.frozen",
                {"channel_id": channel_id, "turn_id": turn_id, "reason": verdict.reason},
            )
            return None

        provider = self.provider_for(agent)
        reply = await self.store.append_message(
            Message(
                channel_id=channel_id,
                author_id=agent.id,
                author_kind="agent",
                kind="chat",
                body="",
                turn_id=turn_id,
                depth=depth,
            )
        )
        await self.hub.publish("message.new", {"channel_id": channel_id,
                                               "message": reply.model_dump()})

        async with self._semaphore(provider):
            try:
                body = await self._generate(agent, channel_id, reply, provider)
            except ProviderUnavailable as exc:
                return await self._fail(agent, channel_id, reply, f"backend offline — {exc}")
            except ProviderError as exc:
                return await self._fail(agent, channel_id, reply, f"provider error — {exc}")
            except Exception as exc:  # noqa: BLE001 - an agent must never take the process down
                return await self._fail(agent, channel_id, reply, f"unexpected error — {exc!r}")

        reply.body = body
        await self.store.update_message_body(reply.id, body)
        self.guard.record_agent_message(turn_id, depth)
        await self._status(agent, channel_id, "idle")
        await self.hub.publish("message.done", {"channel_id": channel_id,
                                                "message": reply.model_dump()})
        return reply

    async def _generate(
        self,
        agent: Agent,
        channel_id: str,
        reply: Message,
        provider: Provider,
    ) -> str:
        """Stream a completion, servicing tool calls until the model stops asking for them."""
        params = _params_for(agent)
        tools = self.tools_for(agent)
        transcript = await self._context(agent, channel_id)
        text_parts: list[str] = []

        for _ in range(self.max_tool_iterations):
            await self._status(agent, channel_id, "thinking")
            calls: dict[str, dict[str, str]] = {}
            produced = ""

            async for delta in provider.stream(transcript, tools, params):
                if isinstance(delta, TextDelta):
                    produced += delta.text
                    await self.hub.publish(
                        "message.delta",
                        {"channel_id": channel_id, "message_id": reply.id, "text": delta.text},
                    )
                elif isinstance(delta, ToolCallDelta):
                    call = calls.setdefault(delta.id, {"name": delta.name, "args": ""})
                    if delta.name:
                        call["name"] = delta.name
                    call["args"] += delta.args_fragment
                elif isinstance(delta, Usage):
                    await self.hub.publish(
                        "usage",
                        {"agent_id": agent.id, "channel_id": channel_id,
                         "input": delta.input, "output": delta.output},
                    )

            if produced:
                text_parts.append(produced)

            if not calls or self.tool_executor is None:
                break

            transcript = transcript + [
                Message(channel_id=channel_id, author_id=agent.id, author_kind="agent",
                        kind="chat", body=produced or ""),
            ]
            for call_id, call in calls.items():
                result = await self._run_tool(agent, channel_id, call_id, call)
                transcript.append(
                    Message(channel_id=channel_id, author_id="tool", author_kind="system",
                            kind="tool", body=f"{call['name']} returned: {result}")
                )
        else:
            text_parts.append(
                f"\n\n_Stopped after {self.max_tool_iterations} tool rounds without finishing._"
            )

        return "".join(text_parts).strip()

    async def _run_tool(
        self, agent: Agent, channel_id: str, call_id: str, call: dict[str, str]
    ) -> str:
        await self._status(agent, channel_id, f"tool:{call['name']}")
        await self.hub.publish(
            "tool.call",
            {"channel_id": channel_id, "agent_id": agent.id, "id": call_id,
             "tool": call["name"], "args": call["args"]},
        )
        # Every path below publishes tool.result. An unresolved tool.call leaves a card spinning
        # in the UI forever, so a failure must be announced exactly like a success.
        try:
            args = json.loads(call["args"] or "{}")
        except json.JSONDecodeError:
            # A weak local model producing malformed JSON is expected; tell it so it can retry.
            result = f"error: arguments were not valid JSON: {call['args'][:200]}"
        else:
            try:
                result = await self.tool_executor(agent.id, call["name"], args)
            except Exception as exc:  # noqa: BLE001 - tool failures are data, not crashes
                result = f"error: {exc!r}"

        await self.hub.publish(
            "tool.result",
            {"channel_id": channel_id, "agent_id": agent.id, "id": call_id,
             "tool": call["name"], "result": result[:4000]},
        )
        return result

    async def _context(self, agent: Agent, channel_id: str) -> list[Message]:
        """Slice 1 context: the agent's system prompt and the recent channel history.

        Section 7 replaces this with the full context packet in Slice 4 — scratchpad, retrieved
        memory, shared drive index and budgeting. Keep the shape, grow the contents.
        """
        prompt = await self.store.system_prompt(agent)
        history = await self.store.history(channel_id, self.history_window)
        system = Message(
            channel_id=channel_id, author_id="system", author_kind="system",
            kind="system", body=prompt,
        )
        return [system] + history

    async def _post_system(self, channel_id: str, turn_id: str, body: str) -> Message:
        message = await self.store.append_message(
            Message(channel_id=channel_id, author_id="system", author_kind="system",
                    kind="system", body=body, turn_id=turn_id)
        )
        await self.hub.publish("message.new", {"channel_id": channel_id,
                                               "message": message.model_dump()})
        return message

    async def _fail(
        self, agent: Agent, channel_id: str, reply: Message, reason: str
    ) -> Message:
        """Surface a failure in the channel. The turn ends; the agent stays enabled."""
        reply.body = f"⚠ {reason}"
        reply.kind = "error"
        await self.store.update_message_body(reply.id, reply.body)
        await self._status(agent, channel_id, "idle")
        await self.hub.publish("error", {"channel_id": channel_id, "agent_id": agent.id,
                                         "message_id": reply.id, "reason": reason})
        await self.hub.publish("message.done", {"channel_id": channel_id,
                                                "message": reply.model_dump()})
        return reply


def _params_for(agent: Agent) -> Params:
    if not agent.params_json:
        return Params()
    try:
        return Params(**json.loads(agent.params_json))
    except (json.JSONDecodeError, TypeError, ValueError):
        return Params()
