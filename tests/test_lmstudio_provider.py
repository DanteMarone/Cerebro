"""LM Studio provider: SSE parsing, tool-call fragment reassembly, and speaker attribution.

No test here touches the network — every request is served by an httpx MockTransport.
"""

import httpx
import pytest

from cerebro.models import Done, Message, TextDelta, ToolCallDelta, Usage
from cerebro.providers.base import Params, ToolSpec
from cerebro.providers.lmstudio import (
    LMStudioProvider,
    ProviderError,
    ProviderUnavailable,
    to_chat_messages,
)


def sse(*chunks: str) -> bytes:
    return "".join(f"data: {c}\n\n" for c in chunks).encode()


def msg(author_id, kind="agent", body="hello"):
    return Message(channel_id="c1", author_id=author_id, author_kind=kind, body=body)


def provider_with(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LMStudioProvider(self_id="jarvis", model="m", client=client, **kwargs)


async def collect(provider, messages=None, tools=None):
    return [
        d async for d in provider.stream(
            messages or [msg("dante", "user")], tools or [], Params()
        )
    ]


async def test_text_deltas_stream_through():
    def handler(request):
        return httpx.Response(200, content=sse(
            '{"choices":[{"delta":{"content":"Hel"}}]}',
            '{"choices":[{"delta":{"content":"lo"}}]}',
            '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "[DONE]",
        ))

    deltas = await collect(provider_with(handler))
    assert [d.text for d in deltas if isinstance(d, TextDelta)] == ["Hel", "lo"]
    assert deltas[-1] == Done(reason="stop")


async def test_tool_call_fragments_keep_their_identity():
    """The id and name arrive once; the arguments dribble in and must stay attributable."""
    def handler(request):
        return httpx.Response(200, content=sse(
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a",'
            '"function":{"name":"fs_read","arguments":"{\\"pa"}}]}}]}',
            '{"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"th\\": \\"x\\"}"}}]}}]}',
            '{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
            "[DONE]",
        ))

    deltas = await collect(provider_with(handler))
    calls = [d for d in deltas if isinstance(d, ToolCallDelta)]
    assert [c.id for c in calls] == ["call_a", "call_a"]
    assert [c.name for c in calls] == ["fs_read", "fs_read"]
    assert "".join(c.args_fragment for c in calls) == '{"path": "x"}'
    assert deltas[-1].reason == "tool_calls"


async def test_usage_is_reported():
    def handler(request):
        return httpx.Response(200, content=sse(
            '{"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":34}}',
            "[DONE]",
        ))

    usage = [d for d in await collect(provider_with(handler)) if isinstance(d, Usage)]
    assert usage == [Usage(input=12, output=34)]


async def test_malformed_frame_does_not_kill_the_turn():
    def handler(request):
        return httpx.Response(200, content=sse(
            "{not json at all",
            '{"choices":[{"delta":{"content":"still here"}}]}',
            "[DONE]",
        ))

    texts = [d.text for d in await collect(provider_with(handler)) if isinstance(d, TextDelta)]
    assert texts == ["still here"]


async def test_http_error_becomes_a_provider_error():
    def handler(request):
        return httpx.Response(500, content=b"model exploded")

    with pytest.raises(ProviderError, match="500"):
        await collect(provider_with(handler))


async def test_connection_refused_is_distinguishable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderUnavailable, match="not reachable"):
        await collect(provider_with(handler))


async def test_tools_are_sent_in_openai_shape():
    seen = {}

    def handler(request):
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=sse("[DONE]"))

    tool = ToolSpec(name="fs_read", description="read a file",
                    parameters={"type": "object", "properties": {}})
    await collect(provider_with(handler), tools=[tool])

    assert seen["tools"][0]["type"] == "function"
    assert seen["tools"][0]["function"]["name"] == "fs_read"
    assert seen["stream_options"] == {"include_usage": True}


async def test_unconfigured_model_resolves_to_a_loaded_chat_model():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [
                {"id": "text-embedding-nomic-embed-text-v1.5"},
                {"id": "google/gemma-4-12b-qat"},
            ]})
        return httpx.Response(200, content=sse("[DONE]"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LMStudioProvider(self_id="jarvis", model=None, client=client)

    assert await provider.resolve_model() == "google/gemma-4-12b-qat"


async def test_only_embeddings_loaded_is_reported_clearly():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "nomic-embed-text"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LMStudioProvider(self_id="jarvis", model=None, client=client)

    with pytest.raises(ProviderUnavailable, match="no chat model"):
        await provider.resolve_model()


def test_only_my_own_messages_are_assistant_turns():
    """A peer's message presented as `assistant` makes a model believe it said things it did not."""
    turns = to_chat_messages(
        [
            msg("system", "system", "you are jarvis"),
            msg("dante", "user", "what do you think?"),
            msg("jarvis", "agent", "I think yes"),
            msg("forge", "agent", "I think no"),
        ],
        self_id="jarvis",
    )

    assert [t["role"] for t in turns] == ["system", "user", "assistant", "user"]
    assert turns[2]["content"] == "I think yes"
    # A peer's turn is attributed, otherwise the model cannot tell who is arguing with it.
    assert turns[3]["content"] == "forge: I think no"


def test_a_tool_round_is_mapped_to_the_protocol_shape():
    """Codex refuted the first version: an empty assistant turn plus a system message.

    The API requires an assistant turn carrying tool_calls, then a tool turn per call carrying the
    matching tool_call_id. A model is not obliged to make sense of anything else.
    """
    import json as _json

    calls = [{"id": "call_1", "type": "function",
              "function": {"name": "memory_write", "arguments": '{"name":"x"}'}}]
    turns = to_chat_messages(
        [
            Message(channel_id="c", author_id="dante", author_kind="user", body="remember x"),
            Message(channel_id="c", author_id="jarvis", author_kind="agent", kind="chat", body="",
                    meta_json=_json.dumps({"tool_calls": calls})),
            Message(channel_id="c", author_id="tool", author_kind="system", kind="tool",
                    body="saved as x.md",
                    meta_json=_json.dumps({"tool_call_id": "call_1", "name": "memory_write"})),
        ],
        self_id="jarvis",
    )

    assert turns[1]["role"] == "assistant"
    assert turns[1]["tool_calls"] == calls
    assert turns[1]["content"] is None, "an empty tool-call turn must not send an empty string"

    assert turns[2]["role"] == "tool"
    assert turns[2]["tool_call_id"] == "call_1"
    assert turns[2]["content"] == "saved as x.md"

    assert not any(t["role"] == "system" and "returned" in str(t.get("content")) for t in turns)


def test_an_empty_assistant_turn_with_no_tool_calls_is_dropped():
    """It says nothing, and consecutive/empty turns are what silently break chat templates."""
    turns = to_chat_messages(
        [
            Message(channel_id="c", author_id="dante", author_kind="user", body="hello"),
            Message(channel_id="c", author_id="jarvis", author_kind="agent", body="   "),
        ],
        self_id="jarvis",
    )

    assert [t["role"] for t in turns] == ["user"]
