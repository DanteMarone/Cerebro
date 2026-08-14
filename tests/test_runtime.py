"""The agent turn loop: streaming, persistence ordering, tool rounds and failure handling."""

import json
from pathlib import Path

import pytest

from cerebro.hub import Hub
from cerebro.models import Agent, Done, Message, ReasoningDelta, TextDelta, ToolCallDelta
from cerebro.providers.fake import FakeProvider
from cerebro.providers.lmstudio import ProviderUnavailable
from cerebro.runtime import AgentRuntime
from cerebro.turnguard import TurnGuard, TurnLimits


class MemoryStore:
    """The four methods the runtime needs, backed by a list."""

    def __init__(self, prompt="you are jarvis"):
        self.messages: list[Message] = []
        self.prompt = prompt
        self._next_id = 1

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


AGENT = Agent(id="jarvis", name="jarvis", provider="lmstudio")


@pytest.fixture(autouse=True)
def _agent_homes_stay_in_tmp(tmp_path, monkeypatch):
    """Keep this file's agents out of the real `agents/` directory.

    AGENT deliberately has no home_path, which is the shape that leaked: the runtime used to fall
    back to a CWD-relative `agents/<id>`, so running this suite from the repo root appended fixture
    text to the live Jarvis's reasoning log. The runtime now anchors to settings.agents_path, and
    this pins that root to tmp so a regression cannot quietly reach the real workspace again.
    """
    _pin_agents_root(monkeypatch, tmp_path)


def _pin_agents_root(monkeypatch, tmp_path):
    """Point the runtime's settings at a throwaway agents root.

    Settings is a frozen dataclass, so the whole object is replaced in the runtime's namespace
    rather than one field being reassigned.
    """
    import dataclasses

    from cerebro.config import settings

    monkeypatch.setattr(
        "cerebro.runtime.settings",
        dataclasses.replace(settings, agents_path=tmp_path / "agents"),
    )


def test_reasoning_is_logged_under_the_configured_agents_root(tmp_path, monkeypatch):
    """The regression itself: a homeless agent must not write outside the configured root.

    Runs from the repo CWD with an agent whose home_path is unset -- exactly the shape that put 47
    fixture strings into the live Jarvis's reasoning log -- and asserts the real tree is untouched.
    """
    _pin_agents_root(monkeypatch, tmp_path)
    assert AGENT.home_path is None, "the regression depends on this agent having no home"
    real_agents = Path("agents") / AGENT.id / "logs"
    before = set(real_agents.glob("*.log")) if real_agents.exists() else set()

    hub, runtime = build(FakeProvider([]))
    runtime._log_thinking(AGENT, "secret deliberation")

    written = list((tmp_path / "agents" / AGENT.id / "logs").glob("*.log"))
    assert written, "reasoning should land under settings.agents_path"
    assert "secret deliberation" in written[0].read_text(encoding="utf-8")

    after = set(real_agents.glob("*.log")) if real_agents.exists() else set()
    assert after == before, "the real agents/ directory must be untouched"


def build(provider, store=None, guard=None, executor=None, tools=None):
    hub = Hub()
    runtime = AgentRuntime(
        hub=hub,
        store=store or MemoryStore(),
        provider_for=lambda a: provider,
        guard=guard,
        tool_executor=executor,
        tools_for=(lambda a: tools or []),
    )
    return hub, runtime


async def drain(sub):
    out = []
    while not sub._queue.empty():
        out.append(await sub.get())
    return out


async def test_reply_is_persisted_only_on_completion():
    """Messages are persisted only when complete, eliminating orphaned placeholders."""
    provider = FakeProvider([TextDelta(text="hi "), TextDelta(text="there"), Done(reason="stop")])
    store = MemoryStore()
    hub, runtime = build(provider, store)

    async with hub.subscribe() as sub:
        reply = await runtime.run_turn(AGENT, "c1")
        events = await drain(sub)

    kinds = [e.type for e in events]
    assert "agent.activity" in kinds
    assert "turn.delta" in kinds
    assert "message.new" in kinds
    assert "message.done" in kinds
    assert kinds[-1] == "message.done"

    # Message row is created on completion with full body
    assert reply.body == "hi there"
    assert len(store.messages) == 1
    assert store.messages[0].body == "hi there"


async def test_deltas_carry_turn_id_and_agent_id():
    provider = FakeProvider([TextDelta(text="x"), Done(reason="stop")])
    hub, runtime = build(provider)

    async with hub.subscribe("turn.delta") as sub:
        await runtime.run_turn(AGENT, "c1", turn_id="turn-123")
        deltas = await drain(sub)

    assert len(deltas) == 1
    assert deltas[0].payload["turn_id"] == "turn-123"
    assert deltas[0].payload["agent_id"] == "jarvis"
    assert deltas[0].payload["text"] == "x"


async def test_context_puts_the_system_prompt_first():
    provider = FakeProvider([Done(reason="stop")])
    store = MemoryStore(prompt="you are jarvis")
    await store.append_message(
        Message(channel_id="c1", author_id="dante", author_kind="user", body="hello")
    )
    _, runtime = build(provider, store)

    await runtime.run_turn(AGENT, "c1")

    sent = provider.calls[0]["messages"]
    assert sent[0].author_kind == "system"
    assert sent[0].body == "you are jarvis"
    assert sent[1].body == "hello"


async def test_a_frozen_turn_never_reaches_the_provider():
    """The guard runs before the call, so a runaway turn costs no inference."""
    provider = FakeProvider([TextDelta(text="should not happen"), Done(reason="stop")])
    guard = TurnGuard(TurnLimits(max_depth=2))
    hub, runtime = build(provider, guard=guard)

    async with hub.subscribe("turn.frozen") as sub:
        result = await runtime.run_turn(AGENT, "c1", turn_id="T1", depth=9)
        frozen = await drain(sub)

    assert result is None
    assert provider.calls == []
    assert len(frozen) == 1


async def test_an_offline_backend_becomes_a_message_not_a_crash():
    class Dead:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            raise ProviderUnavailable("LM Studio is not reachable at http://127.0.0.1:1234")
            yield  # pragma: no cover - makes this an async generator

    store = MemoryStore()
    hub, runtime = build(Dead(), store)

    async with hub.subscribe("error") as sub:
        reply = await runtime.run_turn(AGENT, "c1")
        errors = await drain(sub)

    assert reply.kind == "error"
    assert "backend offline" in reply.body
    assert store.messages[0].body == reply.body
    assert len(errors) == 1


async def test_tool_call_runs_and_its_result_is_fed_back():
    provider = FakeProvider([
        ToolCallDelta(id="call_1", name="fs_read", args_fragment='{"path":"a.txt"}'),
        Done(reason="tool_calls"),
    ])
    calls = []

    async def executor(agent_id, tool, args):
        calls.append((agent_id, tool, args))
        provider.set_deltas([TextDelta(text="the file says hello"), Done(reason="stop")])
        return "hello"

    hub, runtime = build(provider, executor=executor)
    reply = await runtime.run_turn(AGENT, "c1")

    assert calls == [("jarvis", "fs_read", {"path": "a.txt"})]
    assert reply.body == "the file says hello"
    # The tool result must be visible to the model on the second round.
    second_round = provider.calls[1]["messages"]
    assert any("hello" in m.body for m in second_round if m.kind == "tool")


async def test_malformed_tool_arguments_are_returned_to_the_model():
    """Weak local models emit broken JSON; that is data to correct, not an exception."""
    provider = FakeProvider([
        ToolCallDelta(id="call_1", name="fs_read", args_fragment="{not json"),
        Done(reason="tool_calls"),
    ])
    executed = []

    async def executor(agent_id, tool, args):  # pragma: no cover - must not run
        executed.append(tool)
        return "unreachable"

    hub, runtime = build(provider, executor=executor)
    async with hub.subscribe("tool.result") as sub:
        provider.set_deltas([
            ToolCallDelta(id="call_1", name="fs_read", args_fragment="{not json"),
            Done(reason="tool_calls"),
        ])
        await runtime.run_turn(AGENT, "c1")
        results = await drain(sub)

    assert executed == []
    assert "not valid JSON" in results[0].payload["result"]


async def test_a_failing_tool_does_not_end_the_turn():
    provider = FakeProvider([
        ToolCallDelta(id="call_1", name="explode", args_fragment="{}"),
        Done(reason="tool_calls"),
    ])

    async def executor(agent_id, tool, args):
        provider.set_deltas([TextDelta(text="recovered"), Done(reason="stop")])
        raise RuntimeError("boom")

    hub, runtime = build(provider, executor=executor)
    reply = await runtime.run_turn(AGENT, "c1")

    assert reply.body == "recovered"


async def test_tool_rounds_are_bounded():
    """A model that only ever asks for tools must still terminate."""
    provider = FakeProvider([
        ToolCallDelta(id="c", name="loop", args_fragment="{}"),
        Done(reason="tool_calls"),
    ])

    async def executor(agent_id, tool, args):
        return "again"

    hub, runtime = build(provider, executor=executor)
    runtime.max_tool_iterations = 3
    reply = await runtime.run_turn(AGENT, "c1")

    assert len(provider.calls) == 3
    assert "Stopped after 3 tool rounds" in reply.body


async def test_status_events_bracket_the_turn():
    provider = FakeProvider([TextDelta(text="x"), Done(reason="stop")])
    hub, runtime = build(provider)

    async with hub.subscribe("agent.status") as sub:
        await runtime.run_turn(AGENT, "c1")
        statuses = [e.payload["status"] for e in await drain(sub)]

    assert statuses[0] == "thinking"
    assert statuses[-1] == "idle"


async def test_the_placeholder_row_is_not_fed_back_to_the_model():
    """Context is built before the empty reply is persisted.

    Against gpt-oss-20b, letting the placeholder into history made the model see itself having
    already answered with nothing, and it produced an empty reply.
    """
    provider = FakeProvider([TextDelta(text="real answer"), Done(reason="stop")])
    store = MemoryStore()
    await store.append_message(
        Message(channel_id="c1", author_id="dante", author_kind="user", body="question?")
    )
    _, runtime = build(provider, store)

    await runtime.run_turn(AGENT, "c1")

    sent = provider.calls[0]["messages"]
    assert [m.body for m in sent] == ["you are jarvis", "question?"]
    assert not any(m.body == "" for m in sent)


async def test_reasoning_is_neither_published_nor_persisted(tmp_path):
    """Superseded by Dante's call that thinking is private.

    This test previously asserted the opposite -- that reasoning was streamed live into the
    channel. He watched it happen and said the room should carry collaboration, not an inner
    monologue. Keeping the old assertion alongside the new rule would leave two tests disagreeing
    about what the product does.
    """
    provider = FakeProvider([
        ReasoningDelta(text="let me think"),
        TextDelta(text="the answer"),
        Done(reason="stop"),
    ])
    hub, runtime = build(provider)
    # A home under tmp_path: without it the runtime writes reasoning into the *live*
    # agents/jarvis/logs, and test fixtures end up in a real agent's private log.
    agent = Agent(id="jarvis", name="jarvis", provider="lmstudio",
                  home_path=str(tmp_path / "jarvis"))

    async with hub.subscribe() as sub:
        reply = await runtime.run_turn(agent, "c1")
        events = await drain(sub)

    assert reply.body == "the answer"
    assert not any(e.type == "agent.thinking" for e in events)


async def test_message_done_uses_the_same_envelope_as_message_new():
    """The front end reads payload.message on both. A bare message payload silently broke the
    done handler: the thinking block never cleared and the live stream was never replaced."""
    provider = FakeProvider([TextDelta(text="final"), Done(reason="stop")])
    hub, runtime = build(provider)

    async with hub.subscribe("message.*") as sub:
        reply = await runtime.run_turn(AGENT, "c1")
        events = await drain(sub)

    for etype in ("message.new", "message.done"):
        event = next(e for e in events if e.type == etype)
        assert set(event.payload) >= {"channel_id", "message"}, etype
        assert event.payload["message"]["id"] == reply.id, etype
    done = next(e for e in events if e.type == "message.done")
    assert done.payload["message"]["body"] == "final"


async def test_a_pass_reply_is_discarded_and_leaves_no_row():
    """§6: an agent with nothing to add says PASS, and PASS must not become a message.

    Otherwise every poll of every agent leaves a row saying "nothing to say", and the channel
    fills with silence made visible.
    """
    provider = FakeProvider([TextDelta(text="PASS"), Done(reason="stop")])
    store = MemoryStore()
    hub, runtime = build(provider, store)

    async with hub.subscribe("turn.discarded") as sub:
        result = await runtime.run_turn(AGENT, "c1")
        discarded = await drain(sub)

    assert result is None
    assert store.messages == []
    assert len(discarded) == 1


async def test_pass_matching_is_strict():
    """"PASS - nothing to add" has said something; treating it as silence would hide content."""
    from cerebro.runtime import is_pass

    assert is_pass("PASS")
    assert is_pass("  pass  ")
    assert is_pass("Pass.")
    assert not is_pass("PASS - nothing to add")
    assert not is_pass("I'll pass on this one")
    assert not is_pass("")


async def test_an_empty_answer_becomes_an_explained_error_not_a_blank_message():
    """A reasoning model can burn its whole budget thinking and never answer.

    qwen3.6-27b did exactly that: 200 reasoning deltas, zero content, finish reason `length`.
    The blank row that produced told Dante only that the product was broken.
    """
    provider = FakeProvider([ReasoningDelta(text="thinking hard"), Done(reason="length")])
    store = MemoryStore()
    hub, runtime = build(provider, store)

    reply = await runtime.run_turn(AGENT, "c1")

    assert reply.kind == "error"
    assert "ran out of tokens" in reply.body
    assert "max_tokens" in reply.body


async def test_an_empty_answer_with_a_normal_finish_still_errors():
    provider = FakeProvider([Done(reason="stop")])
    hub, runtime = build(provider)

    reply = await runtime.run_turn(AGENT, "c1")

    assert reply.kind == "error"
    assert "no answer" in reply.body


async def test_reasoning_never_reaches_the_channel(tmp_path):
    """Thinking is private (Dante): the room sees collaboration, not an inner monologue."""
    provider = FakeProvider([
        ReasoningDelta(text="let me work through this at length"),
        TextDelta(text="here is the answer"),
        Done(reason="stop"),
    ])
    hub, runtime = build(provider)
    agent = Agent(id="jarvis", name="jarvis", provider="lmstudio",
                  home_path=str(tmp_path / "jarvis"))

    async with hub.subscribe() as sub:
        reply = await runtime.run_turn(agent, "c1")
        events = await drain(sub)

    assert reply.body == "here is the answer"
    assert not any(e.type == "agent.thinking" for e in events), "reasoning was published"
    for event in events:
        leaked = "work through this" in json.dumps(event.payload)
        assert not leaked, f"reasoning leaked into {event.type}"


async def test_reasoning_is_written_to_the_agents_own_log(tmp_path):
    provider = FakeProvider([
        ReasoningDelta(text="private deliberation"),
        TextDelta(text="answer"),
        Done(reason="stop"),
    ])
    _, runtime = build(provider)
    home = tmp_path / "jarvis"
    agent = Agent(id="jarvis", name="jarvis", provider="lmstudio", home_path=str(home))

    await runtime.run_turn(agent, "c1")

    logs = list((home / "logs").glob("reasoning-*.log"))
    assert logs, "no reasoning log written"
    assert "private deliberation" in logs[0].read_text(encoding="utf-8")


async def test_two_overlapping_turns_finish_in_reverse_order():
    """Completion-ordered chat: Turn B finishes before Turn A, so Message B appears before A."""
    import asyncio

    store = MemoryStore()
    hub = Hub()

    agent_slow = Agent(id="slow_agent", name="slow", provider="lmstudio")
    agent_fast = Agent(id="fast_agent", name="fast", provider="lmstudio")

    provider_slow = FakeProvider([TextDelta(text="slow reply"), Done(reason="stop")], delay_s=0.08)
    provider_fast = FakeProvider([TextDelta(text="fast reply"), Done(reason="stop")], delay_s=0.0)

    def provider_for(agent: Agent):
        return provider_slow if agent.id == "slow_agent" else provider_fast

    runtime = AgentRuntime(
        hub=hub,
        store=store,
        provider_for=provider_for,
    )

    # Start slow turn first, then fast turn immediately after
    task_slow = asyncio.create_task(runtime.run_turn(agent_slow, "c1"))
    await asyncio.sleep(0.01)
    task_fast = asyncio.create_task(runtime.run_turn(agent_fast, "c1"))

    await asyncio.gather(task_slow, task_fast)

    # Fast agent finished first -> ID 1 and first in transcript
    # Slow agent finished second -> ID 2 and second in transcript
    assert len(store.messages) == 2
    assert store.messages[0].author_id == "fast_agent"
    assert store.messages[0].body == "fast reply"
    assert store.messages[0].id == 1

    assert store.messages[1].author_id == "slow_agent"
    assert store.messages[1].body == "slow reply"
    assert store.messages[1].id == 2


async def test_quote_msg_id_is_preserved_on_reply():
    """quote_msg_id identifies what prompted the turn while completion time controls ordering."""
    provider = FakeProvider([TextDelta(text="answering question"), Done(reason="stop")])
    store = MemoryStore()
    hub, runtime = build(provider, store)

    reply = await runtime.run_turn(AGENT, "c1", quote_msg_id=42)

    assert reply.quote_msg_id == 42
    assert store.messages[0].quote_msg_id == 42


async def test_no_empty_placeholder_rows_created_during_generation():
    """During inference, zero rows exist in the database transcript."""
    store = MemoryStore()
    hub = Hub()

    messages_during_stream = []

    class AssertingProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            messages_during_stream.append(len(store.messages))
            yield TextDelta(text="computed answer")
            messages_during_stream.append(len(store.messages))
            yield Done(reason="stop")

    runtime = AgentRuntime(
        hub=hub,
        store=store,
        provider_for=lambda a: AssertingProvider(),
    )

    reply = await runtime.run_turn(AGENT, "c1")

    # While generating, zero rows existed in the database
    assert messages_during_stream == [0, 0]
    # Only upon completion does the single completed row appear
    assert len(store.messages) == 1
    assert store.messages[0].id == reply.id


async def test_same_agent_overlapping_turns_have_distinct_turn_ids():
    """Two turns for the same agent carry distinct turn_ids on events and persistence."""
    import asyncio

    store = MemoryStore()
    hub = Hub()

    provider_slow = FakeProvider([TextDelta(text="first reply"), Done(reason="stop")], delay_s=0.06)
    provider_fast = FakeProvider([TextDelta(text="second reply"), Done(reason="stop")], delay_s=0.0)

    call_count = [0]

    def provider_for(agent: Agent):
        call_count[0] += 1
        return provider_slow if call_count[0] == 1 else provider_fast

    runtime = AgentRuntime(
        hub=hub,
        store=store,
        provider_for=provider_for,
    )

    async with hub.subscribe("agent.activity") as sub:
        task1 = asyncio.create_task(runtime.run_turn(AGENT, "c1", turn_id="turn_A"))
        await asyncio.sleep(0.01)
        task2 = asyncio.create_task(runtime.run_turn(AGENT, "c1", turn_id="turn_B"))
        await asyncio.gather(task1, task2)
        events = await drain(sub)

    turn_ids = {e.payload.get("turn_id") for e in events if "turn_id" in e.payload}
    assert turn_ids == {"turn_A", "turn_B"}

    # Fast turn (turn_B) finishes first, then slow turn (turn_A)
    assert store.messages[0].turn_id == "turn_B"
    assert store.messages[0].body == "second reply"
    assert store.messages[1].turn_id == "turn_A"
    assert store.messages[1].body == "first reply"


async def test_cancelled_turn_emits_terminal_activity_event_and_leaves_no_rows():
    """A cancelled turn publishes turn.cancelled with turn_id and leaves zero database rows."""
    import asyncio

    store = MemoryStore()
    hub = Hub()

    class HangingProvider:
        name = "lmstudio"

        async def stream(self, messages, tools, params):
            await asyncio.sleep(10)
            yield TextDelta(text="never reached")
            yield Done(reason="stop")

    runtime = AgentRuntime(
        hub=hub,
        store=store,
        provider_for=lambda a: HangingProvider(),
    )

    async with hub.subscribe("*") as sub:
        task = asyncio.create_task(runtime.run_turn(AGENT, "c1", turn_id="turn_cancelled_1"))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        events = await drain(sub)

    kinds = [e.type for e in events]
    assert "turn.cancelled" in kinds
    cancelled_event = next(e for e in events if e.type == "turn.cancelled")
    assert cancelled_event.payload["turn_id"] == "turn_cancelled_1"
    assert cancelled_event.payload["agent_id"] == "jarvis"

    # Zero rows created in database
    assert store.messages == []
