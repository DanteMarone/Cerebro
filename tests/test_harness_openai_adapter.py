"""The OpenAI-compatible / LM Studio `ProviderAdapter` boundary.

Two directions are checked: canonical items rendered onto the chat-completions wire, and a
streamed response turned back into canonical events with finalized items. Both prove the same
thing — the OpenAI shapes stop at this boundary.
"""

import httpx
import pytest

from cerebro.harness import (
    InferenceAttemptId,
    InferenceItemId,
    InferenceRequest,
    Instruction,
    ModelProfileId,
    ProviderConfigId,
    ProviderOpaqueItem,
    Provenance,
    StepSnapshotId,
    TextPart,
    ToolPolicy,
    UnknownDialect,
    UnsupportedDialectFeature,
)
from cerebro.harness.adapters import (
    OPENAI_CHAT_DIALECT,
    OpenAICompatibleAdapter,
    adapter_factory_for_dialect,
    supported_dialects,
)
from cerebro.harness.adapters.openai_dialect import (
    OpenAIDialectOptions,
    is_unresolved_tool_key,
    to_wire_messages,
)
from cerebro.harness.events import (
    AssistantTextDelta,
    InferenceCompleted,
    InferenceStarted,
    OutputItemCompleted,
    ReasoningSummaryDelta,
    ToolCallInputDelta,
    UsageUpdate,
)
from cerebro.harness.items import MessageItem, ReasoningSummaryItem, ToolCallItem
from cerebro.models import Done, ReasoningDelta, TextDelta, ToolCallDelta, Usage
from cerebro.providers.openai_compatible import ProviderError, ProviderUnavailable
from tests.harness_fixtures import (
    FakeTransport,
    assistant_item,
    mcp_tool_key,
    model_profile,
    provider_config,
    tool_call_item,
    tool_definition,
    tool_key,
    tool_result_item,
    user_item,
)


def _request(**overrides) -> InferenceRequest:
    payload = {
        "step_snapshot_id": StepSnapshotId.generate(),
        "provider_config_ref": ProviderConfigId.generate(),
        "model_profile_ref": ModelProfileId.generate(),
        "provider_options": {"model": "gpt-oss-20b"},
    }
    payload.update(overrides)
    return InferenceRequest(**payload)


def _system(text: str) -> Instruction:
    return Instruction(
        authority="system",
        content=[TextPart(text=text)],
        provenance=Provenance(source_kind="agent_prompt"),
    )


# -- canonical -> wire ---------------------------------------------------------------

def test_a_plain_exchange_maps_onto_chat_turns():
    att = InferenceAttemptId.generate()
    wire = to_wire_messages(
        [_system("You are Jarvis.")],
        [user_item("hello"), assistant_item("hi there", att)],
    )
    assert wire == [
        {"role": "system", "content": "You are Jarvis."},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_a_tool_round_renders_the_shape_the_protocol_requires():
    """One assistant turn carrying tool_calls, then one tool turn per call. F-02."""
    att = InferenceAttemptId.generate()
    text = assistant_item("Let me look.", att)
    call = tool_call_item(att, native_call_id="call_1", args={"path": "notes.md"})
    result = tool_result_item(call, "hello from notes")

    wire = to_wire_messages([], [user_item("read notes.md"), text, call, result])

    assert wire == [
        {"role": "user", "content": "read notes.md"},
        {
            "role": "assistant",
            "content": "Let me look.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "fs_read", "arguments": '{"path":"notes.md"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "hello from notes"},
    ]


def test_multiple_calls_from_one_attempt_share_one_assistant_turn():
    att = InferenceAttemptId.generate()
    first = tool_call_item(att, native_call_id="call_1")
    second = tool_call_item(att, native_call_id="call_2", key=mcp_tool_key())

    wire = to_wire_messages([], [assistant_item("", att), first, second])

    assert len(wire) == 1
    assert wire[0]["role"] == "assistant"
    assert wire[0]["content"] is None
    assert [c["id"] for c in wire[0]["tool_calls"]] == ["call_1", "call_2"]
    assert wire[0]["tool_calls"][1]["function"]["name"] == "filesystem__read_file"


def test_calls_from_different_attempts_do_not_merge():
    att_a = InferenceAttemptId.generate()
    att_b = InferenceAttemptId.generate()
    wire = to_wire_messages(
        [],
        [
            tool_call_item(att_a, native_call_id="call_1"),
            tool_call_item(att_b, native_call_id="call_2"),
        ],
    )
    assert len(wire) == 2
    assert [w["tool_calls"][0]["id"] for w in wire] == ["call_1", "call_2"]


def test_an_empty_assistant_turn_with_nothing_attached_is_dropped():
    att = InferenceAttemptId.generate()
    assert to_wire_messages([], [assistant_item("   ", att)]) == []


def test_reasoning_summaries_are_not_put_on_the_wire():
    """Chat completions never requires a summary back; sending it would be invention."""
    att = InferenceAttemptId.generate()
    summary = ReasoningSummaryItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=att,
        content=[TextPart(text="thinking out loud")],
        provenance=Provenance(source_kind="provider_reasoning_summary"),
    )
    assert to_wire_messages([], [summary, assistant_item("done", att)]) == [
        {"role": "assistant", "content": "done"}
    ]


def test_developer_authority_falls_back_to_system_explicitly():
    developer = Instruction(
        authority="developer",
        content=[TextPart(text="be terse")],
        provenance=Provenance(source_kind="policy"),
    )
    assert to_wire_messages([developer], [])[0]["role"] == "system"
    assert (
        to_wire_messages(
            [developer], [], options=OpenAIDialectOptions(supports_developer_role=True)
        )[0]["role"]
        == "developer"
    )


def test_a_configured_refusal_of_the_developer_fallback_fails_loudly():
    developer = Instruction(
        authority="developer",
        content=[TextPart(text="be terse")],
        provenance=Provenance(source_kind="policy"),
    )
    with pytest.raises(UnsupportedDialectFeature):
        to_wire_messages(
            [developer], [], options=OpenAIDialectOptions(developer_instruction_fallback="reject")
        )


# -- explicit refusals ---------------------------------------------------------------

def test_provider_opaque_replay_material_is_refused_by_this_dialect():
    att = InferenceAttemptId.generate()
    opaque = ProviderOpaqueItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=att,
        provider_id="anthropic",
        adapter_dialect="anthropic.messages",
        kind="thinking_signature",
        exact_payload="sig",
        replay_requirement="required_for_correctness",
        retention_scope="current_turn",
        sensitivity="signature_or_encrypted_reasoning",
    )
    with pytest.raises(UnsupportedDialectFeature) as excinfo:
        to_wire_messages([], [opaque])
    assert "replay" in str(excinfo.value)


def test_a_tool_call_without_a_provider_ref_cannot_borrow_the_cerebro_call_id():
    att = InferenceAttemptId.generate()
    orphan = tool_call_item(att).model_copy(update={"provider_ref": None})
    with pytest.raises(UnsupportedDialectFeature) as excinfo:
        to_wire_messages([], [orphan])
    assert "CerebroCallId is not a substitute" in str(excinfo.value)


def test_non_text_content_is_refused_rather_than_stringified():
    from cerebro.harness import JsonPart

    att = InferenceAttemptId.generate()
    item = MessageItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=att,
        role="assistant",
        content=[JsonPart(value={"a": 1})],
        provenance=Provenance(source_kind="provider_attempt"),
    )
    with pytest.raises(UnsupportedDialectFeature):
        to_wire_messages([], [item])


def test_an_unregistered_dialect_fails_explicitly():
    with pytest.raises(UnknownDialect) as excinfo:
        adapter_factory_for_dialect("anthropic.messages")
    assert "anthropic.messages" in str(excinfo.value)
    assert supported_dialects() == [OPENAI_CHAT_DIALECT]
    assert adapter_factory_for_dialect(OPENAI_CHAT_DIALECT) is OpenAICompatibleAdapter


def test_a_config_for_another_dialect_is_refused_at_prepare():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    with pytest.raises(UnsupportedDialectFeature):
        adapter.prepare(
            _request(),
            provider_config(dialect_id="gemini.interactions"),
            attempt_id=InferenceAttemptId.generate(),
        )


def test_parallel_tool_calls_are_refused_in_phase_1():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    request = _request(
        tools=[tool_definition()], tool_policy=ToolPolicy(allow_parallel_calls=True)
    )
    with pytest.raises(UnsupportedDialectFeature):
        adapter.prepare(
            request, provider_config(), attempt_id=InferenceAttemptId.generate()
        )


# -- prepare -------------------------------------------------------------------------

def test_prepare_builds_the_current_payload_shape():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    attempt_id = InferenceAttemptId.generate()
    request = _request(
        instructions=[_system("You are Jarvis.")],
        history=[user_item("hello", sequence_no=0)],
        tools=[tool_definition()],
    )
    prepared = adapter.prepare(request, provider_config(), attempt_id=attempt_id)

    assert prepared.attempt_id == attempt_id
    assert prepared.dialect_id == OPENAI_CHAT_DIALECT
    assert prepared.payload["model"] == "gpt-oss-20b"
    assert prepared.payload["stream"] is True
    assert prepared.payload["stream_options"] == {"include_usage": True}
    assert prepared.payload["tools"][0]["function"]["name"] == "fs_read"
    assert prepared.wire_tool_names == {"fs_read": tool_key().canonical()}
    assert len(prepared.request_semantic_hash) == 64


def test_prepare_requires_an_explicit_model():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    with pytest.raises(UnsupportedDialectFeature):
        adapter.prepare(
            _request(provider_options={}),
            provider_config(),
            attempt_id=InferenceAttemptId.generate(),
        )


def test_prepare_records_replayed_provider_refs_without_conflating_identities():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    att = InferenceAttemptId.generate()
    call = tool_call_item(att, native_call_id="call_7")
    prepared = adapter.prepare(
        _request(history=[call, tool_result_item(call)]),
        provider_config(),
        attempt_id=InferenceAttemptId.generate(),
    )
    assert prepared.replayed_call_refs == {"call_7": str(call.call_id)}
    assert "call_7" != str(call.call_id)


# -- wire -> canonical ---------------------------------------------------------------

async def _events(adapter, prepared, **kwargs):
    return [event async for event in adapter.stream(prepared, **kwargs)]


async def test_a_text_response_finalizes_one_assistant_item():
    transport = FakeTransport(
        [TextDelta(text="Hel"), TextDelta(text="lo."), Usage(input=10, output=3),
         Done(reason="stop")]
    )
    adapter = OpenAICompatibleAdapter(transport)
    attempt_id = InferenceAttemptId.generate()
    prepared = adapter.prepare(_request(), provider_config(), attempt_id=attempt_id)

    events = await _events(adapter, prepared)

    assert isinstance(events[0], InferenceStarted)
    assert [e.text for e in events if isinstance(e, AssistantTextDelta)] == ["Hel", "lo."]
    assert [(e.input_tokens, e.output_tokens) for e in events if isinstance(e, UsageUpdate)] == [
        (10, 3)
    ]
    finalized = [e.item for e in events if isinstance(e, OutputItemCompleted)]
    assert len(finalized) == 1
    assert isinstance(finalized[0], MessageItem)
    assert finalized[0].content[0].text == "Hello."
    assert finalized[0].producing_attempt_id == attempt_id
    assert finalized[0].origin == "provider_attempt"
    assert events[-1].status == "end_turn"


async def test_a_tool_call_finalizes_with_two_distinct_identities():
    transport = FakeTransport(
        [
            ToolCallDelta(id="call_1", name="fs_read", args_fragment='{"path":'),
            ToolCallDelta(id="call_1", name="", args_fragment='"notes.md"}'),
            Done(reason="tool_calls"),
        ]
    )
    adapter = OpenAICompatibleAdapter(transport)
    attempt_id = InferenceAttemptId.generate()
    prepared = adapter.prepare(
        _request(tools=[tool_definition()]), provider_config(), attempt_id=attempt_id
    )

    events = await _events(adapter, prepared)

    fragments = [e for e in events if isinstance(e, ToolCallInputDelta)]
    assert [f.arguments_fragment for f in fragments] == ['{"path":', '"notes.md"}']

    calls = [
        e.item for e in events
        if isinstance(e, OutputItemCompleted) and isinstance(e.item, ToolCallItem)
    ]
    assert len(calls) == 1
    call = calls[0]
    assert call.provider_ref.native_call_id == "call_1"
    assert call.provider_ref.replay_required is True
    assert str(call.call_id).startswith("ccall_")
    assert str(call.call_id) != "call_1"
    assert call.tool_key == tool_key()
    assert call.input.value == {"path": "notes.md"}
    assert call.producing_attempt_id == attempt_id
    assert events[-1].status == "tool_calls_pending"


async def test_deltas_are_never_finalized_items():
    """A complete-looking argument fragment is still only a fragment until the stream ends."""
    transport = FakeTransport(
        [ToolCallDelta(id="call_1", name="fs_read", args_fragment='{"path":"notes.md"}')]
    )
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(tools=[tool_definition()]),
        provider_config(),
        attempt_id=InferenceAttemptId.generate(),
    )

    events = await _events(adapter, prepared)
    completed_before_end = [
        e for e in events[: events.index(next(e for e in events if isinstance(e, OutputItemCompleted)))]
        if isinstance(e, OutputItemCompleted)
    ]
    assert completed_before_end == []
    assert isinstance(events[-1], InferenceCompleted)


async def test_a_stop_reason_alongside_tool_calls_still_reports_pending_calls():
    transport = FakeTransport(
        [
            ToolCallDelta(id="call_1", name="fs_read", args_fragment="{}"),
            Done(reason="stop"),
        ]
    )
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(tools=[tool_definition()]),
        provider_config(),
        attempt_id=InferenceAttemptId.generate(),
    )
    events = await _events(adapter, prepared)
    assert events[-1].status == "tool_calls_pending"


async def test_malformed_arguments_stay_representable_as_text():
    transport = FakeTransport(
        [
            ToolCallDelta(id="call_1", name="fs_read", args_fragment="{not json"),
            Done(reason="tool_calls"),
        ]
    )
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(tools=[tool_definition()]),
        provider_config(),
        attempt_id=InferenceAttemptId.generate(),
    )
    call = next(
        e.item for e in await _events(adapter, prepared)
        if isinstance(e, OutputItemCompleted) and isinstance(e.item, ToolCallItem)
    )
    assert call.input.input_form == "text"
    assert call.input.text == "{not json"


async def test_a_tool_name_outside_the_plan_resolves_to_an_unresolved_key():
    transport = FakeTransport(
        [
            ToolCallDelta(id="call_1", name="launch_missiles", args_fragment="{}"),
            Done(reason="tool_calls"),
        ]
    )
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(tools=[tool_definition()]),
        provider_config(),
        attempt_id=InferenceAttemptId.generate(),
    )
    call = next(
        e.item for e in await _events(adapter, prepared)
        if isinstance(e, OutputItemCompleted) and isinstance(e.item, ToolCallItem)
    )
    assert is_unresolved_tool_key(call.tool_key)
    assert call.tool_key.name == "launch_missiles"


async def test_reasoning_is_streamed_but_not_finalized_by_default():
    """Current behaviour: reasoning is private and never re-enters the request."""
    transport = FakeTransport([ReasoningDelta(text="hmm"), TextDelta(text="ok"),
                               Done(reason="stop")])
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(), provider_config(), attempt_id=InferenceAttemptId.generate()
    )
    events = await _events(adapter, prepared)
    assert [e.summary_fragment for e in events if isinstance(e, ReasoningSummaryDelta)] == ["hmm"]
    assert not any(isinstance(e.item, ReasoningSummaryItem) for e in events
                   if isinstance(e, OutputItemCompleted))


async def test_reasoning_can_be_finalized_when_a_profile_asks_for_a_summary():
    transport = FakeTransport([ReasoningDelta(text="hmm"), Done(reason="stop")])
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(), provider_config(), attempt_id=InferenceAttemptId.generate()
    )
    events = await _events(adapter, prepared, emit_reasoning_summary=True)
    summaries = [e.item for e in events if isinstance(e, OutputItemCompleted)]
    assert len(summaries) == 1
    assert isinstance(summaries[0], ReasoningSummaryItem)


async def test_the_prepared_payload_is_what_reaches_the_transport():
    transport = FakeTransport([Done(reason="stop")])
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(history=[user_item("hello", sequence_no=0)]),
        provider_config(),
        attempt_id=InferenceAttemptId.generate(),
    )
    await _events(adapter, prepared)
    assert transport.payloads == [prepared.payload]
    assert transport.payloads[0]["messages"] == [{"role": "user", "content": "hello"}]


# -- error classification ------------------------------------------------------------

def test_error_classification_separates_kind_from_transport_retryability():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))

    rate_limited = ProviderError("lmstudio returned 429: slow down")
    rate_limited.status_code = 429
    classified = adapter.classify_error(rate_limited)
    assert classified.kind == "rate_limited"
    assert classified.transport_retryable is True

    unauthorized = ProviderError("lmstudio returned 401: nope")
    unauthorized.status_code = 401
    classified = adapter.classify_error(unauthorized)
    assert classified.kind == "authentication"
    assert classified.transport_retryable is False


def test_unreachable_backend_classifies_as_transient_transport():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    classified = adapter.classify_error(ProviderUnavailable("not reachable"))
    assert classified.kind == "transient_transport"
    assert classified.transport_retryable is True


def test_a_stream_that_dies_without_a_status_is_transport_trouble():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    classified = adapter.classify_error(ProviderError("lmstudio stopped responding after 300s."))
    assert classified.kind == "transient_transport"
    assert classified.transport_retryable is True


def test_an_unexpected_exception_is_fatal_internal_rather_than_retryable():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    classified = adapter.classify_error(ZeroDivisionError("boom"))
    assert classified.kind == "fatal_internal"
    assert classified.transport_retryable is False


def test_http_status_errors_map_through_the_same_table():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    request = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
    response = httpx.Response(503, request=request)
    classified = adapter.classify_error(
        httpx.HTTPStatusError("overloaded", request=request, response=response)
    )
    assert classified.kind == "provider_overloaded"
    assert classified.transport_retryable is True


# -- capabilities and AR-12 declaration ----------------------------------------------

def test_this_dialect_declares_that_it_emits_no_sensitive_replay_material():
    """AR-12: PR 1 states whether it can create sensitive replay payloads. It cannot."""
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    capabilities = adapter.resolve_capabilities(model_profile())
    assert adapter.emits_sensitive_replay_material is False
    assert capabilities.emits_opaque_replay_items is False
    assert capabilities.emits_sensitive_replay_material is False


async def test_the_adapter_never_emits_an_opaque_item():
    transport = FakeTransport(
        [
            ReasoningDelta(text="private thought"),
            TextDelta(text="answer"),
            ToolCallDelta(id="call_1", name="fs_read", args_fragment="{}"),
            Done(reason="tool_calls"),
        ]
    )
    adapter = OpenAICompatibleAdapter(transport)
    prepared = adapter.prepare(
        _request(tools=[tool_definition()]),
        provider_config(),
        attempt_id=InferenceAttemptId.generate(),
    )
    events = await _events(adapter, prepared, emit_reasoning_summary=True)
    assert not any(
        isinstance(e, OutputItemCompleted) and isinstance(e.item, ProviderOpaqueItem)
        for e in events
    )


async def test_close_releases_the_transport():
    transport = FakeTransport([])
    await OpenAICompatibleAdapter(transport).close()
    assert transport.closed
