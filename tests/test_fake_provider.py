"""Tests for FakeProvider."""

import pytest
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
