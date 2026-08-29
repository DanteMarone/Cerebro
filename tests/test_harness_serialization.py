"""Versioned serialization round trips and format-version behaviour."""

import pytest

from cerebro.harness import (
    ArtifactRef,
    CerebroCallId,
    InferenceAttemptId,
    InferenceItemId,
    OmissionMetadata,
    ProviderOpaqueItem,
    TextPart,
    ToolResultItem,
    UnsupportedFormatVersion,
)
from cerebro.harness.serialization import (
    canonical_json,
    dump_attempt,
    dump_item,
    dump_tool_execution,
    load_attempt,
    load_item,
    load_tool_execution,
)
from tests.harness_fixtures import (
    assistant_item,
    attempt,
    tool_call_item,
    tool_key,
    tool_result_item,
    user_item,
)

NOW = "2026-08-29T00:00:00Z"


def _round_trip_item(item):
    return load_item(dump_item(item))


def test_message_item_round_trips():
    item = user_item("hello", sequence_no=0)
    restored = _round_trip_item(item)
    assert restored == item
    assert restored.item_id == item.item_id


def test_tool_call_item_round_trips_with_its_provider_ref():
    item = tool_call_item(InferenceAttemptId.generate(), native_call_id="call_9")
    restored = _round_trip_item(item)
    assert restored == item
    assert restored.provider_ref.native_call_id == "call_9"
    assert restored.provider_ref.replay_required is True
    # Two identities survive the round trip and stay distinct.
    assert str(restored.call_id) != restored.provider_ref.native_call_id


def test_tool_result_item_round_trips_with_omission_metadata():
    call = tool_call_item(InferenceAttemptId.generate())
    item = ToolResultItem(
        item_id=InferenceItemId.generate(),
        call_id=call.call_id,
        tool_key=tool_key(),
        status="success",
        content=[TextPart(text="first 200 bytes")],
        raw_output_ref=ArtifactRef.generate(),
        original_size=1_048_576,
        omission=OmissionMetadata(
            reason="model projection bounded", omitted_bytes=1_048_376, original_size=1_048_576
        ),
    )
    restored = _round_trip_item(item)
    assert restored == item
    assert restored.omission.omitted_bytes == 1_048_376


def test_every_item_variant_round_trips():
    att = InferenceAttemptId.generate()
    call = tool_call_item(att)
    opaque = ProviderOpaqueItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=att,
        provider_id="fake",
        adapter_dialect="fake.dialect",
        kind="thought_signature",
        exact_payload="ZXhhY3QtcGF5bG9hZA==",
        payload_encoding="base64",
        replay_requirement="required_for_correctness",
        retention_scope="conversation",
        sensitivity="signature_or_encrypted_reasoning",
    )
    for item in (user_item("hi"), assistant_item("hello", att), call,
                 tool_result_item(call), opaque):
        assert _round_trip_item(item) == item


def test_opaque_payload_survives_serialization_exactly():
    """Durable form keeps the bytes; only projections redact. A redacted signature is unusable."""
    att = InferenceAttemptId.generate()
    payload = '{"signature":"abc123","nonce":"xyz"}'
    item = ProviderOpaqueItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=att,
        provider_id="fake",
        adapter_dialect="fake.dialect",
        kind="thought_signature",
        exact_payload=payload,
        replay_requirement="required_for_correctness",
        retention_scope="current_turn",
        sensitivity="signature_or_encrypted_reasoning",
    )
    assert load_item(dump_item(item)).exact_payload == payload


def test_attempt_round_trips_through_its_state_machine():
    att = attempt()
    att.mark_dispatch_may_have_escaped(started_at=NOW)
    att.mark_completed("tool_calls_pending", completed_at=NOW, provider_request_id="req-1")
    restored = load_attempt(dump_attempt(att))
    assert restored == att
    assert restored.dispatch_barrier_committed is True
    assert restored.may_have_reached_provider


def test_tool_execution_round_trips_with_uncertainty_metadata():
    from cerebro.harness import (
        AgentTurnId,
        StepSnapshotId,
        ToolBindingGeneration,
        ToolExecution,
        ToolRecoveryCapability,
    )

    execution = ToolExecution(
        call_id=CerebroCallId.generate(),
        agent_turn_id=AgentTurnId.generate(),
        step_snapshot_id=StepSnapshotId.generate(),
        tool_call_item_id=InferenceItemId.generate(),
        tool_key=tool_key("post_message"),
        binding_generation=ToolBindingGeneration.generate(),
        recovery_capability=ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="stable_idempotency_key"
        ),
        admitted_at=NOW,
    )
    execution.assign_stable_operation_key("op-42")
    execution.mark_dispatch_may_have_escaped(at=NOW)
    execution.resolve_indeterminate("executor lost the response", at=NOW)

    restored = load_tool_execution(dump_tool_execution(execution))
    assert restored == execution
    assert restored.stable_operation_key == "op-42"
    assert restored.resolution.resolution_kind == "indeterminate"
    assert restored.is_unresolved_effect


# -- format version behaviour --------------------------------------------------------

def test_a_future_item_format_version_is_refused():
    payload = dump_item(user_item("hello"))
    payload["format_version"] = 2
    with pytest.raises(UnsupportedFormatVersion) as excinfo:
        load_item(payload)
    assert "InferenceItem" in str(excinfo.value)


def test_a_missing_item_format_version_is_refused():
    payload = dump_item(user_item("hello"))
    del payload["format_version"]
    with pytest.raises(UnsupportedFormatVersion):
        load_item(payload)


def test_a_future_attempt_format_version_is_refused():
    payload = dump_attempt(attempt())
    payload["format_version"] = 99
    with pytest.raises(UnsupportedFormatVersion):
        load_attempt(payload)


def test_a_future_tool_execution_format_version_is_refused():
    from cerebro.harness import (
        AgentTurnId,
        StepSnapshotId,
        ToolBindingGeneration,
        ToolExecution,
        ToolRecoveryCapability,
    )

    payload = dump_tool_execution(
        ToolExecution(
            call_id=CerebroCallId.generate(),
            agent_turn_id=AgentTurnId.generate(),
            step_snapshot_id=StepSnapshotId.generate(),
            tool_call_item_id=InferenceItemId.generate(),
            tool_key=tool_key(),
            binding_generation=ToolBindingGeneration.generate(),
            recovery_capability=ToolRecoveryCapability(
                effect_class="read_only", repeat_semantics="idempotent"
            ),
            admitted_at=NOW,
        )
    )
    payload["format_version"] = 7
    with pytest.raises(UnsupportedFormatVersion):
        load_tool_execution(payload)


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
