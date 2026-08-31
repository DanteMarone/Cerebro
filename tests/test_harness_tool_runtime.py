"""The standalone Harness tool-effect primitive (Phase 1C).

Covers F-06, F-07, F-08, the tool arms of F-09, F-13, F-14, F-15 and F-16, plus the durability
and redaction rules around raw output. Every executor here is a fake; nothing reaches a paid
provider or a real MCP subprocess.
"""

import inspect

import pytest

from cerebro import db
from cerebro.config import Settings
from cerebro.harness import ArtifactStore, ToolCallItem, ToolResultItem
from cerebro.harness.artifacts import INLINE_THRESHOLD_BYTES, ArtifactWriteFailed
from cerebro.harness.exceptions import HarnessStateError
from cerebro.harness.store import HarnessStore
from cerebro.harness.tool_runtime import (
    MODEL_PROJECTION_LIMIT_CHARS,
    HarnessToolRuntime,
    KnownInvocation,
    UnknownInvocation,
)
from tests.harness_phase1c import (
    IDEMPOTENT,
    KEYED,
    NOW,
    RECONCILABLE,
    FakeExecutorGateway,
    FakeToolCatalog,
    KeyedRemote,
    catalog_entry,
    executable_call,
    mcp_key,
)


def catalog(capability=None, *, generation: str = "g1") -> FakeToolCatalog:
    entry = catalog_entry(
        mcp_key(), generation=generation, **({"capability": capability} if capability else {})
    )
    return FakeToolCatalog([entry])


def artifacts(settings: Settings) -> ArtifactStore:
    return ArtifactStore(settings.data_dir / "harness_artifacts")


def runtime(store, fixture, gateway, settings) -> HarnessToolRuntime:
    return HarnessToolRuntime(
        store, catalog=fixture.catalog, gateway=gateway, artifacts=artifacts(settings)
    )


async def _result_items(store, turn) -> list[ToolResultItem]:
    items = await store.list_inference_items(turn.conversation_turn_id)
    return [item for item in items if isinstance(item, ToolResultItem)]


@pytest.mark.asyncio
async def test_no_executor_call_happens_before_the_dispatch_mark_commits(test_db: Settings):
    """The single ordering this module exists for, asserted directly."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="ordering")
    observed: list[str] = []

    class OrderingGateway(FakeExecutorGateway):
        async def invoke(self, request):
            stored = await store.get_tool_execution(request.call_id)
            observed.append(stored.execution.dispatch_state)
            return await super().invoke(request)

    gateway = OrderingGateway([KnownInvocation(raw_output="done")])
    await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)

    # The executor saw a durably marked call, not a not_dispatched one.
    assert observed == ["dispatch_may_have_escaped"]


@pytest.mark.asyncio
async def test_f06_non_idempotent_ambiguity_never_repeats_automatically(test_db: Settings):
    """F-06: a lost response for a `never_automatic_repeat` tool stays truthfully unknown."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f06")
    gateway = FakeExecutorGateway(
        [UnknownInvocation(reason="remote committed, response lost")]
    )
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)

    assert outcome.disposition == "resolved_indeterminate"
    assert gateway.count_for("g1") == 1

    await db.close()
    await db.connect(test_db.db_path)
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "resolved"
    assert stored.execution.resolution.resolution_kind == "indeterminate"
    assert stored.execution.is_unresolved_effect is True
    turn = await store.get_turn(fixture.turn.id)
    assert turn.needs_attention is True
    assert turn.unresolved_effect_count == 1

    # A second automatic attempt is refused, not merely avoided by luck.
    with pytest.raises(HarnessStateError, match="no uncertain dispatch to resume"):
        await runtime(store, fixture, gateway, test_db).resume_uncertain_call(fixture.call_id)
    assert gateway.count_for("g1") == 1


@pytest.mark.asyncio
async def test_f06_uncertainty_survives_restart_before_resolution(test_db: Settings):
    """A crash between the dispatch mark and the result leaves uncertainty, not failure."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f06-restart")
    stored = await store.get_tool_execution(fixture.call_id)
    turn = await fixture.reload()
    await store.mark_tool_dispatch_after_barrier(
        fixture.call_id,
        binding=fixture.snapshot.tool_plan.binding_for(mcp_key()),
        expected_tool_version=stored.row_version,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    await db.close()
    await db.connect(test_db.db_path)

    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "dispatch_may_have_escaped"
    assert stored.execution.resolution is None
    gateway = FakeExecutorGateway()
    with pytest.raises(HarnessStateError, match="use resume_uncertain_call"):
        await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    assert gateway.invocations == []


@pytest.mark.asyncio
async def test_f07_stable_idempotency_key_retry_reuses_the_durable_key(test_db: Settings):
    """F-07: after a restart the retry reuses the persisted key and mutates once."""
    store = HarnessStore()
    fixture = await executable_call(
        store,
        catalog(KEYED),
        occurrence="f07",
        stable_operation_key="op-charge-77",
    )
    remote = KeyedRemote(lose_first_response=True)

    first = await runtime(store, fixture, remote, test_db).execute_call(fixture.call_id)
    # The in-process retry already reuses the same durable key.
    assert first.disposition == "resolved_known"
    assert remote.mutations == ["op-charge-77"]
    assert [call.stable_operation_key for call in remote.invocations] == [
        "op-charge-77",
        "op-charge-77",
    ]

    await db.close()
    await db.connect(test_db.db_path)
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.stable_operation_key == "op-charge-77"
    assert stored.execution.resolution.status == "success"
    assert len(remote.mutations) == 1
    assert len(await _result_items(store, fixture.turn)) == 1


@pytest.mark.asyncio
async def test_f07_restart_before_retry_reuses_the_same_persisted_key(test_db: Settings):
    """The key is durable, so a process that dies before retrying cannot mint a new one."""
    store = HarnessStore()
    fixture = await executable_call(
        store, catalog(KEYED), occurrence="f07-restart", stable_operation_key="op-charge-88"
    )
    remote = KeyedRemote(lose_first_response=True)

    class OnceGateway:
        async def invoke(self, request):
            return await remote.invoke(request)

    # Mark dispatch, invoke once, then "crash" before the result is committed.
    stored = await store.get_tool_execution(fixture.call_id)
    turn = await fixture.reload()
    await store.mark_tool_dispatch_after_barrier(
        fixture.call_id,
        binding=fixture.snapshot.tool_plan.binding_for(mcp_key()),
        expected_tool_version=stored.row_version,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    await remote.invoke(
        _request_for(await store.get_tool_execution(fixture.call_id), fixture)
    )
    await db.close()
    await db.connect(test_db.db_path)

    outcome = await runtime(store, fixture, OnceGateway(), test_db).resume_uncertain_call(
        fixture.call_id
    )
    assert outcome.disposition == "resolved_known"
    assert remote.mutations == ["op-charge-88"]
    assert {call.stable_operation_key for call in remote.invocations} == {"op-charge-88"}
    assert len(await _result_items(store, fixture.turn)) == 1


def _request_for(stored, fixture):
    from cerebro.harness.tool_runtime import ToolInvocationRequest

    execution = stored.execution
    return ToolInvocationRequest(
        call_id=execution.call_id,
        agent_turn_id=execution.agent_turn_id,
        binding=fixture.snapshot.tool_plan.binding_for(execution.tool_key),
        wire_name="payments__charge",
        arguments={"amount": 10},
        stable_operation_key=execution.stable_operation_key,
        attempt_number=1,
    )


@pytest.mark.asyncio
async def test_f08_known_result_is_monotonic_across_reopen(test_db: Settings):
    """F-08: a committed known result stays in history and cannot become executable again."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f08")
    gateway = FakeExecutorGateway([KnownInvocation(raw_output="charged")])
    await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)

    await db.close()
    await db.connect(test_db.db_path)

    results = await _result_items(store, fixture.turn)
    assert len(results) == 1
    assert results[0].status == "success"
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "resolved"
    turn = await store.get_turn(fixture.turn.id)
    assert turn.needs_attention is False

    with pytest.raises(HarnessStateError, match="already resolved"):
        await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    assert gateway.count_for("g1") == 1
    assert len(await _result_items(store, fixture.turn)) == 1


@pytest.mark.asyncio
async def test_f09_cancellation_before_the_dispatch_mark_invokes_nothing(test_db: Settings):
    """F-09 arm 1: pre-dispatch cancellation is the one cancellation that proves no effect."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f09-pre")
    gateway = FakeExecutorGateway()
    outcome = await runtime(store, fixture, gateway, test_db).cancel_before_dispatch(
        fixture.call_id, reason="turn cancelled by the user"
    )
    assert outcome.disposition == "cancelled_before_dispatch"
    assert gateway.invocations == []
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.resolution.status == "cancelled_before_dispatch"
    turn = await store.get_turn(fixture.turn.id)
    assert turn.needs_attention is False


@pytest.mark.asyncio
async def test_f09_cancellation_after_the_dispatch_mark_cannot_rewind_uncertainty(
    test_db: Settings,
):
    """F-09 arm 2: once dispatch may have escaped, cancellation is not proof of no effect."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f09-post")
    stored = await store.get_tool_execution(fixture.call_id)
    turn = await fixture.reload()
    stored, turn = await store.mark_tool_dispatch_after_barrier(
        fixture.call_id,
        binding=fixture.snapshot.tool_plan.binding_for(mcp_key()),
        expected_tool_version=stored.row_version,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    gateway = FakeExecutorGateway()
    with pytest.raises(HarnessStateError, match="cannot prove it did not"):
        await runtime(store, fixture, gateway, test_db).cancel_before_dispatch(
            fixture.call_id, reason="too late"
        )
    assert gateway.invocations == []

    await store.transition_turn(
        turn.id,
        expected_version=turn.state_version,
        lifecycle="cancelled",
        at=NOW,
    )
    await db.close()
    await db.connect(test_db.db_path)
    reloaded = await store.get_tool_execution(fixture.call_id)
    assert reloaded.execution.dispatch_state == "dispatch_may_have_escaped"
    cancelled_turn = await store.get_turn(turn.id)
    assert cancelled_turn.lifecycle == "cancelled"
    assert cancelled_turn.needs_attention is True
    assert cancelled_turn.unresolved_effect_count == 1


@pytest.mark.asyncio
async def test_f09_known_result_survives_a_later_cancellation(test_db: Settings):
    """F-09 arm 4: a durably known success is never rewritten as cancelled."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f09-known")
    gateway = FakeExecutorGateway([KnownInvocation(raw_output="charged")])
    await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    turn = await fixture.reload()
    await store.transition_turn(
        turn.id, expected_version=turn.state_version, lifecycle="cancelled", at=NOW
    )
    await db.close()
    await db.connect(test_db.db_path)
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.resolution.status == "success"
    assert len(await _result_items(store, fixture.turn)) == 1


@pytest.mark.asyncio
async def test_f13_large_output_keeps_complete_raw_evidence_and_bounded_projection(
    test_db: Settings,
):
    """F-13: the model sees a bounded projection; the durable evidence stays complete."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f13")
    huge = "X" * (INLINE_THRESHOLD_BYTES * 3)
    gateway = FakeExecutorGateway([KnownInvocation(raw_output=huge)])
    store_artifacts = artifacts(test_db)
    outcome = await HarnessToolRuntime(
        store, catalog=fixture.catalog, gateway=gateway, artifacts=store_artifacts
    ).execute_call(fixture.call_id)

    assert outcome.disposition == "resolved_known"
    assert outcome.artifact["storage_backend"] == "file"
    assert outcome.artifact["byte_size"] == len(huge)

    results = await _result_items(store, fixture.turn)
    assert len(results) == 1
    projection = results[0]
    assert projection.content[0].text == huge[:MODEL_PROJECTION_LIMIT_CHARS]
    assert len(projection.content[0].text) == MODEL_PROJECTION_LIMIT_CHARS
    assert projection.original_size == len(huge)
    assert projection.omission is not None
    assert projection.omission.omitted_bytes == len(huge) - MODEL_PROJECTION_LIMIT_CHARS
    assert projection.raw_output_ref is not None

    await db.close()
    await db.connect(test_db.db_path)
    assert await store_artifacts.read(projection.raw_output_ref) == huge
    index = await store.get_artifact(projection.raw_output_ref)
    assert index.byte_size == len(huge)
    assert index.retention_policy == "conversation"
    assert index.provenance["call_id"] == str(fixture.call_id)
    # Nothing log-facing carries the payload.
    assert huge not in str(index.describe())
    assert huge not in str(outcome.describe())


@pytest.mark.asyncio
async def test_small_output_stays_inline_and_still_round_trips(test_db: Settings):
    """Below the threshold the exact bytes live in the row; there is no file to lose."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="artifact-inline")
    gateway = FakeExecutorGateway([KnownInvocation(raw_output="small result")])
    store_artifacts = artifacts(test_db)
    outcome = await HarnessToolRuntime(
        store, catalog=fixture.catalog, gateway=gateway, artifacts=store_artifacts
    ).execute_call(fixture.call_id)
    assert outcome.artifact["storage_backend"] == "inline"
    results = await _result_items(store, fixture.turn)
    assert results[0].omission is None
    assert await store_artifacts.read(results[0].raw_output_ref) == "small result"


@pytest.mark.asyncio
async def test_artifact_write_failure_leaves_no_committed_reference(test_db: Settings):
    """A raw-output write that fails never becomes a committed dangling ArtifactRef."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="artifact-fail")
    huge = "Y" * (INLINE_THRESHOLD_BYTES * 2)
    gateway = FakeExecutorGateway([KnownInvocation(raw_output=huge)])

    class FailingArtifacts(ArtifactStore):
        def stage(self, *args, **kwargs):
            raise ArtifactWriteFailed("disk is full")

    with pytest.raises(ArtifactWriteFailed):
        await HarnessToolRuntime(
            store,
            catalog=fixture.catalog,
            gateway=gateway,
            artifacts=FailingArtifacts(test_db.data_dir / "harness_artifacts"),
        ).execute_call(fixture.call_id)

    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "dispatch_may_have_escaped"
    assert stored.execution.raw_output_ref is None
    assert await _result_items(store, fixture.turn) == []
    assert await db.fetch_all("SELECT * FROM harness_artifacts") == []


@pytest.mark.asyncio
async def test_a_result_reference_without_its_artifact_is_refused(test_db: Settings):
    """The store refuses to commit a ToolResultItem that names an unstaged artifact."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="artifact-dangling")
    stored = await store.get_tool_execution(fixture.call_id)
    turn = await fixture.reload()
    stored, turn = await store.mark_tool_dispatch_after_barrier(
        fixture.call_id,
        binding=fixture.snapshot.tool_plan.binding_for(mcp_key()),
        expected_tool_version=stored.row_version,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    from cerebro.harness import ArtifactRef, InferenceItemId, TextPart

    orphan = ToolResultItem(
        item_id=InferenceItemId.generate(),
        call_id=fixture.call_id,
        tool_key=stored.execution.tool_key,
        status="success",
        content=[TextPart(text="ok")],
        raw_output_ref=ArtifactRef("artf_" + "0" * 24),
    )
    with pytest.raises(HarnessStateError, match="requires its staged durable artifact"):
        await store.resolve_tool_known(
            fixture.call_id,
            "success",
            expected_tool_version=stored.row_version,
            expected_turn_version=turn.state_version,
            result_item=orphan,
            expected_history_version=await store.history_version(turn.conversation_turn_id),
            at=NOW,
        )
    assert await db.fetch_all("SELECT * FROM harness_artifacts") == []
    assert await _result_items(store, fixture.turn) == []


@pytest.mark.asyncio
async def test_f14_arm_a_still_addressable_g1_is_invoked_and_g2_is_not(test_db: Settings):
    """F-14 arm A: the frozen generation is still addressable, so it runs. G2 count is zero."""
    store = HarnessStore()
    live = catalog()
    fixture = await executable_call(store, live, occurrence="f14-a")
    replacement = catalog_entry(mcp_key(), generation="g2")
    live.add(replacement)

    gateway = FakeExecutorGateway([KnownInvocation(raw_output="g1 ran")])
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)

    assert outcome.disposition == "resolved_known"
    assert gateway.count_for("g1") == 1
    assert gateway.count_for("g2") == 0
    assert gateway.invocations[0].executor_identity.endswith("/g1")


@pytest.mark.asyncio
async def test_f14_arm_b_unaddressable_g1_resolves_stale_and_never_touches_g2(
    test_db: Settings,
):
    """F-14 arm B: G1 is gone, so the call resolves unavailable under its original identity."""
    store = HarnessStore()
    live = catalog()
    fixture = await executable_call(store, live, occurrence="f14-b")
    live.replace(mcp_key(), catalog_entry(mcp_key(), generation="g2"))

    gateway = FakeExecutorGateway()
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)

    assert outcome.disposition == "unavailable_stale_binding"
    assert outcome.status == "unavailable"
    assert gateway.invocations == []
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "resolved"
    assert stored.execution.call_id == fixture.call_id
    assert str(stored.execution.binding_generation) == "tbg_g1"
    results = await _result_items(store, fixture.turn)
    assert results[0].status == "unavailable"
    assert results[0].call_id == fixture.call_id


@pytest.mark.asyncio
async def test_f15_security_revocation_denies_under_the_original_identity(test_db: Settings):
    """F-15: an epoch advanced after the snapshot denies the call and invokes nothing."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="f15")
    await store.advance_security_revocation_epoch(at=NOW)

    gateway = FakeExecutorGateway()
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)

    assert outcome.disposition == "denied_security_revocation"
    assert outcome.status == "denied"
    assert gateway.invocations == []
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.call_id == fixture.call_id
    assert str(stored.execution.binding_generation) == "tbg_g1"
    assert stored.execution.resolution.status == "denied"
    # The barrier itself also refuses, so no other caller can slip past the runtime.
    turn = await store.get_turn(fixture.turn.id)
    assert turn.needs_attention is False


@pytest.mark.asyncio
async def test_revoked_grant_denies_without_rebinding_to_the_new_grant(test_db: Settings):
    """A tier or glob change denies the frozen call; it never adopts the newer grant."""
    store = HarnessStore()
    live = catalog()
    fixture = await executable_call(store, live, occurrence="grant-revoked")
    live.revoke_grant(policy_version=123)

    gateway = FakeExecutorGateway()
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    assert outcome.disposition == "denied_security_revocation"
    assert "grant policy version changed" in outcome.reason
    assert gateway.invocations == []
    stored = await store.get_tool_execution(fixture.call_id)
    assert str(stored.execution.binding_generation) == "tbg_g1"


@pytest.mark.asyncio
async def test_f16_multiple_calls_execute_sequentially_in_original_order(test_db: Settings):
    """F-16: one provider step's calls run in order, each with its own durable state."""
    store = HarnessStore()
    fixture = await executable_call(
        store, catalog(), occurrence="f16", call_count=3
    )
    gateway = FakeExecutorGateway([KnownInvocation(raw_output="ok")])
    outcomes = await runtime(store, fixture, gateway, test_db).execute_step_calls(
        fixture.call_ids
    )

    assert [outcome.disposition for outcome in outcomes] == ["resolved_known"] * 3
    assert [call.call_id for call in gateway.invocations] == [
        str(call_id) for call_id in fixture.call_ids
    ]
    assert [call.arguments["amount"] for call in gateway.invocations] == [10, 11, 12]

    results = await _result_items(store, fixture.turn)
    assert len(results) == 3
    assert len({result.call_id for result in results}) == 3
    for call_id in fixture.call_ids:
        stored = await store.get_tool_execution(call_id)
        assert stored.execution.dispatch_state == "resolved"
        assert stored.execution.raw_output_ref is not None
    # Execution is sequential by construction, not by scheduling luck.
    source = inspect.getsource(HarnessToolRuntime.execute_step_calls)
    assert "gather" not in source


@pytest.mark.asyncio
async def test_terminal_turn_makes_a_checkpointed_call_non_executable(test_db: Settings):
    """A cancelled or completed turn admits no new external effect."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="terminal")
    turn = await fixture.reload()
    await store.transition_turn(
        turn.id, expected_version=turn.state_version, lifecycle="cancelled", at=NOW
    )
    gateway = FakeExecutorGateway()
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    assert outcome.disposition == "not_executable"
    assert gateway.invocations == []
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "not_dispatched"


@pytest.mark.asyncio
async def test_reconcile_before_repeat_uses_the_named_authoritative_lookup(test_db: Settings):
    """`reconcile_before_repeat` asks the declared lookup and never blind-retries."""
    store = HarnessStore()
    fixture = await executable_call(
        store, catalog(RECONCILABLE), occurrence="reconcile", stable_operation_key=None
    )
    gateway = FakeExecutorGateway(
        [UnknownInvocation(reason="timed out")],
        reconcile_outcome=KnownInvocation(raw_output="the charge did happen"),
    )
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)

    assert outcome.disposition == "resolved_known"
    assert outcome.detail["reconciled"] is True
    assert gateway.count_for("g1") == 1
    assert len(gateway.reconciliations) == 1


@pytest.mark.asyncio
async def test_reconcile_without_an_answer_stays_indeterminate(test_db: Settings):
    """An inconclusive reconciliation is not permission to repeat the mutation."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(RECONCILABLE), occurrence="reconcile-none")
    gateway = FakeExecutorGateway(
        [UnknownInvocation(reason="timed out")], reconcile_outcome=None
    )
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    assert outcome.disposition == "resolved_indeterminate"
    assert outcome.detail["reconciliation_attempted"] is True
    assert gateway.count_for("g1") == 1
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.resolution.reconciliation_attempted is True


@pytest.mark.asyncio
async def test_idempotent_read_only_tool_may_retry_once(test_db: Settings):
    """A declared-idempotent read has no externally relevant effect, so one retry is safe."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(IDEMPOTENT), occurrence="idempotent")
    gateway = FakeExecutorGateway(
        [UnknownInvocation(reason="connection reset"), KnownInvocation(raw_output="value")]
    )
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    assert outcome.disposition == "resolved_known"
    assert gateway.count_for("g1") == 2
    assert [call.attempt_number for call in gateway.invocations] == [1, 2]


@pytest.mark.asyncio
async def test_a_raising_executor_is_unknown_not_a_known_failure(test_db: Settings):
    """A traceback proves the call failed locally, not that the remote effect did not happen."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="raising")
    gateway = FakeExecutorGateway()
    gateway.raise_on_invoke = TimeoutError("socket timed out")
    outcome = await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    assert outcome.disposition == "resolved_indeterminate"
    assert "TimeoutError" in outcome.reason
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.resolution.resolution_kind == "indeterminate"


@pytest.mark.asyncio
async def test_the_admitted_call_item_is_never_superseded_by_the_result(test_db: Settings):
    """One canonical result item joins the history; the call item stays exactly as admitted."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="one-result")
    gateway = FakeExecutorGateway([KnownInvocation(raw_output="ok")])
    await runtime(store, fixture, gateway, test_db).execute_call(fixture.call_id)
    items = await store.list_inference_items(fixture.turn.conversation_turn_id)
    assert [type(item) for item in items] == [ToolCallItem, ToolResultItem]
    assert [item.sequence_no for item in items] == [0, 1]
    assert items[0].is_superseded is False
