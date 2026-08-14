"""Tests for FakeProvider."""

import pytest
import json

from cerebro.models import Done, Message, TextDelta, ToolCallDelta, Usage
from cerebro.providers.base import Params, ToolSpec
from cerebro.providers.fake import FakeProvider


@pytest.mark.asyncio
async def test_fake_provider_streaming_and_call_recording():
    """Verify FakeProvider streams scripted deltas and records call arguments."""
    provider = FakeProvider(
        deltas=[
            TextDelta(text="Hello "),
            TextDelta(text="Dante!"),
            ToolCallDelta(id="tc_1", name="fs_read", args_fragment='{"path": "test.txt"}'),
            Usage(input=10, output=25),
            Done(reason="stop"),
        ]
    )

    messages = [
        Message(
            channel_id="chan_1",
            author_id="user_local",
            author_kind="user",
            body="Hello bot",
        )
    ]
    tools = [
        ToolSpec(
            name="fs_read",
            description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]
    params = Params(temperature=0.2, max_tokens=100)

    yielded_deltas = []
    async for delta in provider.stream(messages=messages, tools=tools, params=params):
        yielded_deltas.append(delta)

    assert len(yielded_deltas) == 5
    assert yielded_deltas[0].text == "Hello "
    assert yielded_deltas[1].text == "Dante!"
    assert yielded_deltas[2].id == "tc_1"
    assert yielded_deltas[3].input == 10
    assert yielded_deltas[4].reason == "stop"

    # Verify recorded calls
    assert len(provider.calls) == 1
    assert provider.last_messages == messages
    assert provider.last_tools == tools
    assert provider.last_params == params


# -- the strict fake ---------------------------------------------------------------
#
# Three of Cerebro's first six silent failures were green against a permissive fake and dead
# against a real model. These pin the shapes a real chat template mishandles without complaining,
# so a test that passes has exercised a conversation a model could actually have understood.

import pytest  # noqa: E402

from cerebro.providers.fake import InvalidConversation, validate_chat_turns  # noqa: E402


async def _drive(provider, messages):
    return [d async for d in provider.stream(messages, [], Params())]


def _sys(body="you are jarvis"):
    return Message(channel_id="c", author_id="system", author_kind="system", kind="system",
                   body=body)


def _user(body="hello"):
    return Message(channel_id="c", author_id="dante", author_kind="user", body=body)


async def test_consecutive_system_turns_are_rejected():
    """This exact shape made Jarvis mute in production while every test stayed green."""
    provider = FakeProvider([Done(reason="stop")])

    with pytest.raises(InvalidConversation, match="two system turns in a row"):
        await _drive(provider, [_sys("identity"), _sys("house rules"), _user()])


async def test_an_empty_assistant_turn_is_rejected_by_fake_provider():
    """FakeProvider must reject empty non-tool assistant turns before lossy mapping."""
    provider = FakeProvider([Done(reason="stop")], self_id="jarvis")
    empty = Message(channel_id="c", author_id="jarvis", author_kind="agent", body="")

    with pytest.raises(InvalidConversation, match="empty assistant turn"):
        await _drive(provider, [_sys(), _user(), empty, _user("still there?")])


def test_the_validator_would_reject_an_empty_assistant_turn():
    """Pinned directly, since the mapper removes it before the validator can see it."""
    with pytest.raises(InvalidConversation, match="empty assistant turn"):
        validate_chat_turns([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "  "},
        ])


async def test_a_tool_result_without_an_id_is_rejected():
    provider = FakeProvider([Done(reason="stop")], self_id="jarvis")
    orphan = Message(channel_id="c", author_id="tool", author_kind="system", kind="tool",
                     body="saved", meta_json=json.dumps({}))

    with pytest.raises(InvalidConversation, match="no tool_call_id"):
        await _drive(provider, [_sys(), _user(), orphan])


async def test_a_valid_tool_round_is_accepted():
    """The positive case: assistant carrying tool_calls, then a tool turn answering it."""
    calls = [{"id": "call_1", "type": "function",
              "function": {"name": "memory_write", "arguments": "{}"}}]
    provider = FakeProvider([TextDelta(text="done"), Done(reason="stop")], self_id="jarvis")

    deltas = await _drive(provider, [
        _sys(),
        _user("remember x"),
        Message(channel_id="c", author_id="jarvis", author_kind="agent", body="",
                meta_json=json.dumps({"tool_calls": calls})),
        Message(channel_id="c", author_id="tool", author_kind="system", kind="tool",
                body="saved as x.md",
                meta_json=json.dumps({"tool_call_id": "call_1", "name": "memory_write"})),
    ])

    assert any(isinstance(d, TextDelta) for d in deltas)
    assert provider.calls, "a valid conversation must reach the provider"


def test_a_tool_result_answering_a_call_nobody_made_is_rejected():
    turns = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "call_ghost", "content": "result"},
    ]
    with pytest.raises(InvalidConversation, match="no preceding assistant turn requested"):
        validate_chat_turns(turns)


def test_an_empty_conversation_is_rejected():
    with pytest.raises(InvalidConversation, match="empty conversation"):
        validate_chat_turns([])
