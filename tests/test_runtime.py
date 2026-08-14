"""The agent turn loop: streaming, persistence ordering, tool rounds and failure handling."""

import json

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


async def test_reply_is_persisted_before_the_first_token():
    """A client reconnecting mid-stream must find the row already there."""
    provider = FakeProvider([TextDelta(text="hi "), TextDelta(text="there"), Done(reason="stop")])
    store = MemoryStore()
    hub, runtime = build(provider, store)

    async with hub.subscribe() as sub:
        reply = await runtime.run_turn(AGENT, "c1")
        events = await drain(sub)

    kinds = [e.type for e in events]
    assert kinds[0] == "message.new"
    assert events[0].payload["message"]["body"] == ""
    assert "message.delta" in kinds
    assert kinds[-1] == "message.done"

    assert reply.body == "hi there"
    assert store.messages[0].body == "hi there"


async def test_deltas_carry_the_persisted_message_id():
    provider = FakeProvider([TextDelta(text="x"), Done(reason="stop")])
    hub, runtime = build(provider)

    async with hub.subscribe("message.delta") as sub:
        reply = await runtime.run_turn(AGENT, "c1")
        deltas = await drain(sub)

    assert [d.payload["message_id"] for d in deltas] == [reply.id]


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


async def test_reasoning_is_neither_published_nor_persisted():
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

    async with hub.subscribe() as sub:
        reply = await runtime.run_turn(AGENT, "c1")
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

    async with hub.subscribe("message.discarded") as sub:
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
