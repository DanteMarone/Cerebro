"""Authoritative output admission and the atomic pre-side-effect barrier (Phase 1C).

Covers the Phase 1C portions of F-04, F-05 and F-10 plus the barrier's fail-closed cases.
"""

import pytest

from cerebro import db
from cerebro.config import Settings
from cerebro.harness import (
    AssistantTextDelta,
    CerebroCallId,
    InferenceAttempt,
    InferenceAttemptId,
    OutputItemCompleted,
    ToolCallInputDelta,
    ToolCallItem,
)
from cerebro.harness.exceptions import (
    DuplicateHarnessIdentity,
    HarnessStateError,
    StaleHarnessWrite,
)
from cerebro.harness.store import HarnessStore
from cerebro.harness.tool_runtime import HarnessToolRuntime
from tests.harness_phase1c import (
    NOW,
    FakeExecutorGateway,
    FakeToolCatalog,
    admit_output,
    catalog_entry,
    executable_call,
    mcp_key,
    opaque_item,
    snapshotted_turn,
    tool_call,
)


def catalog() -> FakeToolCatalog:
    return FakeToolCatalog([catalog_entry(mcp_key(), generation="g1")])


async def _tool_execution_count() -> int:
    row = await db.fetch_one("SELECT COUNT(*) AS count FROM tool_executions")
    return row["count"]


@pytest.mark.asyncio
async def test_f04_deltas_never_become_executable_authority(test_db: Settings):
    """F-04: a complete-looking delta stream admits nothing and invokes nothing."""
    store = HarnessStore()
    live = catalog()
    turn, snapshot, attempt = await snapshotted_turn(store, live, occurrence="f04")
    gateway = FakeExecutorGateway()

    admission = await admit_output(
        store,
        turn,
        snapshot,
        attempt,
        [],
        extra_events=[
            AssistantTextDelta(attempt_id=attempt.attempt_id, text="I will charge the card"),
            ToolCallInputDelta(
                attempt_id=attempt.attempt_id,
                call_index=0,
                provider_native_call_id="call_1",
                tool_wire_name="payments__charge",
                arguments_fragment='{"amount": 10}',
            ),
        ],
    )

    assert admission.observed_deltas == 2
    assert admission.accepted == ()
    assert await store.history_version(turn.conversation_turn_id) == 0
    assert await _tool_execution_count() == 0
    assert gateway.invocations == []
    items = await store.list_inference_items(turn.conversation_turn_id)
    assert items == []


@pytest.mark.asyncio
async def test_f10_late_output_from_an_abandoned_attempt_cannot_enter_history(test_db: Settings):
    """F-10: an abandoned attempt's finalized tool call changes nothing and runs nothing."""
    store = HarnessStore()
    live = catalog()
    turn, snapshot, attempt_a = await snapshotted_turn(store, live, occurrence="f10")

    _, turn = await store.abandon_attempt(
        attempt_a.attempt_id,
        "switched model",
        expected_attempt_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    attempt_b = InferenceAttempt(
        attempt_id=InferenceAttemptId.generate(),
        agent_turn_id=turn.id,
        step_snapshot_id=snapshot.snapshot_id,
        attempt_generation=2,
        turn_version_admitted=turn.state_version,
        request_semantic_hash="d" * 64,
    )
    _, turn = await store.admit_inference_attempt(
        attempt_b, expected_turn_version=turn.state_version, at=NOW
    )

    late_call = tool_call(attempt_a, mcp_key(), native_call_id="late")
    admission = await admit_output(store, turn, snapshot, attempt_b, [])
    assert admission.accepted == ()

    from cerebro.harness import ProviderOutputCoordinator

    coordinator = ProviderOutputCoordinator(store)
    result = await coordinator.accept(
        [OutputItemCompleted(attempt_id=attempt_a.attempt_id, item=late_call)],
        turn=turn,
        snapshot_id=snapshot.snapshot_id,
        active_attempt_id=attempt_b.attempt_id,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        at=NOW,
    )
    assert result.accepted == ()
    assert [entry.reason for entry in result.rejected] == ["stale_or_non_active_attempt"]
    assert await store.list_inference_items(turn.conversation_turn_id) == []
    assert await _tool_execution_count() == 0

    # And the barrier refuses the stale call outright, even if a caller offers it.
    binding = snapshot.tool_plan.binding_for(mcp_key())
    with pytest.raises(Exception):
        await store.commit_executable_call_checkpoint(
            agent_turn_id=turn.id,
            snapshot_id=snapshot.snapshot_id,
            attempt_id=attempt_a.attempt_id,
            tool_call_item_id=late_call.item_id,
            call_id=late_call.call_id,
            binding=binding,
            expected_turn_version=turn.state_version,
            expected_history_version=0,
            expected_replay_version=0,
            at=NOW,
        )
    assert await _tool_execution_count() == 0


@pytest.mark.asyncio
async def test_output_coordinator_rejects_attribution_mismatch(test_db: Settings):
    """An item that names another attempt is not this attempt's output, whoever delivered it."""
    store = HarnessStore()
    turn, snapshot, attempt = await snapshotted_turn(store, catalog(), occurrence="attribution")
    other = InferenceAttemptId.generate()
    mismatched = tool_call(attempt, mcp_key()).model_copy(
        update={"producing_attempt_id": other}
    )
    from cerebro.harness import ProviderOutputCoordinator

    result = await ProviderOutputCoordinator(store).accept(
        [OutputItemCompleted(attempt_id=attempt.attempt_id, item=mismatched)],
        turn=turn,
        snapshot_id=snapshot.snapshot_id,
        active_attempt_id=attempt.attempt_id,
        expected_history_version=0,
        at=NOW,
    )
    assert [entry.reason for entry in result.rejected] == ["attempt_attribution_mismatch"]
    assert await store.list_inference_items(turn.conversation_turn_id) == []


@pytest.mark.asyncio
async def test_replay_version_advances_only_for_replay_material(test_db: Settings):
    """The provider-replay checkpoint counts what a next request must reproduce exactly."""
    store = HarnessStore()
    turn, snapshot, attempt = await snapshotted_turn(store, catalog(), occurrence="replay-count")
    assert await store.replay_version(turn.conversation_turn_id) == 0

    await admit_output(
        store,
        turn,
        snapshot,
        attempt,
        [
            opaque_item(attempt),
            tool_call(attempt, mcp_key(), replay_required=True),
        ],
    )
    assert await store.replay_version(turn.conversation_turn_id) == 2
    assert await store.history_version(turn.conversation_turn_id) == 2

    turn = await store.get_turn(turn.id)
    await admit_output(
        store,
        turn,
        snapshot,
        attempt,
        [tool_call(attempt, mcp_key(), native_call_id="c2", replay_required=False)],
    )
    assert await store.replay_version(turn.conversation_turn_id) == 2
    assert await store.history_version(turn.conversation_turn_id) == 3


@pytest.mark.asyncio
async def test_barrier_commits_the_whole_executable_set(test_db: Settings):
    """D, E, E2, I, J, K and L land together, and the event records the checkpoint."""
    store = HarnessStore()
    fixture = await executable_call(
        store,
        catalog(),
        occurrence="barrier-happy",
        with_opaque=True,
        require_provider_call_ref=True,
        required_opaque_kinds=("reasoning_state",),
    )
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "not_dispatched"
    assert str(stored.execution.binding_generation) == "tbg_g1"
    assert stored.execution.binding_executor_identity.endswith("/g1")
    assert stored.execution.recovery_capability.repeat_semantics == "never_automatic_repeat"

    events = await store.list_turn_events(fixture.turn.id)
    checkpoint = [e for e in events if e["event_type"] == "tool.call_admitted"][-1]
    assert checkpoint["detail"]["checkpoint"] == "executable_pre_side_effect"
    assert checkpoint["detail"]["binding_generation"] == "tbg_g1"
    assert checkpoint["resulting_turn_state_version"] == fixture.turn.state_version


@pytest.mark.asyncio
async def test_barrier_fails_closed_on_missing_replay_material(test_db: Settings):
    """F and G: a missing provider handle or required opaque item blocks the checkpoint."""
    store = HarnessStore()
    live = catalog()
    turn, snapshot, attempt = await snapshotted_turn(store, live, occurrence="barrier-replay")
    call = tool_call(attempt, mcp_key(), with_provider_ref=False)
    admission = await admit_output(store, turn, snapshot, attempt, [call])
    stored_call = admission.accepted[0]
    turn = await store.get_turn(turn.id)
    binding = snapshot.tool_plan.binding_for(mcp_key())

    common = dict(
        agent_turn_id=turn.id,
        snapshot_id=snapshot.snapshot_id,
        attempt_id=attempt.attempt_id,
        tool_call_item_id=stored_call.item_id,
        call_id=stored_call.call_id,
        binding=binding,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    with pytest.raises(HarnessStateError, match="replay-required ProviderCallRef"):
        await store.commit_executable_call_checkpoint(
            **common, require_provider_call_ref=True
        )
    assert await _tool_execution_count() == 0

    with pytest.raises(HarnessStateError, match="required ProviderOpaqueItem kinds"):
        await store.commit_executable_call_checkpoint(
            **common, required_opaque_kinds=("reasoning_state",)
        )
    assert await _tool_execution_count() == 0


@pytest.mark.asyncio
async def test_barrier_fails_closed_on_stale_history_replay_or_turn(test_db: Settings):
    """H and K: a stale expected version is never treated as good enough."""
    store = HarnessStore()
    live = catalog()
    turn, snapshot, attempt = await snapshotted_turn(store, live, occurrence="barrier-stale")
    admission = await admit_output(
        store, turn, snapshot, attempt, [tool_call(attempt, mcp_key())]
    )
    stored_call = admission.accepted[0]
    turn = await store.get_turn(turn.id)
    binding = snapshot.tool_plan.binding_for(mcp_key())
    history_version = await store.history_version(turn.conversation_turn_id)
    replay_version = await store.replay_version(turn.conversation_turn_id)

    base = dict(
        agent_turn_id=turn.id,
        snapshot_id=snapshot.snapshot_id,
        attempt_id=attempt.attempt_id,
        tool_call_item_id=stored_call.item_id,
        call_id=stored_call.call_id,
        binding=binding,
        at=NOW,
    )
    with pytest.raises(StaleHarnessWrite):
        await store.commit_executable_call_checkpoint(
            **base,
            expected_turn_version=turn.state_version - 1,
            expected_history_version=history_version,
            expected_replay_version=replay_version,
        )
    with pytest.raises(StaleHarnessWrite, match="InferenceHistory"):
        await store.commit_executable_call_checkpoint(
            **base,
            expected_turn_version=turn.state_version,
            expected_history_version=history_version - 1,
            expected_replay_version=replay_version,
        )
    with pytest.raises(StaleHarnessWrite, match="provider replay checkpoint"):
        await store.commit_executable_call_checkpoint(
            **base,
            expected_turn_version=turn.state_version,
            expected_history_version=history_version,
            expected_replay_version=replay_version + 5,
        )
    assert await _tool_execution_count() == 0


@pytest.mark.asyncio
async def test_barrier_rejects_a_binding_that_is_not_the_frozen_one(test_db: Settings):
    """J: a same-named newer generation is not the binding this call was frozen against."""
    store = HarnessStore()
    live = catalog()
    turn, snapshot, attempt = await snapshotted_turn(store, live, occurrence="barrier-binding")
    admission = await admit_output(
        store, turn, snapshot, attempt, [tool_call(attempt, mcp_key())]
    )
    stored_call = admission.accepted[0]
    turn = await store.get_turn(turn.id)
    replacement = catalog_entry(mcp_key(), generation="g2").binding

    with pytest.raises(HarnessStateError, match="not the one frozen in the snapshot"):
        await store.commit_executable_call_checkpoint(
            agent_turn_id=turn.id,
            snapshot_id=snapshot.snapshot_id,
            attempt_id=attempt.attempt_id,
            tool_call_item_id=stored_call.item_id,
            call_id=stored_call.call_id,
            binding=replacement,
            expected_turn_version=turn.state_version,
            expected_history_version=await store.history_version(turn.conversation_turn_id),
            expected_replay_version=await store.replay_version(turn.conversation_turn_id),
            at=NOW,
        )
    assert await _tool_execution_count() == 0


@pytest.mark.asyncio
async def test_barrier_rejects_an_identity_only_snapshot(test_db: Settings):
    """A: a Phase 1B identity seam describes nothing executable, so nothing is executable."""
    store = HarnessStore()
    from cerebro.harness.store import StepSnapshotIdentity
    from cerebro.harness import StepSnapshotId
    from tests.harness_phase1c import running_turn

    turn = await running_turn(store, occurrence="barrier-identity-only")
    identity = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=0,
        turn_version_at_creation=turn.state_version,
        created_at=NOW,
    )
    _, turn = await store.commit_snapshot_identity(
        identity, expected_turn_version=turn.state_version
    )
    binding = catalog_entry(mcp_key(), generation="g1").binding
    with pytest.raises(HarnessStateError, match="only an executable snapshot"):
        await store.commit_executable_call_checkpoint(
            agent_turn_id=turn.id,
            snapshot_id=identity.snapshot_id,
            attempt_id=InferenceAttemptId.generate(),
            tool_call_item_id="item_missing",
            call_id=CerebroCallId.generate(),
            binding=binding,
            expected_turn_version=turn.state_version,
            expected_history_version=0,
            expected_replay_version=0,
            at=NOW,
        )


@pytest.mark.asyncio
async def test_one_tool_call_item_cannot_create_two_execution_identities(test_db: Settings):
    """E: a second CerebroCallId for one finalized call would be a second effect."""
    store = HarnessStore()
    fixture = await executable_call(store, catalog(), occurrence="barrier-one-identity")
    turn = await fixture.reload()
    binding = fixture.snapshot.tool_plan.binding_for(mcp_key())
    common = dict(
        agent_turn_id=turn.id,
        snapshot_id=fixture.snapshot.snapshot_id,
        attempt_id=fixture.attempt.attempt_id,
        tool_call_item_id=fixture.call_item.item_id,
        binding=binding,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    # Re-checkpointing the same call is refused by the one-execution-per-call rule.
    with pytest.raises(DuplicateHarnessIdentity, match="already has execution identity"):
        await store.commit_executable_call_checkpoint(**common, call_id=fixture.call_id)
    # Minting a fresh identity for the same finalized call is refused one step earlier: the
    # persisted item does not carry it, so barrier condition D is already false.
    with pytest.raises(HarnessStateError, match="does not carry this CerebroCallId"):
        await store.commit_executable_call_checkpoint(
            **common, call_id=CerebroCallId.generate()
        )
    assert await _tool_execution_count() == 1


@pytest.mark.asyncio
async def test_e2_requires_a_durable_operation_key_before_dispatch_eligibility(test_db: Settings):
    """E2: a `stable_idempotency_key` tool is not executable without its durable key."""
    store = HarnessStore()
    from tests.harness_phase1c import KEYED

    live = FakeToolCatalog([catalog_entry(mcp_key(), generation="g1", capability=KEYED)])
    turn, snapshot, attempt = await snapshotted_turn(store, live, occurrence="e2")
    admission = await admit_output(
        store, turn, snapshot, attempt, [tool_call(attempt, mcp_key())]
    )
    stored_call = admission.accepted[0]
    turn = await store.get_turn(turn.id)
    binding = snapshot.tool_plan.binding_for(mcp_key())
    common = dict(
        agent_turn_id=turn.id,
        snapshot_id=snapshot.snapshot_id,
        attempt_id=attempt.attempt_id,
        tool_call_item_id=stored_call.item_id,
        call_id=stored_call.call_id,
        binding=binding,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    with pytest.raises(HarnessStateError, match="E2 requires a durable operation key"):
        await store.commit_executable_call_checkpoint(**common)
    assert await _tool_execution_count() == 0

    checkpoint = await store.commit_executable_call_checkpoint(
        **common, stable_operation_key="op-1"
    )
    assert checkpoint.execution.execution.stable_operation_key == "op-1"
    assert checkpoint.execution.execution.dispatch_eligible is True


@pytest.mark.asyncio
async def test_f05_barrier_is_all_or_nothing_and_pre_barrier_state_invokes_nothing(
    test_db: Settings, monkeypatch: pytest.MonkeyPatch
):
    """F-05: an injected failure inside the barrier commits none of D/E/E2/I/J/K/L."""
    store = HarnessStore()
    live = catalog()
    turn, snapshot, attempt = await snapshotted_turn(store, live, occurrence="f05-atomic")
    admission = await admit_output(
        store, turn, snapshot, attempt, [tool_call(attempt, mcp_key())]
    )
    stored_call = admission.accepted[0]
    turn = await store.get_turn(turn.id)
    version_before = turn.state_version
    events_before = len(await store.list_turn_events(turn.id))
    binding = snapshot.tool_plan.binding_for(mcp_key())

    import cerebro.harness.store as store_module

    real_append = store_module._append_event

    async def _explode(conn, current_turn, event_type, **kwargs):
        if event_type == "tool.call_admitted":
            raise RuntimeError("injected crash after the ToolExecution insert")
        return await real_append(conn, current_turn, event_type, **kwargs)

    monkeypatch.setattr(store_module, "_append_event", _explode)

    with pytest.raises(RuntimeError, match="injected crash"):
        await store.commit_executable_call_checkpoint(
            agent_turn_id=turn.id,
            snapshot_id=snapshot.snapshot_id,
            attempt_id=attempt.attempt_id,
            tool_call_item_id=stored_call.item_id,
            call_id=stored_call.call_id,
            binding=binding,
            expected_turn_version=turn.state_version,
            expected_history_version=await store.history_version(turn.conversation_turn_id),
            expected_replay_version=await store.replay_version(turn.conversation_turn_id),
            at=NOW,
        )

    monkeypatch.undo()
    await db.close()
    await db.connect(test_db.db_path)

    assert await _tool_execution_count() == 0
    recovered = await store.get_turn(turn.id)
    assert recovered.state_version == version_before
    assert len(await store.list_turn_events(turn.id)) == events_before
    # The finalized call item survives; it just is not executable.
    items = await store.list_inference_items(turn.conversation_turn_id)
    assert [type(item) for item in items] == [ToolCallItem]


@pytest.mark.asyncio
async def test_f05_recovery_after_the_barrier_sees_exactly_one_stable_call(test_db: Settings):
    """F-05: once the barrier commits, restart finds one CerebroCallId and one snapshot set."""
    store = HarnessStore()
    fixture = await executable_call(
        store, catalog(), occurrence="f05-after", stable_operation_key=None
    )
    gateway = FakeExecutorGateway()
    await db.close()
    await db.connect(test_db.db_path)

    rows = await db.fetch_all("SELECT * FROM tool_executions")
    assert len(rows) == 1
    stored = await store.get_tool_execution(fixture.call_id)
    assert stored.execution.dispatch_state == "not_dispatched"
    assert stored.execution.step_snapshot_id == fixture.snapshot.snapshot_id
    snapshot = await store.get_step_snapshot(stored.execution.step_snapshot_id)
    assert snapshot == fixture.snapshot
    assert gateway.invocations == []

    # And the call is still executable exactly once from that durable state.
    runtime = HarnessToolRuntime(
        store, catalog=fixture.catalog, gateway=gateway, artifacts=_artifacts(test_db)
    )
    outcome = await runtime.execute_call(fixture.call_id)
    assert outcome.disposition == "resolved_known"
    assert gateway.count_for("g1") == 1


def _artifacts(settings: Settings):
    from cerebro.harness import ArtifactStore

    return ArtifactStore(settings.data_dir / "harness_artifacts")
