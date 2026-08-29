"""Comprehensive characterization test suite for Cerebro AgentRuntime before Harness v1 refactor.

Locks down observable invariants across 10 key categories:
1. Completion-ordered final channel replies
2. PASS and silent completion semantics (topic vs DM)
3. Assistant > tool call > tool result > follow-up sequencing
4. Provider concurrency/semaphore behavior
5. TurnGuard and maximum tool-loop behavior
6. MCP/tool allowlist refusal and confinement
7. Cancellation and terminal UI/runtime state
8. Usage accounting and persistence
9. Provider/tool failure behavior without orphaning turns
10. Existing CLI-provider behavior tested with deterministic fakes
"""

import asyncio
import json
import sys
from typing import Any

import pytest

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
from cerebro.mcp import MCPClientError, MCPServerConfig, StdioMCPClient, CompositeToolExecutor, MCPRegistry
from cerebro.providers.base import Params
from cerebro.providers.cli_agent import CliAgentProvider, parse_cli_output, render_prompt
from cerebro.providers.fake import FakeProvider
from cerebro.providers.lmstudio import ProviderError, ProviderUnavailable
from cerebro.runtime import AgentRuntime
from cerebro.tools import CoreTools, ToolError
from cerebro.turnguard import TurnGuard, TurnLimits


class InMemoryStore:
    """Deterministic in-memory implementation of the Persistence protocol."""

    def __init__(self, prompt: str = "you are jarvis") -> None:
        self.messages: list[Message] = []
        self.prompt = prompt
        self._next_id = 1
        self.channels: dict[str, dict[str, Any]] = {}

    async def append_message(self, message: Message) -> Message:
        message.id = self._next_id
        self._next_id += 1
        self.messages.append(message)
        return message

    async def update_message_body(self, message_id: int, body: str) -> None:
        for m in self.messages:
            if m.id == message_id:
                m.body = body

    async def delete_message(self, message_id: int) -> None:
        self.messages = [m for m in self.messages if m.id != message_id]

    async def history(self, channel_id: str, limit: int) -> list[Message]:
        return [m for m in self.messages if m.channel_id == channel_id][-limit:]

    async def system_prompt(self, agent: Agent) -> str:
        return self.prompt

    async def channel(self, channel_id: str) -> dict:
        return self.channels.get(channel_id, {"id": channel_id, "name": channel_id, "kind": "topic"})

    async def get_channel(self, channel_id: str) -> dict:
        return await self.channel(channel_id)

    async def members(self, channel_id: str) -> list[str]:
        return ["dante", "jarvis"]


async def drain_events(sub) -> list[Any]:
    events = []
    while not sub._queue.empty():
        events.append(await sub.get())
    return events


def make_agent(
    agent_id: str = "jarvis",
    name: str = "jarvis",
    provider: str = "lmstudio",
    home_path: str | None = None,
    params: dict[str, Any] | None = None,
) -> Agent:
    return Agent(
        id=agent_id,
        name=name,
        provider=provider,
        home_path=home_path,
        params_json=json.dumps(params) if params else None,
    )


def make_runtime(
    provider,
    store=None,
    guard=None,
    executor=None,
    tools=None,
    concurrency=None,
    max_tool_iterations=12,
) -> tuple[Hub, AgentRuntime]:
    hub = Hub()
    runtime = AgentRuntime(
        hub=hub,
        store=store or InMemoryStore(),
        provider_for=(lambda a: provider if not callable(provider) else provider(a)),
        guard=guard or TurnGuard(),
        tool_executor=executor,
        tools_for=(lambda a: tools or []),
        concurrency=concurrency,
        max_tool_iterations=max_tool_iterations,
    )
    return hub, runtime


def fake_script_harness(script: str) -> list[str]:
    return [sys.executable, "-c", script]


# =============================================================================
# 1. Completion-ordered final channel replies
# =============================================================================


@pytest.mark.asyncio
async def test_completion_ordered_replies_commit_at_completion_time_not_start_time():
    """Turns started out of order commit strictly by completion time in the transcript."""
    store = InMemoryStore()
    hub = Hub()

    agent_slow = make_agent("slow_agent", "slow")
    agent_fast = make_agent("fast_agent", "fast")

    prov_slow = FakeProvider([TextDelta(text="slow message"), Done(reason="stop")], delay_s=0.06)
    prov_fast = FakeProvider([TextDelta(text="fast message"), Done(reason="stop")], delay_s=0.0)

    def router(agent: Agent):
        return prov_slow if agent.id == "slow_agent" else prov_fast

    runtime = AgentRuntime(hub=hub, store=store, provider_for=router)

    task_slow = asyncio.create_task(runtime.run_turn(agent_slow, "general", turn_id="turn_slow"))
    await asyncio.sleep(0.01)
    task_fast = asyncio.create_task(runtime.run_turn(agent_fast, "general", turn_id="turn_fast"))

    await asyncio.gather(task_slow, task_fast)

    assert len(store.messages) == 2
    assert store.messages[0].author_id == "fast_agent"
    assert store.messages[0].body == "fast message"
    assert store.messages[0].turn_id == "turn_fast"
    assert store.messages[0].id == 1

    assert store.messages[1].author_id == "slow_agent"
    assert store.messages[1].body == "slow message"
    assert store.messages[1].turn_id == "turn_slow"
    assert store.messages[1].id == 2


@pytest.mark.asyncio
async def test_streaming_deltas_do_not_create_intermediate_database_rows():
    """While deltas stream, zero database message rows exist until completion."""
    store = InMemoryStore()
    row_counts: list[int] = []

    class InspectingProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            row_counts.append(len(store.messages))
            yield TextDelta(text="chunk 1 ")
            row_counts.append(len(store.messages))
            yield TextDelta(text="chunk 2")
            row_counts.append(len(store.messages))
            yield Done(reason="stop")

    hub, runtime = make_runtime(InspectingProvider(), store=store)
    agent = make_agent()
    reply = await runtime.run_turn(agent, "general")

    assert row_counts == [0, 0, 0]
    assert len(store.messages) == 1
    assert store.messages[0].id == reply.id
    assert store.messages[0].body == "chunk 1 chunk 2"


@pytest.mark.asyncio
async def test_completion_publishes_message_new_and_message_done_events():
    """Upon completion, message.new and message.done are emitted with the persisted message payload."""
    provider = FakeProvider([TextDelta(text="final answer"), Done(reason="stop")])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent()

    async with hub.subscribe("message.*") as sub:
        reply = await runtime.run_turn(agent, "general")
        events = await drain_events(sub)

    event_types = [e.type for e in events]
    assert event_types == ["message.new", "message.done"]

    for ev in events:
        assert ev.payload["channel_id"] == "general"
        assert ev.payload["message"]["id"] == reply.id
        assert ev.payload["message"]["body"] == "final answer"


@pytest.mark.asyncio
async def test_reply_preserves_turn_metadata_and_attribution():
    """Persisted replies preserve depth, quote_msg_id, turn_id, and agent authorship."""
    provider = FakeProvider([TextDelta(text="quoted response"), Done(reason="stop")])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent("specialist_agent", "Specialist")

    reply = await runtime.run_turn(
        agent,
        "c_topic",
        turn_id="turn_custom_99",
        depth=4,
        quote_msg_id=123,
    )

    assert reply is not None
    assert reply.author_id == "specialist_agent"
    assert reply.author_kind == "agent"
    assert reply.kind == "chat"
    assert reply.depth == 4
    assert reply.quote_msg_id == 123
    assert reply.turn_id == "turn_custom_99"


# =============================================================================
# 2. PASS and silent completion semantics
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("pass_text", ["PASS", "  pass  ", "Pass.", "PASS\n", "\tpass.\t"])
async def test_pass_in_topic_channel_discards_turn_without_persisting_row(pass_text):
    """In topic channels, PASS variations discard the turn cleanly without database rows."""
    provider = FakeProvider([TextDelta(text=pass_text), Done(reason="stop")])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent()

    async with hub.subscribe("*") as sub:
        result = await runtime.run_turn(agent, "general", turn_id="pass_turn_1")
        events = await drain_events(sub)

    assert result is None
    assert store.messages == []

    discarded = [e for e in events if e.type == "turn.discarded"]
    assert len(discarded) == 1
    assert discarded[0].payload["reason"] == "pass"
    assert discarded[0].payload["agent_id"] == "jarvis"

    status_events = [e for e in events if e.type == "agent.status"]
    assert status_events[-1].payload["status"] == "idle"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "substantive_text",
    [
        "PASS - I have nothing to add",
        "I'll pass on this question",
        "Pass along the message to Dante",
        "PASSING is not allowed here",
    ],
)
async def test_pass_strict_matching_preserves_non_exact_sentences(substantive_text):
    """Strict PASS matching treats non-exact text as real communication."""
    provider = FakeProvider([TextDelta(text=substantive_text), Done(reason="stop")])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "general")
    assert reply is not None
    assert reply.body == substantive_text
    assert len(store.messages) == 1


@pytest.mark.asyncio
async def test_silent_stop_in_topic_channel_discards_turn_without_row():
    """Zero text output with finish_reason='stop' discards turn cleanly in non-DM channels."""
    provider = FakeProvider([ReasoningDelta(text="Deliberating silently"), Done(reason="stop")])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent()

    async with hub.subscribe("turn.discarded") as sub:
        reply = await runtime.run_turn(agent, "channel_team")
        discarded = await drain_events(sub)

    assert reply is None
    assert store.messages == []
    assert len(discarded) == 1
    assert discarded[0].payload["reason"] == "silent_stop"


@pytest.mark.asyncio
async def test_pass_in_dm_channel_fails_closed_with_error_message():
    """In direct messages (dm-*), saying PASS is forbidden and persists an error message."""
    provider = FakeProvider([TextDelta(text="PASS"), Done(reason="stop")])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "dm-dante-jarvis")

    assert reply is not None
    assert reply.kind == "error"
    assert "said PASS in a direct message" in reply.body
    assert len(store.messages) == 1
    assert store.messages[0].id == reply.id


@pytest.mark.asyncio
async def test_silent_stop_in_dm_channel_fails_closed_with_error_message():
    """In direct messages, silent stop with no content is forbidden and produces an error."""
    provider = FakeProvider([Done(reason="stop")])
    store = InMemoryStore()
    store.channels["dm-custom"] = {"id": "dm-custom", "kind": "dm"}
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "dm-custom")

    assert reply is not None
    assert reply.kind == "error"
    assert "produced no answer in a direct message" in reply.body
    assert len(store.messages) == 1


# =============================================================================
# 3. Assistant > tool call > tool result > follow-up sequencing
# =============================================================================


@pytest.mark.asyncio
async def test_single_tool_round_protocol_shape_and_follow_up():
    """Tool invocation emits assistant call turn, system tool turn, and provider receives both."""
    provider = FakeProvider([
        ToolCallDelta(id="call_01", name="fs_read", args_fragment='{"path": "config.yaml"}'),
        Done(reason="tool_calls"),
    ])

    executed_calls = []

    async def executor(agent_id: str, tool_name: str, args: dict[str, Any]) -> str:
        executed_calls.append((agent_id, tool_name, args))
        provider.set_deltas([
            TextDelta(text="File content loaded successfully."),
            Done(reason="stop"),
        ])
        return "env: production"

    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store, executor=executor)
    agent = make_agent()

    async with hub.subscribe("*") as sub:
        reply = await runtime.run_turn(agent, "general")
        events = await drain_events(sub)

    assert executed_calls == [("jarvis", "fs_read", {"path": "config.yaml"})]
    assert reply.body == "File content loaded successfully."

    # Verify tool events published to Hub
    tool_calls = [e for e in events if e.type == "tool.call"]
    tool_results = [e for e in events if e.type == "tool.result"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["tool"] == "fs_read"
    assert len(tool_results) == 1
    assert tool_results[0].payload["result"] == "env: production"

    # Verify second-round transcript presented to provider
    round2_messages = provider.calls[1]["messages"]
    assistant_msg = next(m for m in round2_messages if m.author_kind == "agent")
    tool_msg = next(m for m in round2_messages if m.kind == "tool")

    meta = json.loads(assistant_msg.meta_json)
    assert meta["tool_calls"][0]["id"] == "call_01"
    assert meta["tool_calls"][0]["function"]["name"] == "fs_read"

    tool_meta = json.loads(tool_msg.meta_json)
    assert tool_meta["tool_call_id"] == "call_01"
    assert tool_meta["name"] == "fs_read"
    assert tool_msg.body == "env: production"


@pytest.mark.asyncio
async def test_parallel_multiple_tool_calls_in_single_round():
    """Multiple tool calls in a single assistant turn are executed and appended in sequence."""
    provider = FakeProvider([
        ToolCallDelta(id="call_a", name="scratchpad_read", args_fragment="{}"),
        ToolCallDelta(id="call_b", name="memory_read", args_fragment='{"name":"keys"}'),
        Done(reason="tool_calls"),
    ])

    calls = []

    async def executor(agent_id: str, tool_name: str, args: dict[str, Any]) -> str:
        calls.append(tool_name)
        if len(calls) == 2:
            provider.set_deltas([TextDelta(text="processed both"), Done(reason="stop")])
        return f"result_of_{tool_name}"

    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store, executor=executor)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "general")
    assert reply.body == "processed both"
    assert calls == ["scratchpad_read", "memory_read"]

    # Verify round 2 transcript contains both tool results
    round2_messages = provider.calls[1]["messages"]
    tool_turns = [m for m in round2_messages if m.kind == "tool"]
    assert len(tool_turns) == 2
    assert tool_turns[0].body == "result_of_scratchpad_read"
    assert tool_turns[1].body == "result_of_memory_read"


@pytest.mark.asyncio
async def test_multi_round_tool_loop_sequencing():
    """Sequential multi-round tool iterations maintain strict transcript formatting."""
    provider = FakeProvider([
        ToolCallDelta(id="call_1", name="step1", args_fragment="{}"),
        Done(reason="tool_calls"),
    ])

    round_counter = [0]

    async def executor(agent_id: str, tool_name: str, args: dict[str, Any]) -> str:
        round_counter[0] += 1
        if round_counter[0] == 1:
            provider.set_deltas([
                ToolCallDelta(id="call_2", name="step2", args_fragment="{}"),
                Done(reason="tool_calls"),
            ])
            return "done step 1"
        elif round_counter[0] == 2:
            provider.set_deltas([
                TextDelta(text="finished all steps"),
                Done(reason="stop"),
            ])
            return "done step 2"
        return "unexpected"

    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store, executor=executor)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "general")
    assert reply.body == "finished all steps"
    assert len(provider.calls) == 3


@pytest.mark.asyncio
async def test_unserviced_tool_calls_without_executor_produce_error():
    """A model requesting tool calls without an available executor fails as an error."""
    provider = FakeProvider([
        ToolCallDelta(id="c1", name="fs_read", args_fragment='{"path":"test"}'),
        Done(reason="stop"),
    ])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store, executor=None)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "general")

    assert reply is not None
    assert reply.kind == "error"
    assert "produced no answer" in reply.body


# =============================================================================
# 4. Provider concurrency/semaphore behavior
# =============================================================================


@pytest.mark.asyncio
async def test_provider_semaphore_bounds_concurrent_streams():
    """Provider semaphores cap concurrent in-flight streams at configured capacity."""
    concurrency_limit = 2
    active_streams = 0
    max_observed_active = 0
    lock = asyncio.Lock()

    class ConcurrencyTrackingProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            nonlocal active_streams, max_observed_active
            async with lock:
                active_streams += 1
                if active_streams > max_observed_active:
                    max_observed_active = active_streams
            await asyncio.sleep(0.05)
            async with lock:
                active_streams -= 1
            yield TextDelta(text="done")
            yield Done(reason="stop")

    hub, runtime = make_runtime(
        ConcurrencyTrackingProvider(),
        concurrency={"lmstudio": concurrency_limit},
    )

    agents = [make_agent(f"agent_{i}") for i in range(5)]
    tasks = [asyncio.create_task(runtime.run_turn(ag, "c1")) for ag in agents]
    await asyncio.gather(*tasks)

    assert max_observed_active == concurrency_limit


@pytest.mark.asyncio
async def test_independent_providers_do_not_block_each_other():
    """Saturated provider A does not delay or block provider B's turns."""
    slow_provider_started = asyncio.Event()

    class SlowProvider:
        name = "provider_a"

        async def stream(self, messages, tools, params):
            slow_provider_started.set()
            await asyncio.sleep(0.1)
            yield TextDelta(text="slow finished")
            yield Done(reason="stop")

    class FastProvider:
        name = "provider_b"

        async def stream(self, messages, tools, params):
            yield TextDelta(text="fast finished")
            yield Done(reason="stop")

    prov_a = SlowProvider()
    prov_b = FastProvider()

    def router(agent: Agent):
        return prov_a if agent.provider == "provider_a" else prov_b

    hub, runtime = make_runtime(
        router,
        concurrency={"provider_a": 1, "provider_b": 1},
    )

    agent_a = make_agent("agent_a", provider="provider_a")
    agent_b = make_agent("agent_b", provider="provider_b")

    task_a = asyncio.create_task(runtime.run_turn(agent_a, "c1"))
    await slow_provider_started.wait()

    # Fast provider B runs and finishes immediately while A is still busy
    reply_b = await runtime.run_turn(agent_b, "c1")
    assert reply_b.body == "fast finished"

    reply_a = await task_a
    assert reply_a.body == "slow finished"


@pytest.mark.asyncio
async def test_semaphore_is_released_on_stream_exception():
    """An exception inside the provider stream cleanly releases the semaphore."""
    first_call = True

    class FailingThenPassingProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            nonlocal first_call
            if first_call:
                first_call = False
                raise ProviderError("temporary glitch")
            yield TextDelta(text="recovered")
            yield Done(reason="stop")

    hub, runtime = make_runtime(
        FailingThenPassingProvider(),
        concurrency={"lmstudio": 1},
    )

    agent = make_agent()
    reply1 = await runtime.run_turn(agent, "c1")
    assert reply1.kind == "error"

    # Next turn succeeds immediately without being blocked by unreleased semaphore
    reply2 = await runtime.run_turn(agent, "c1")
    assert reply2.kind == "chat"
    assert reply2.body == "recovered"


@pytest.mark.asyncio
async def test_semaphore_is_released_on_turn_cancellation():
    """Cancelling a turn in-flight releases the semaphore for queued turns."""
    stream_started = asyncio.Event()

    class HangingThenFastProvider:
        name = "lmstudio"

        def __init__(self):
            self.hanging = True

        async def stream(self, messages, tools, params):
            if self.hanging:
                stream_started.set()
                await asyncio.sleep(5)
            yield TextDelta(text="success")
            yield Done(reason="stop")

    prov = HangingThenFastProvider()
    hub, runtime = make_runtime(prov, concurrency={"lmstudio": 1})
    agent = make_agent()

    task = asyncio.create_task(runtime.run_turn(agent, "c1"))
    await stream_started.wait()

    prov.hanging = False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Next turn can immediately acquire semaphore
    reply = await runtime.run_turn(agent, "c1")
    assert reply.body == "success"


# =============================================================================
# 5. TurnGuard and maximum tool-loop behavior
# =============================================================================


@pytest.mark.asyncio
async def test_turnguard_depth_limit_freezes_turn_and_posts_system_message():
    """When turn depth exceeds limits.max_depth, TurnGuard freezes the turn without inference."""
    provider = FakeProvider([TextDelta(text="unreachable"), Done(reason="stop")])
    guard = TurnGuard(TurnLimits(max_depth=3))
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store, guard=guard)
    agent = make_agent()

    async with hub.subscribe("turn.frozen") as sub:
        result = await runtime.run_turn(agent, "c1", turn_id="deep_turn", depth=4)
        frozen_events = await drain_events(sub)

    assert result is None
    assert provider.calls == []
    assert len(frozen_events) == 1
    assert frozen_events[0].payload["turn_id"] == "deep_turn"
    assert len(store.messages) == 1
    assert store.messages[0].author_id == "system"
    assert "Paused: conversation depth 4 exceeded the limit of 3" in store.messages[0].body


@pytest.mark.asyncio
async def test_turnguard_message_count_limit_freezes_turn():
    """Exceeding max_agent_messages freezes subsequent turns on the same turn_id."""
    provider = FakeProvider([TextDelta(text="hello"), Done(reason="stop")])
    guard = TurnGuard(TurnLimits(max_agent_messages=2))
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store, guard=guard)
    agent = make_agent()

    # 1st turn -> allowed
    r1 = await runtime.run_turn(agent, "c1", turn_id="counted_turn", depth=0)
    assert r1 is not None

    # 2nd turn -> allowed
    r2 = await runtime.run_turn(agent, "c1", turn_id="counted_turn", depth=1)
    assert r2 is not None

    # 3rd turn -> frozen
    r3 = await runtime.run_turn(agent, "c1", turn_id="counted_turn", depth=2)
    assert r3 is None
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_max_tool_iterations_terminates_infinite_tool_loop():
    """Tool execution loops terminate after max_tool_iterations and report stopping reason."""
    provider = FakeProvider([
        ToolCallDelta(id="c_inf", name="loop_tool", args_fragment="{}"),
        Done(reason="tool_calls"),
    ])

    async def executor(agent_id, name, args):
        return "looping"

    store = InMemoryStore()
    hub, runtime = make_runtime(
        provider,
        store=store,
        executor=executor,
        max_tool_iterations=4,
    )
    agent = make_agent()

    reply = await runtime.run_turn(agent, "general")

    assert len(provider.calls) == 4
    assert reply is not None
    assert "_Stopped after 4 tool rounds without finishing._" in reply.body


# =============================================================================
# 6. MCP/tool allowlist refusal and confinement
# =============================================================================


def test_core_tools_sandboxed_tier_refuses_fs_and_task_tools(tmp_path):
    """Sandboxed tier agents are denied access to fs and task management tools."""
    tools = CoreTools(agents_root=tmp_path / "agents")
    sandboxed_agent = make_agent("sandboxed_bot")
    profile = {"trust": "sandboxed"}

    specs = tools.specs_for(sandboxed_agent, profile)
    spec_names = {s.name for s in specs}

    assert "fs_read" not in spec_names
    assert "task_create" not in spec_names
    assert "scratchpad_read" in spec_names
    assert "memory_write" in spec_names


@pytest.mark.asyncio
async def test_core_tools_execution_tier_refusal(tmp_path):
    """Calling an un-offered tool produces an informative error response."""
    tools = CoreTools(agents_root=tmp_path / "agents")
    sandboxed_agent = make_agent("sandboxed_bot")
    profile = {"trust": "sandboxed"}

    result = await tools.execute(sandboxed_agent, "fs_read", {"path": "a.txt"}, profile=profile)
    assert "is not available to sandboxed_bot" in result


def test_filesystem_path_confinement_traversal_refusal(tmp_path):
    """CoreTools fs_read and fs_list refuse directory traversal attempts."""
    agents_root = tmp_path / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    tools = CoreTools(agents_root=agents_root)
    agent = make_agent("trusted_bot")

    # Attempt to read path escaping agents_root
    with pytest.raises(ToolError, match="confinement violation"):
        tools._fs_read(agent, {"path": "../../outside_secret.txt"})


def test_memory_note_safe_name_confinement_refusal(tmp_path):
    """Memory note operations reject path separators and invalid note names."""
    tools = CoreTools(agents_root=tmp_path / "agents")
    agent = make_agent("test_agent")

    with pytest.raises(ToolError, match="not a usable note name"):
        tools._memory_write(agent, {"name": "../escaped_note", "body": "content"})

    with pytest.raises(ToolError, match="not a usable note name"):
        tools._memory_write(agent, {"name": "sub/folder/note", "body": "content"})


@pytest.mark.asyncio
async def test_composite_tool_executor_refuses_unoffered_mcp_tools(tmp_path):
    """CompositeToolExecutor rejects MCP tool invocations not present in the agent's offered specs."""
    core = CoreTools(agents_root=tmp_path / "agents")
    registry = MCPRegistry(repo_root=tmp_path)
    composite = CompositeToolExecutor(core, registry)

    agent = make_agent("worker")
    profile = {"tools_enabled": ["cerebro-core:*"]}

    result = await composite.execute(agent, "weather__get_temp", {}, profile=profile)
    assert "'weather__get_temp' is not available to worker" in result


@pytest.mark.asyncio
async def test_stdio_mcp_client_rejects_npx_uvx_dynamic_downloads():
    """StdioMCPClient forbids dynamic download commands (npx -y / uvx) per security directives."""
    npx_config = MCPServerConfig(name="unsafe_npx", command="npx", args=["-y", "mcp-server"])
    client_npx = StdioMCPClient(npx_config)

    with pytest.raises(MCPClientError, match="Dynamic tool download commands"):
        await client_npx.start()

    uvx_config = MCPServerConfig(name="unsafe_uvx", command="uvx", args=["mcp-server"])
    client_uvx = StdioMCPClient(uvx_config)

    with pytest.raises(MCPClientError, match="Dynamic tool download commands"):
        await client_uvx.start()


# =============================================================================
# 7. Cancellation and terminal UI/runtime state
# =============================================================================


@pytest.mark.asyncio
async def test_cancellation_emits_cancelled_status_and_leaves_clean_database():
    """Cancelling an in-flight turn updates status, publishes turn.cancelled, and writes zero rows."""
    store = InMemoryStore()
    hub = Hub()

    class StalledProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            await asyncio.sleep(10)
            yield TextDelta(text="never delivered")
            yield Done(reason="stop")

    runtime = AgentRuntime(hub=hub, store=store, provider_for=lambda a: StalledProvider())
    agent = make_agent()

    async with hub.subscribe("*") as sub:
        turn_task = asyncio.create_task(runtime.run_turn(agent, "c1", turn_id="turn_to_cancel"))
        await asyncio.sleep(0.02)
        turn_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn_task
        events = await drain_events(sub)

    assert store.messages == []

    cancelled_events = [e for e in events if e.type == "turn.cancelled"]
    assert len(cancelled_events) == 1
    assert cancelled_events[0].payload["turn_id"] == "turn_to_cancel"
    assert cancelled_events[0].payload["agent_id"] == "jarvis"

    status_events = [e for e in events if e.type == "agent.status"]
    assert status_events[-1].payload["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancellation_propagates_to_cli_subprocess():
    """Cancellation of a CliAgentProvider stream terminates the underlying subprocess."""
    harness = fake_script_harness("import time, sys; sys.stdin.read(); time.sleep(30)")
    prov = CliAgentProvider(self_id="claude", command=harness, timeout_s=10)

    async def run_stream():
        msgs = [Message(channel_id="c1", author_id="dante", author_kind="user", body="hello")]
        return [d async for d in prov.stream(msgs, [], Params())]

    task = asyncio.create_task(run_stream())
    await asyncio.sleep(0.4)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# =============================================================================
# 8. Usage accounting and persistence
# =============================================================================


@pytest.mark.asyncio
async def test_usage_delta_publishes_event_and_persists_to_budget_usage(test_db):
    """Usage delta publishes usage event to Hub and records measured tokens in database."""
    from cerebro import db

    provider = FakeProvider([
        TextDelta(text="result"),
        Usage(input=200, output=80),
        Done(reason="stop"),
    ])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent("jarvis")

    async with hub.subscribe("usage") as sub:
        await runtime.run_turn(agent, "general")
        usage_events = await drain_events(sub)

    assert len(usage_events) == 1
    assert usage_events[0].payload["agent_id"] == "jarvis"
    assert usage_events[0].payload["input"] == 200
    assert usage_events[0].payload["output"] == 80

    rows = await db.fetch_all("SELECT * FROM budget_usage WHERE scope_id = 'jarvis'")
    assert len(rows) == 1
    assert rows[0]["input_tokens"] == 200
    assert rows[0]["output_tokens"] == 80


@pytest.mark.asyncio
async def test_usage_persistence_failure_is_non_fatal(monkeypatch):
    """Database failure during usage recording never crashes or aborts the turn."""
    async def failing_write(*args, **kwargs):
        raise RuntimeError("database write failure")

    monkeypatch.setattr("cerebro.db.enqueue_write", failing_write)

    provider = FakeProvider([
        TextDelta(text="success despite usage failure"),
        Usage(input=100, output=50),
        Done(reason="stop"),
    ])
    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "general")
    assert reply is not None
    assert reply.body == "success despite usage failure"


# =============================================================================
# 9. Provider/tool failure behavior without orphaning a turn
# =============================================================================


@pytest.mark.asyncio
async def test_provider_unavailable_persists_error_and_returns_idle_status():
    """ProviderUnavailable becomes an error message row and resets status to idle."""
    class OfflineProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            raise ProviderUnavailable("Connection refused at port 1234")
            yield

    store = InMemoryStore()
    hub, runtime = make_runtime(OfflineProvider(), store=store)
    agent = make_agent()

    async with hub.subscribe("*") as sub:
        reply = await runtime.run_turn(agent, "c1", turn_id="turn_offline")
        events = await drain_events(sub)

    assert reply.kind == "error"
    assert "backend offline — Connection refused" in reply.body

    error_events = [e for e in events if e.type == "error"]
    assert len(error_events) == 1
    assert error_events[0].payload["turn_id"] == "turn_offline"

    status_events = [e for e in events if e.type == "agent.status"]
    assert status_events[-1].payload["status"] == "idle"


@pytest.mark.asyncio
async def test_provider_error_persists_error_and_returns_idle_status():
    """ProviderError becomes an error message row and announces completion."""
    class BrokenProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            raise ProviderError("context window exceeded")
            yield

    store = InMemoryStore()
    hub, runtime = make_runtime(BrokenProvider(), store=store)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "c1")
    assert reply.kind == "error"
    assert "provider error — context window exceeded" in reply.body


@pytest.mark.asyncio
async def test_unexpected_exception_persists_error_and_returns_idle_status():
    """Arbitrary unexpected exceptions in provider stream fail gracefully without crashing."""
    class ExplodingProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            raise ValueError("unexpected corrupt state")
            yield

    store = InMemoryStore()
    hub, runtime = make_runtime(ExplodingProvider(), store=store)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "c1")
    assert reply.kind == "error"
    assert "unexpected error — ValueError('unexpected corrupt state')" in reply.body


@pytest.mark.asyncio
async def test_tool_execution_exception_is_captured_and_reported_to_model():
    """Exceptions raised by tool implementations are returned as error strings for model recovery."""
    provider = FakeProvider([
        ToolCallDelta(id="c_err", name="unstable_tool", args_fragment="{}"),
        Done(reason="tool_calls"),
    ])

    async def executor(agent_id, name, args):
        provider.set_deltas([
            TextDelta(text="Handled tool error gracefully."),
            Done(reason="stop"),
        ])
        raise RuntimeError("file system locked")

    store = InMemoryStore()
    hub, runtime = make_runtime(provider, store=store, executor=executor)
    agent = make_agent()

    reply = await runtime.run_turn(agent, "general")
    assert reply.body == "Handled tool error gracefully."

    round2_messages = provider.calls[1]["messages"]
    tool_msg = next(m for m in round2_messages if m.kind == "tool")
    assert "error: RuntimeError('file system locked')" in tool_msg.body


@pytest.mark.asyncio
async def test_malformed_tool_args_reported_to_model():
    """Invalid JSON arguments from the model generate an error string rather than raising."""
    stream_count = 0

    class RetryingProvider:
        name = "lmstudio"
        self_id = "jarvis"

        async def stream(self, messages, tools, params):
            nonlocal stream_count
            stream_count += 1
            if stream_count == 1:
                yield ToolCallDelta(id="c_bad_json", name="fs_read", args_fragment="{broken json")
                yield Done(reason="tool_calls")
            else:
                yield TextDelta(text="Recovered from malformed JSON")
                yield Done(reason="stop")

    executed = []

    async def executor(agent_id, name, args):
        executed.append(name)
        return "unreachable"

    store = InMemoryStore()
    hub, runtime = make_runtime(RetryingProvider(), store=store, executor=executor)
    agent = make_agent()

    async with hub.subscribe("tool.result") as sub:
        reply = await runtime.run_turn(agent, "general")
        results = await drain_events(sub)

    assert executed == []
    assert len(results) == 1
    assert "arguments were not valid JSON" in results[0].payload["result"]
    assert reply.body == "Recovered from malformed JSON"


# =============================================================================
# 10. Existing CLI-provider behavior
# =============================================================================


def test_cli_agent_renders_prompt_with_role_labels():
    """render_prompt labels agent messages, user messages, and peer agents explicitly."""
    messages = [
        Message(channel_id="c1", author_id="system", author_kind="system", body="system directive"),
        Message(channel_id="c1", author_id="dante", author_kind="user", body="how is the build?"),
        Message(channel_id="c1", author_id="sonnet", author_kind="agent", body="I reviewed it."),
        Message(channel_id="c1", author_id="codex", author_kind="agent", body="Tests passed."),
    ]
    prompt = render_prompt(messages, self_id="sonnet")

    assert "[System]\nsystem directive" in prompt
    assert "[Dante]\nhow is the build?" in prompt
    assert "[sonnet (you)]\nI reviewed it." in prompt
    assert "[codex]\nTests passed." in prompt


def test_cli_agent_extracts_reasoning_and_strips_banner():
    """parse_cli_output strips startup banners and separates inner reasoning tags."""
    raw_output = (
        "__( O)>  ● new session\n"
        "   L L   goose is ready\n"
        "<thought>Evaluating the requested task.</thought>"
        "Ready to assist, Dante."
    )
    reasoning, clean = parse_cli_output(raw_output, backend="goose")
    assert "Evaluating the requested task." in reasoning
    assert clean == "Ready to assist, Dante."


@pytest.mark.asyncio
async def test_cli_agent_handles_nonzero_exit_and_drains_stderr():
    """CLI subprocess exiting with non-zero status raises ProviderError with stderr output."""
    script = "import sys; sys.stdin.read(); sys.stderr.write('fatal: syntax error\\n'); sys.exit(2)"
    harness = fake_script_harness(script)
    prov = CliAgentProvider(self_id="claude", command=harness)

    msgs = [Message(channel_id="c1", author_id="dante", author_kind="user", body="test")]
    with pytest.raises(ProviderError) as exc:
        async for _ in prov.stream(msgs, [], Params()):
            pass

    assert "exited 2" in str(exc.value)
    assert "fatal: syntax error" in str(exc.value)


@pytest.mark.asyncio
async def test_cli_agent_output_file_mode_ignores_stdout_noise(monkeypatch):
    """Output file mode (e.g. codex --output-last-message) captures clean file and ignores stdout noise."""
    from cerebro.providers import cli_agent

    monkeypatch.setitem(cli_agent.OUTPUT_FILE_FLAG, "fake_file_backend", "--out-file")
    script = (
        "import sys;"
        "sys.stdin.read();"
        "out_idx = sys.argv.index('--out-file') + 1;"
        "out_path = sys.argv[out_idx];"
        "sys.stdout.write('NOISE: internal debug logs\\n' * 50);"
        "open(out_path, 'w', encoding='utf-8').write('The clean final answer.')"
    )
    harness = fake_script_harness(script)
    prov = CliAgentProvider(self_id="codex", backend="fake_file_backend", command=harness)

    msgs = [Message(channel_id="c1", author_id="dante", author_kind="user", body="hello")]
    deltas = [d async for d in prov.stream(msgs, [], Params())]
    text_deltas = [d.text for d in deltas if isinstance(d, TextDelta)]

    assert "".join(text_deltas) == "The clean final answer."
    assert not any("NOISE" in d.text for d in deltas if isinstance(d, TextDelta))
