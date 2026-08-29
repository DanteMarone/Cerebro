"""Canonical Harness v1 contract invariants.

These are the properties the later persistence and reducer PRs will build on, so each test
states one invariant rather than exercising a workflow.
"""

import pytest
from pydantic import ValidationError

from cerebro.harness import (
    AgentTurn,
    AgentTurnId,
    ArtifactRef,
    CausalWakeKey,
    CerebroCallId,
    ContinuationNotAdmissible,
    ConversationTurnId,
    HarnessStateError,
    INFERENCE_ATTEMPT_FORMAT_VERSION,
    INFERENCE_ITEM_FORMAT_VERSION,
    InferenceAttemptId,
    InferenceError,
    InferenceHistory,
    InferenceItemId,
    InferenceRequest,
    InvalidHarnessId,
    MessageItem,
    ModelProfileId,
    ProviderCallRef,
    ProviderConfigId,
    ProviderOpaqueItem,
    Provenance,
    StepSnapshotId,
    TOOL_EXECUTION_FORMAT_VERSION,
    TextPart,
    ToolBindingGeneration,
    ToolExecution,
    ToolKey,
    ToolRecoveryCapability,
    ToolResultItem,
    assert_continuation_admissible,
    classify_recovery,
    provider_action_for,
    request_semantic_hash,
)
from cerebro.harness.adapters.openai_compatible import OpenAICompatibleAdapter
from tests.harness_fixtures import (
    FakeTransport,
    assistant_item,
    attempt,
    model_profile,
    tool_call_item,
    tool_key,
    tool_result_item,
    user_item,
)

NOW = "2026-08-29T00:00:00Z"


# -- identity invariants -------------------------------------------------------------

def test_identities_carry_their_family_prefix():
    turn_id = AgentTurnId.generate()
    assert turn_id.startswith("atn_")
    assert AgentTurnId(str(turn_id)) == turn_id


def test_provider_tool_call_id_cannot_become_a_cerebro_call_id():
    """The whole point of two identities: a provider id is not admissible as Cerebro's."""
    with pytest.raises(InvalidHarnessId):
        CerebroCallId("call_abc123")


def test_one_identity_family_cannot_be_reused_as_another():
    snapshot_id = StepSnapshotId.generate()
    with pytest.raises(InvalidHarnessId):
        InferenceItemId(snapshot_id)


def test_identity_body_must_not_be_empty():
    with pytest.raises(InvalidHarnessId):
        ArtifactRef("artf_")


def test_provider_call_ref_needs_a_handle():
    with pytest.raises(ValidationError):
        ProviderCallRef(provider_id="lmstudio")


# -- item envelope invariants --------------------------------------------------------

def test_every_item_family_carries_its_own_format_version():
    att = InferenceAttemptId.generate()
    call = tool_call_item(att)
    assert call.format_version == INFERENCE_ITEM_FORMAT_VERSION
    assert tool_result_item(call).format_version == INFERENCE_ITEM_FORMAT_VERSION
    assert attempt().format_version == INFERENCE_ATTEMPT_FORMAT_VERSION


def test_provider_originated_item_requires_producing_attempt_identity():
    with pytest.raises(ValidationError):
        MessageItem(
            item_id=InferenceItemId.generate(),
            origin="provider_attempt",
            role="assistant",
            content=[TextPart(text="hello")],
            provenance=Provenance(source_kind="provider_attempt"),
        )


def test_projected_item_must_not_claim_a_producing_attempt():
    with pytest.raises(ValidationError):
        MessageItem(
            item_id=InferenceItemId.generate(),
            origin="context_projection",
            producing_attempt_id=InferenceAttemptId.generate(),
            role="user",
            content=[TextPart(text="hello")],
            provenance=Provenance(source_kind="collaboration_message"),
        )


def test_tool_result_is_never_provider_originated():
    """A tool result is Cerebro's own evidence; claiming a provider produced it is a lie."""
    call = tool_call_item(InferenceAttemptId.generate())
    payload = tool_result_item(call).model_dump(mode="json")
    payload["origin"] = "provider_attempt"
    payload["producing_attempt_id"] = str(InferenceAttemptId.generate())
    with pytest.raises(ValidationError):
        ToolResultItem.model_validate(payload)


def test_opaque_item_must_come_from_a_provider_attempt():
    with pytest.raises(ValidationError):
        ProviderOpaqueItem(
            item_id=InferenceItemId.generate(),
            origin="harness_local",
            provider_id="anthropic",
            adapter_dialect="anthropic.messages",
            kind="thinking_signature",
            exact_payload="sig",
            replay_requirement="required_for_correctness",
            retention_scope="current_turn",
        )


# -- ordered history -----------------------------------------------------------------

def test_mixed_history_keeps_canonical_order():
    att = InferenceAttemptId.generate()
    history = InferenceHistory(ConversationTurnId.generate())
    first = history.append(user_item("read notes.md"))
    text = history.append(assistant_item("Reading it now.", att))
    call = history.append(tool_call_item(att))
    result = history.append(tool_result_item(call))
    final = history.append(assistant_item("It says hello.", att))

    ordered = [item.item_id for item in history.canonical_request_history()]
    assert ordered == [first.item_id, text.item_id, call.item_id, result.item_id, final.item_id]
    assert [item.sequence_no for item in history.canonical_request_history()] == [0, 1, 2, 3, 4]
    assert history.version == 5


def test_history_refuses_a_backwards_sequence_number():
    history = InferenceHistory(ConversationTurnId.generate())
    history.append(user_item("first"))
    history.append(user_item("second"))
    with pytest.raises(HarnessStateError):
        history.append(user_item("stale", sequence_no=0))


# -- AR-02 supersession --------------------------------------------------------------

def test_abandoned_attempt_output_is_superseded_not_deleted():
    """Interrupted output that authorised nothing leaves the next request but stays as evidence."""
    att_a = InferenceAttemptId.generate()
    att_b = InferenceAttemptId.generate()
    history = InferenceHistory(ConversationTurnId.generate())
    projected = history.append(user_item("hello"))
    partial = history.append(assistant_item("I was half way through", att_a))

    superseded = history.supersede_abandoned_attempt(
        att_a, reason="attempt abandoned without completion", at=NOW,
        superseding_attempt_id=att_b,
    )

    assert [item.item_id for item in superseded] == [partial.item_id]
    assert [item.item_id for item in history.canonical_request_history()] == [projected.item_id]
    audit = {item.item_id: item for item in history.audit_history()}
    assert audit[partial.item_id].is_superseded
    assert audit[partial.item_id].superseding_attempt_id == att_b
    assert len(history.audit_history()) == 2


def test_supersession_never_crosses_a_dispatched_effect():
    """Committed effect history stays canonical; only trailing unprotected output is dropped."""
    att_a = InferenceAttemptId.generate()
    history = InferenceHistory(ConversationTurnId.generate())
    preamble = history.append(assistant_item("Calling the tool.", att_a))
    call = history.append(tool_call_item(att_a, native_call_id="call_1"))
    result = history.append(tool_result_item(call))
    trailing = history.append(assistant_item("half-finished follow up", att_a))

    superseded = history.supersede_abandoned_attempt(
        att_a, reason="provider stream died", at=NOW, protected_call_ids=[call.call_id],
    )

    assert [item.item_id for item in superseded] == [trailing.item_id]
    surviving = [item.item_id for item in history.canonical_request_history()]
    assert surviving == [preamble.item_id, call.item_id, result.item_id]


def test_committed_tool_results_are_never_superseded():
    """A ToolResultItem is harness-local, so no provider abandonment can take it away."""
    att = InferenceAttemptId.generate()
    history = InferenceHistory(ConversationTurnId.generate())
    call = history.append(tool_call_item(att))
    result = history.append(tool_result_item(call))

    history.supersede_abandoned_attempt(att, reason="abandoned", at=NOW)

    assert result.item_id in {i.item_id for i in history.canonical_request_history()}


# -- attempts ------------------------------------------------------------------------

def test_dispatch_barrier_precedes_completion():
    att = attempt()
    assert att.dispatch_state == "admitted"
    assert not att.may_have_reached_provider
    with pytest.raises(HarnessStateError):
        att.mark_completed("end_turn")

    att.mark_dispatch_may_have_escaped(started_at=NOW)
    assert att.dispatch_state == "dispatch_may_have_escaped"
    assert att.may_have_reached_provider

    att.mark_completed("tool_calls_pending", completed_at=NOW)
    assert att.semantic_state == "completed"
    assert att.dispatch_state == "terminal"


def test_cancelled_before_dispatch_is_impossible_after_the_barrier():
    att = attempt()
    att.mark_dispatch_may_have_escaped()
    with pytest.raises(HarnessStateError):
        att.mark_cancelled_before_dispatch()


def test_terminal_cancellation_before_dispatch_does_not_claim_escape():
    att = attempt()
    att.mark_cancelled_before_dispatch(completed_at=NOW)
    assert att.semantic_state == "cancelled_before_dispatch"
    assert not att.may_have_reached_provider


def test_late_events_from_a_superseded_attempt_are_fenced():
    snapshot = StepSnapshotId.generate()
    old = attempt(snapshot_id=snapshot)
    new = attempt(snapshot_id=snapshot, generation=2)
    old.mark_dispatch_may_have_escaped()
    old.mark_abandoned("switched provider", superseded_by_attempt_id=new.attempt_id)

    assert not old.accepts_late_event(
        active_attempt_id=new.attempt_id, expected_snapshot_id=snapshot
    )
    assert new.accepts_late_event(
        active_attempt_id=new.attempt_id, expected_snapshot_id=snapshot
    )


def test_attempt_transitions_are_monotonic():
    att = attempt()
    att.mark_dispatch_may_have_escaped()
    att.mark_failed(InferenceError(kind="provider_internal"))
    with pytest.raises(HarnessStateError):
        att.mark_completed("end_turn")


# -- error taxonomy versus semantic replay -------------------------------------------

def test_transport_retryability_alone_never_authorises_a_fresh_semantic_attempt():
    error = InferenceError(kind="rate_limited", transport_retryable=True, retry_after=2.0)
    assert classify_recovery(error) == "same_attempt_transport_retry"
    # Same error, but the request may already have reached the provider: the transport flag has
    # not changed and the semantic answer has.
    assert (
        classify_recovery(error, dispatch_may_have_escaped=True)
        == "fresh_attempt_from_current_checkpoint"
    )


def test_unresolved_effect_outranks_every_error_kind():
    for kind in ("transient_transport", "rate_limited", "provider_internal", "invalid_request"):
        error = InferenceError(kind=kind, transport_retryable=True)
        assert classify_recovery(error, has_unresolved_effect=True) == "reconcile_or_suspend"


def test_non_retryable_kinds_are_not_replay_safe():
    for kind in ("quota_or_billing", "permission_denied", "policy_denied", "cancelled"):
        error = InferenceError(kind=kind, transport_retryable=True)
        assert classify_recovery(error) == "not_replay_safe"


def test_reconcile_or_suspend_degenerates_to_suspend_in_phase_1():
    """AR-11: there is no generic provider-side reconciliation, so it suspends rather than guess."""
    assert provider_action_for("reconcile_or_suspend") == "suspend"
    assert provider_action_for("not_replay_safe") == "fail"
    assert provider_action_for("same_attempt_transport_retry") == "retry_same_attempt"


def test_context_exhaustion_asks_for_compaction_not_a_blind_retry():
    error = InferenceError(kind="context_exhausted", transport_retryable=False)
    assert classify_recovery(error) == "compact_then_fresh_attempt"


# -- tool execution ------------------------------------------------------------------

def _execution(capability: ToolRecoveryCapability, key: ToolKey | None = None) -> ToolExecution:
    return ToolExecution(
        call_id=CerebroCallId.generate(),
        agent_turn_id=AgentTurnId.generate(),
        step_snapshot_id=StepSnapshotId.generate(),
        tool_call_item_id=InferenceItemId.generate(),
        tool_key=key or tool_key(),
        binding_generation=ToolBindingGeneration.generate(),
        recovery_capability=capability,
        admitted_at=NOW,
    )


def test_tool_execution_carries_its_own_format_version():
    execution = _execution(
        ToolRecoveryCapability(effect_class="read_only", repeat_semantics="idempotent")
    )
    assert execution.format_version == TOOL_EXECUTION_FORMAT_VERSION


def test_not_dispatched_call_can_resolve_directly_for_a_pre_dispatch_outcome():
    execution = _execution(
        ToolRecoveryCapability(effect_class="side_effecting", repeat_semantics="idempotent")
    )
    execution.resolve_known("denied", at=NOW)
    assert execution.dispatch_state == "resolved"
    assert execution.resolution.status == "denied"
    assert not execution.is_unresolved_effect


def test_success_cannot_be_recorded_for_a_call_that_never_dispatched():
    execution = _execution(
        ToolRecoveryCapability(effect_class="read_only", repeat_semantics="idempotent")
    )
    with pytest.raises(HarnessStateError):
        execution.resolve_known("success", at=NOW)


def test_escaped_dispatch_without_an_outcome_needs_attention():
    execution = _execution(
        ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="never_automatic_repeat"
        )
    )
    execution.mark_dispatch_may_have_escaped(at=NOW)
    assert execution.may_have_escaped
    assert execution.is_unresolved_effect
    assert not execution.may_repeat_dispatch()


def test_indeterminate_is_terminal_and_stays_visible():
    execution = _execution(
        ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="never_automatic_repeat"
        )
    )
    execution.mark_dispatch_may_have_escaped(at=NOW)
    execution.resolve_indeterminate("executor lost the response", at=NOW)
    assert execution.resolution.resolution_kind == "indeterminate"
    # Terminal, and still counted: the turn ending does not resolve the external effect.
    assert execution.is_unresolved_effect
    with pytest.raises(HarnessStateError):
        execution.resolve_known("error", at=NOW)


def test_indeterminate_cannot_be_invented_for_an_undispatched_call():
    execution = _execution(
        ToolRecoveryCapability(effect_class="read_only", repeat_semantics="idempotent")
    )
    with pytest.raises(HarnessStateError):
        execution.resolve_indeterminate("no idea", at=NOW)


def test_known_success_is_never_overwritten_by_a_later_timeout():
    execution = _execution(
        ToolRecoveryCapability(effect_class="side_effecting", repeat_semantics="idempotent")
    )
    execution.mark_dispatch_may_have_escaped(at=NOW)
    execution.resolve_known("success", at=NOW)
    with pytest.raises(HarnessStateError):
        execution.resolve_known("timeout", at=NOW)


def test_stable_idempotency_key_gates_dispatch_eligibility():
    execution = _execution(
        ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="stable_idempotency_key"
        )
    )
    assert not execution.dispatch_eligible
    with pytest.raises(HarnessStateError):
        execution.mark_dispatch_may_have_escaped(at=NOW)

    execution.assign_stable_operation_key("op-42")
    assert execution.dispatch_eligible
    execution.mark_dispatch_may_have_escaped(at=NOW)
    assert execution.may_repeat_dispatch()


def test_operation_key_cannot_be_rotated_or_assigned_after_dispatch():
    execution = _execution(
        ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="stable_idempotency_key"
        )
    )
    execution.assign_stable_operation_key("op-42")
    with pytest.raises(HarnessStateError):
        execution.assign_stable_operation_key("op-43")
    execution.mark_dispatch_may_have_escaped(at=NOW)
    with pytest.raises(HarnessStateError):
        execution.assign_stable_operation_key("op-42-again")


def test_reconcile_before_repeat_requires_a_named_reconciliation():
    with pytest.raises(ValidationError):
        ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="reconcile_before_repeat"
        )


# -- turn projection -----------------------------------------------------------------

def _turn(**overrides) -> AgentTurn:
    payload = {
        "id": AgentTurnId.generate(),
        "conversation_turn_id": ConversationTurnId.generate(),
        "causal_wake_key": CausalWakeKey(
            wake_kind="direct_message",
            target_agent_id="jarvis",
            channel_id="dm-1",
            trigger_message_id=7,
        ),
        "channel_id": "dm-1",
        "agent_id": "jarvis",
        "created_at": NOW,
    }
    payload.update(overrides)
    return AgentTurn(**payload)


def test_product_outcome_kind_is_the_finalization_discriminator():
    """AR-05: a topic PASS has no final row and must still count as finalized."""
    turn = _turn(lifecycle="completed", product_outcome_kind="topic_pass")
    assert turn.is_finalized
    assert turn.final_message_id is None


def test_a_visible_outcome_requires_its_message_evidence():
    with pytest.raises(ValidationError):
        _turn(lifecycle="completed", product_outcome_kind="final_message")


def test_completed_turn_requires_an_explicit_outcome():
    with pytest.raises(ValidationError):
        _turn(lifecycle="completed")


def test_unresolved_effects_force_the_attention_flag():
    turn = _turn()
    turn.record_unresolved_effects(2)
    assert turn.needs_attention and turn.unresolved_effect_count == 2
    with pytest.raises(ValidationError):
        _turn(unresolved_effect_count=1, needs_attention=False)


def test_suspension_requires_a_reason():
    with pytest.raises(ValidationError):
        _turn(lifecycle="suspended")


# -- causal wake ---------------------------------------------------------------------

def test_message_driven_wake_uses_the_trigger_message_as_occurrence_identity():
    first = CausalWakeKey(
        wake_kind="direct_message", target_agent_id="jarvis", channel_id="dm-1",
        trigger_message_id=7,
    )
    duplicate = CausalWakeKey(
        wake_kind="direct_message", target_agent_id="jarvis", channel_id="dm-1",
        trigger_message_id=7,
    )
    later = CausalWakeKey(
        wake_kind="direct_message", target_agent_id="jarvis", channel_id="dm-1",
        trigger_message_id=8,
    )
    assert first.stable_hash() == duplicate.stable_hash()
    assert first.stable_hash() != later.stable_hash()


def test_explicit_turn_requires_a_durable_occurrence_id():
    with pytest.raises(ValidationError):
        CausalWakeKey(
            wake_kind="explicit_turn", target_agent_id="jarvis", channel_id="general"
        )
    key = CausalWakeKey(
        wake_kind="explicit_turn", target_agent_id="jarvis", channel_id="general",
        occurrence_id="cron-2026-08-29T09:00",
    )
    assert "cron-2026-08-29T09:00" in key.serialized()


def test_poll_without_a_trigger_message_needs_an_occurrence_id():
    with pytest.raises(ValidationError):
        CausalWakeKey(
            wake_kind="channel_poll", target_agent_id="jarvis", channel_id="general"
        )


# -- request hashing and continuation admission --------------------------------------

def _request(**overrides) -> InferenceRequest:
    payload = {
        "step_snapshot_id": StepSnapshotId.generate(),
        "provider_config_ref": ProviderConfigId.generate(),
        "model_profile_ref": ModelProfileId.generate(),
        "history": [user_item("hello", sequence_no=0)],
    }
    payload.update(overrides)
    return InferenceRequest(**payload)


def test_semantic_hash_ignores_trace_and_cache_state():
    base = _request()
    noisy = base.model_copy(
        update={"trace_metadata": {"trace": "abc"}, "cache_hints": {"prefix": "xyz"}}
    )
    assert request_semantic_hash(base) == request_semantic_hash(noisy)


def test_semantic_hash_changes_with_history():
    base = _request()
    extended = base.model_copy(
        update={"history": [*base.history, user_item("and one more", sequence_no=1)]}
    )
    assert request_semantic_hash(base) != request_semantic_hash(extended)


def test_a_profile_needing_opaque_replay_is_refused_by_a_dialect_that_cannot_carry_it():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    profile = model_profile(opaque_replay_behavior="required_for_correctness")
    with pytest.raises(ContinuationNotAdmissible):
        assert_continuation_admissible(adapter.resolve_capabilities(profile), profile)


def test_the_current_lmstudio_profile_is_admissible():
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    profile = model_profile()
    assert_continuation_admissible(adapter.resolve_capabilities(profile), profile)
