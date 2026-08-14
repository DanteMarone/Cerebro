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
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from cerebro import usage
from cerebro.config import settings
from cerebro.context import ContextBuilder
from cerebro.hub import Hub
from cerebro.models import (
    Agent,
    Done,
    Message,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    Usage,
)
from cerebro.providers.base import Params, Provider, ToolSpec
from cerebro.providers.lmstudio import ProviderError, ProviderUnavailable
from cerebro.turnguard import TurnGuard, new_turn_id

logger = logging.getLogger(__name__)

PASS_TOKEN = "PASS"
DEFAULT_HISTORY_WINDOW = 30
DEFAULT_MAX_TOOL_ITERATIONS = 12


def is_pass(body: str) -> bool:
    """Did the agent decline to speak?

    Deliberately strict: exactly PASS, ignoring case and surrounding whitespace and a trailing
    full stop. A model that writes "PASS - nothing to add here" has said something, and treating
    that as silence would swallow real content. Better to occasionally show a short message than
    to occasionally hide one.
    """
    return body.strip().rstrip(".").upper() == PASS_TOKEN


@dataclass(frozen=True)
class Completion:
    """One turn's result, carried back from the stream rather than stashed on the runtime.

    `finish_reason` used to live on the AgentRuntime instance. RuntimeService holds a single
    runtime and starts every turn with asyncio.create_task, so that attribute was shared by all
    turns in flight: one turn's finish reason could overwrite another's between the stream ending
    and the check that reads it. While it only chose the wording of an error that was mostly
    invisible; once it decided whether a message is written at all, a concurrent `stop` could
    silently delete another turn's "ran out of tokens" error and the agent would simply never
    answer.
    """

    text: str
    finish_reason: str | None
    pending_calls: bool = False


class Persistence(Protocol):
    """The slice of storage the runtime needs.

    Declared here rather than imported so the runtime and the store can be built in parallel; any
    object with these four methods satisfies it.
    """

    async def append_message(self, message: Message) -> Message: ...

    async def update_message_body(self, message_id: int, body: str) -> None: ...

    async def delete_message(self, message_id: int) -> None: ...

    async def history(self, channel_id: str, limit: int) -> list[Message]: ...

    async def system_prompt(self, agent: Agent) -> str: ...

    async def channel(self, channel_id: str) -> dict: ...

    async def members(self, channel_id: str) -> list[str]: ...


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
        context: "ContextBuilder | None" = None,
    ) -> None:
        self.hub = hub
        self.store = store
        self.provider_for = provider_for
        self.guard = guard or TurnGuard()
        self.tool_executor = tool_executor
        self.tools_for = tools_for or (lambda agent: [])
        self.history_window = history_window
        self.max_tool_iterations = max_tool_iterations
        self.context = context
        self._limits = {
            name: asyncio.Semaphore(n)
            for name, n in (concurrency or {"lmstudio": 2, "gemini": 4}).items()
        }

    def _semaphore(self, provider: Provider) -> asyncio.Semaphore:
        return self._limits.setdefault(provider.name, asyncio.Semaphore(2))

    async def _status(
        self, agent: Agent, channel_id: str, status: str, turn_id: str | None = None
    ) -> None:
        payload = {"agent_id": agent.id, "channel_id": channel_id, "status": status}
        if turn_id is not None:
            payload["turn_id"] = turn_id
        await self.hub.publish("agent.status", payload)
        await self.hub.publish("agent.activity", payload)

    async def run_turn(
        self,
        agent: Agent,
        channel_id: str,
        turn_id: str | None = None,
        depth: int = 0,
        quote_msg_id: int | None = None,
    ) -> Message | None:
        """Produce one reply from `agent` in `channel_id`.

        Returns the persisted message, or None when refused, passed, or failed.
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

        transcript = await self._context(agent, channel_id)

        # Signal in-flight turn activity across WebSockets without writing a message row to DB
        await self._status(agent, channel_id, "thinking", turn_id=turn_id)

        try:
            async with self._semaphore(provider):
                try:
                    completion = await self._generate(
                        agent, channel_id, turn_id, provider, transcript
                    )
                except ProviderUnavailable as exc:
                    return await self._fail(
                        agent, channel_id, turn_id, depth, quote_msg_id, f"backend offline — {exc}"
                    )
                except ProviderError as exc:
                    return await self._fail(
                        agent, channel_id, turn_id, depth, quote_msg_id, f"provider error — {exc}"
                    )
                except Exception as exc:  # noqa: BLE001 - an agent must never crash the service
                    err = f"unexpected error — {exc!r}"
                    return await self._fail(agent, channel_id, turn_id, depth, quote_msg_id, err)
        except asyncio.CancelledError:
            # Emit terminal cancellation so UI indicator never remains orphaned
            await self._status(agent, channel_id, "cancelled", turn_id=turn_id)
            await self.hub.publish(
                "turn.cancelled",
                {"channel_id": channel_id, "turn_id": turn_id, "agent_id": agent.id},
            )
            raise

        body = completion.text
        is_dm = channel_id.startswith("dm-")
        if not is_dm and hasattr(self.store, "get_channel"):
            try:
                ch = await self.store.get_channel(channel_id)
                if ch and ch.get("kind") == "dm":
                    is_dm = True
            except Exception:
                pass

        if not body.strip():
            if not is_dm and completion.finish_reason == "stop" and not completion.pending_calls:
                logger.info("Agent %s completed turn %s silently (finish: stop)", agent.id, turn_id)
                await self._status(agent, channel_id, "idle", turn_id=turn_id)
                await self.hub.publish(
                    "turn.discarded",
                    {
                        "channel_id": channel_id,
                        "turn_id": turn_id,
                        "agent_id": agent.id,
                        "reason": "silent_stop",
                    },
                )
                return None

            reason = "produced no answer"
            if is_dm and completion.finish_reason == "stop":
                reason = "produced no answer in a direct message (silence is not allowed in DMs)"
            elif completion.finish_reason == "length":
                reason = (
                    "ran out of tokens before answering — it spent its budget reasoning. "
                    "Raise max_tokens for this agent."
                )
            elif completion.finish_reason:
                reason = f"produced no answer (finished: {completion.finish_reason})"
            return await self._fail(agent, channel_id, turn_id, depth, quote_msg_id, reason)

        if is_pass(body):
            if is_dm:
                return await self._fail(
                    agent, channel_id, turn_id, depth, quote_msg_id,
                    "said PASS in a direct message (silence is not allowed in DMs)",
                )
            await self._status(agent, channel_id, "idle", turn_id=turn_id)
            await self.hub.publish(
                "turn.discarded",
                {
                    "channel_id": channel_id,
                    "turn_id": turn_id,
                    "agent_id": agent.id,
                    "reason": "pass",
                },
            )
            return None

        # Completion-ordered persistence: the message is appended once with final timestamp
        reply = await self.store.append_message(
            Message(
                channel_id=channel_id,
                author_id=agent.id,
                author_kind="agent",
                kind="chat",
                body=body,
                quote_msg_id=quote_msg_id,
                turn_id=turn_id,
                depth=depth,
            )
        )
        self.guard.record_agent_message(turn_id, depth)
        await self._status(agent, channel_id, "idle", turn_id=turn_id)
        await self.hub.publish(
            "message.new",
            {"channel_id": channel_id, "message": reply.model_dump()},
        )
        await self.hub.publish(
            "message.done",
            {"channel_id": channel_id, "message": reply.model_dump()},
        )
        return reply

    async def _generate(
        self,
        agent: Agent,
        channel_id: str,
        turn_id: str,
        provider: Provider,
        transcript: list[Message],
    ) -> Completion:
        """Stream a completion, servicing tool calls until the model stops asking for them."""
        params = _params_for(agent)
        tools = self.tools_for(agent)
        text_parts: list[str] = []
        thinking: list[str] = []
        finish_reason: str | None = None
        unserviced_calls = False

        for _ in range(self.max_tool_iterations):
            await self._status(agent, channel_id, "thinking", turn_id=turn_id)
            calls: dict[str, dict[str, str]] = {}
            produced = ""

            async for delta in provider.stream(transcript, tools, params):
                if isinstance(delta, TextDelta):
                    produced += delta.text
                    await self.hub.publish(
                        "turn.delta",
                        {
                            "channel_id": channel_id,
                            "agent_id": agent.id,
                            "turn_id": turn_id,
                            "text": delta.text,
                        },
                    )
                elif isinstance(delta, ReasoningDelta):
                    # Thinking is private (Dante, 2026-08-14): "Only message the group what we
                    # actually should see as a chat message for collaboration."
                    #
                    # So reasoning never reaches the channel. It goes to the agent's own log, where
                    # it is available for debugging without turning a shared room into a feed of
                    # everyone's inner monologue. The room still sees *that* the agent is thinking,
                    # via agent.status, because presence is collaboration and thought is not.
                    thinking.append(delta.text)
                elif isinstance(delta, ToolCallDelta):
                    call = calls.setdefault(delta.id, {"name": delta.name, "args": ""})
                    if delta.name:
                        call["name"] = delta.name
                    call["args"] += delta.args_fragment
                elif isinstance(delta, Done):
                    finish_reason = delta.reason
                elif isinstance(delta, Usage):
                    await self.hub.publish(
                        "usage",
                        {"agent_id": agent.id, "channel_id": channel_id,
                         "input": delta.input, "output": delta.output},
                    )
                    # Until now this number was published and dropped. The hub event is for live
                    # display; this is the durable half, and it cannot raise. See
                    # usage.record_turn_usage for why it swallows its own failures.
                    await usage.record_turn_usage(agent.id, delta.input, delta.output)

            if produced:
                text_parts.append(produced)

            if not calls or self.tool_executor is None:
                # Calls we cannot service are not a finished turn. Codex's contract: silence
                # requires a clean stop AND no outstanding tool activity.
                unserviced_calls = bool(calls) and self.tool_executor is None
                break

            # The protocol shape: one assistant turn carrying the calls, then one tool turn per
            # call carrying its id. Codex refuted the previous version, which emitted an empty
            # assistant message and a system message -- a sequence no model is obliged to
            # understand and which the API forbids.
            transcript = transcript + [
                Message(
                    channel_id=channel_id, author_id=agent.id, author_kind="agent",
                    kind="chat", body=produced or "",
                    meta_json=json.dumps({"tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["args"] or "{}"},
                        }
                        for call_id, call in calls.items()
                    ]}),
                ),
            ]
            for call_id, call in calls.items():
                result = await self._run_tool(agent, channel_id, call_id, call, turn_id=turn_id)
                transcript.append(
                    Message(
                        channel_id=channel_id, author_id="tool", author_kind="system",
                        kind="tool", body=result,
                        meta_json=json.dumps({"tool_call_id": call_id, "name": call["name"]}),
                    )
                )
        else:
            text_parts.append(
                f"\n\n_Stopped after {self.max_tool_iterations} tool rounds without finishing._"
            )

        if thinking:
            self._log_thinking(agent, "".join(thinking))
        return Completion(
            text="".join(text_parts).strip(),
            finish_reason=finish_reason,
            pending_calls=unserviced_calls,
        )

    def _log_thinking(self, agent: Agent, text: str) -> None:
        """Write reasoning to the agent's own log rather than the shared channel.

        The fallback home is anchored to `settings.agents_path`, not to a relative `agents/`. A
        CWD-relative fallback meant the test suite, run from the repo root with an agent that has no
        home_path, appended fixtures to the *live* agent's log: 47 copies of the string "thinking
        hard" from tests/test_runtime.py ended up in Jarvis's reasoning log, and were sitting there
        the first time somebody read that log to explain why Jarvis was failing. `cerebro/tools.py`
        already anchors agent homes to an explicit root; this brings the runtime in line with it.
        """
        try:
            home = (
                Path(agent.home_path)
                if agent.home_path
                else Path(settings.agents_path) / agent.id
            )
            logs = home / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc)
            with (logs / f"reasoning-{stamp:%Y-%m-%d}.log").open("a", encoding="utf-8") as fh:
                fh.write(f"\n--- {stamp:%H:%M:%S} ---\n{text.strip()}\n")
        except OSError:
            # Losing a debug log must never cost a reply.
            pass

    async def _run_tool(
        self,
        agent: Agent,
        channel_id: str,
        call_id: str,
        call: dict[str, str],
        turn_id: str | None = None,
    ) -> str:
        await self._status(agent, channel_id, f"tool:{call['name']}", turn_id=turn_id)
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

        if self.context is not None:
            try:
                channel = await self.store.channel(channel_id)
                members = await self.store.members(channel_id)
                return self.context.build(agent, prompt, channel, members, history)
            except Exception:  # noqa: BLE001 - a thin packet beats no turn at all
                logger.exception("context build failed for %s; falling back", agent.id)

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
        self,
        agent: Agent,
        channel_id: str,
        turn_id: str,
        depth: int,
        quote_msg_id: int | None,
        reason: str,
    ) -> Message:
        """Surface a failure in the channel as a completed error message."""
        reply = await self.store.append_message(
            Message(
                channel_id=channel_id,
                author_id=agent.id,
                author_kind="agent",
                kind="error",
                body=f"⚠ {reason}",
                quote_msg_id=quote_msg_id,
                turn_id=turn_id,
                depth=depth,
            )
        )
        await self._status(agent, channel_id, "idle", turn_id=turn_id)
        await self.hub.publish(
            "error",
            {
                "channel_id": channel_id,
                "agent_id": agent.id,
                "turn_id": turn_id,
                "message_id": reply.id,
                "reason": reason,
            },
        )
        await self.hub.publish(
            "message.new",
            {"channel_id": channel_id, "message": reply.model_dump()},
        )
        await self.hub.publish(
            "message.done",
            {"channel_id": channel_id, "message": reply.model_dump()},
        )
        return reply


def _params_for(agent: Agent) -> Params:
    if not agent.params_json:
        return Params()
    try:
        return Params(**json.loads(agent.params_json))
    except (json.JSONDecodeError, TypeError, ValueError):
        return Params()
