"""Unit tests for OpenAICompatibleProvider."""

import json
import pytest
import httpx

from cerebro.models import Done, Message, ReasoningDelta, TextDelta, ToolCallDelta, Usage
from cerebro.providers.base import Params, ToolSpec
from cerebro.providers.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderError,
    to_chat_messages,
)


def _sse_event(data: dict | str) -> str:
    payload = json.dumps(data) if isinstance(data, dict) else data
    return f"data: {payload}\n\n"


@pytest.mark.asyncio
async def test_to_chat_messages_attribution():
    messages = [
        Message(channel_id="c1", author_id="dante", author_kind="user", body="hello"),
        Message(channel_id="c1", author_id="jarvis", author_kind="agent", body="hi"),
        Message(channel_id="c1", author_id="claude", author_kind="agent", body="welcome"),
    ]
    # For jarvis: jarvis is assistant, dante is user, claude is user prefixed with 'claude:'
    chat_turns = to_chat_messages(messages, "jarvis")
    assert chat_turns == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "claude: welcome"},
    ]


@pytest.mark.asyncio
async def test_openai_compatible_stream_text_and_usage():
    usage_data = {"prompt_tokens": 10, "completion_tokens": 5}
    sse_body = (
        _sse_event({"choices": [{"delta": {"content": "Hello "}}]}) +
        _sse_event({"choices": [{"delta": {"content": "world!"}}]}) +
        _sse_event({"choices": [{"finish_reason": "stop"}], "usage": usage_data}) +
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer secret-key"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, text=sse_body)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    provider = OpenAICompatibleProvider(
        self_id="test_agent",
        model="gpt-4o",
        base_url="https://api.openai.com/v1",
        api_key="secret-key",
        client=client,
    )

    deltas = []
    async for delta in provider.stream(
        messages=[Message(channel_id="c1", author_id="dante", author_kind="user", body="test")],
        tools=[],
        params=Params(),
    ):
        deltas.append(delta)

    assert deltas == [
        TextDelta(text="Hello "),
        TextDelta(text="world!"),
        Usage(input=10, output=5),
        Done(reason="stop"),
    ]


@pytest.mark.asyncio
async def test_openai_compatible_reasoning_and_tools():
    sse_body = (
        _sse_event({"choices": [{"delta": {"reasoning": "Thinking step..."}}]}) +
        _sse_event({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_abc",
                        "function": {"name": "read_file", "arguments": '{"path":'},
                    }]
                }
            }]
        }) +
        _sse_event({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": ' "foo.txt"}'},
                    }]
                }
            }]
        }) +
        _sse_event({"choices": [{"finish_reason": "tool_calls"}]}) +
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse_body)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    provider = OpenAICompatibleProvider(
        self_id="test_agent",
        model="deepseek-r1",
        base_url="https://api.deepseek.com/v1",
        api_key="ds-key",
        client=client,
    )

    tools = [ToolSpec(name="read_file", description="reads a file", parameters={})]
    msg = Message(channel_id="c1", author_id="dante", author_kind="user", body="check file")
    deltas = []
    async for delta in provider.stream(
        messages=[msg],
        tools=tools,
        params=Params(),
    ):
        deltas.append(delta)

    assert deltas == [
        ReasoningDelta(text="Thinking step..."),
        ToolCallDelta(id="call_abc", name="read_file", args_fragment='{"path":'),
        ToolCallDelta(id="call_abc", name="read_file", args_fragment=' "foo.txt"}'),
        Done(reason="tool_calls"),
    ]


@pytest.mark.asyncio
async def test_openai_compatible_openrouter_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("HTTP-Referer") == "http://127.0.0.1:8765"
        assert request.headers.get("X-Title") == "Cerebro"
        assert request.headers.get("Authorization") == "Bearer or-key"
        return httpx.Response(200, json={"data": [{"id": "meta-llama/llama-3-70b"}]})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    provider = OpenAICompatibleProvider(
        self_id="or_agent",
        base_url="https://openrouter.ai/api/v1",
        api_key="or-key",
        client=client,
    )

    resolved = await provider.resolve_model()
    assert resolved == "meta-llama/llama-3-70b"


@pytest.mark.asyncio
async def test_openai_compatible_error_handling():
    def handler_400(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Invalid model requested")

    transport = httpx.MockTransport(handler_400)
    client = httpx.AsyncClient(transport=transport)

    provider = OpenAICompatibleProvider(
        self_id="test_agent",
        model="invalid-model",
        base_url="https://api.openai.com/v1",
        client=client,
    )

    with pytest.raises(ProviderError, match="returned 400: Invalid model"):
        async for _ in provider.stream(
            messages=[Message(channel_id="c1", author_id="dante", author_kind="user", body="hi")],
            tools=[],
            params=Params(),
        ):
            pass
