"""F-05: the replay/effect checkpoint crash matrix, stage by stage (Phase 1C).

Each stage builds durable state up to one boundary, closes and reopens the database, and then
asserts two things: what recovery can see, and how many times an external executor was invoked.
Every boundary before the atomic barrier must show zero invocations, and every boundary after it
must show exactly one stable `CerebroCallId`, snapshot and operation key.
"""

import pytest

from cerebro import db
from cerebro.config import Settings
from cerebro.harness import ArtifactStore, InferenceAttempt, InferenceAttemptId, ToolResultItem
from cerebro.harness.store import HarnessStore
from cerebro.harness.tool_runtime import HarnessToolRuntime, KnownInvocation
from tests.harness_phase1c import (
    KEYED,
    NOW,
    FakeExecutorGateway,
    FakeToolCatalog,
    admit_output,
    build_snapshot,
    catalog_entry,
    mcp_key,
    running_turn,
    tool_call,
)

STAGES = [
    "pre_snapshot",
    "post_snapshot",
    "post_attempt",
    "post_finalized_output",
    "post_barrier",
    "post_dispatch_mark",
    "post_executor_invocation",
    "post_result_commit",
]

PRE_BARRIER = {"pre_snapshot", "post_snapshot", "post_attempt", "post_finalized_output"}


def keyed_catalog() -> FakeToolCatalog:
    return FakeToolCatalog([catalog_entry(mcp_key(), generation="g1", capability=KEYED)])


async def _count(sql: str) -> int:
    row = await db.fetch_one(sql)
    return row["count"]


async def _drive_to(stage: str, store: HarnessStore, catalog: FakeToolCatalog, settings):
    """Build durable state up to exactly one boundary, and report executor invocations."""
    gateway = FakeExecutorGateway([KnownInvocation(raw_output="charged")])
    artifacts = ArtifactStore(settings.data_dir / "harness_artifacts")

    turn = await running_turn(store, occurrence=f"f05-{stage}")
    if stage == "pre_snapshot":
        return gateway, turn, None

    snapshot = build_snapshot(
        turn,
        catalog,
        security_revocation_epoch=await store.security_revocation_epoch(),
        history_version=await store.history_version(turn.conversation_turn_id),
        replay_version=await store.replay_version(turn.conversation_turn_id),
    )
    snapshot, turn = await store.commit_step_snapshot(
        snapshot, expected_turn_version=turn.state_version
    )
    if stage == "post_snapshot":
        return gateway, turn, None

    attempt = InferenceAttempt(
        attempt_id=InferenceAttemptId.generate(),
        agent_turn_id=turn.id,
        step_snapshot_id=snapshot.snapshot_id,
        turn_version_admitted=turn.state_version,
        request_semantic_hash="e" * 64,
    )
    _, turn = await store.admit_inference_attempt(
        attempt, expected_turn_version=turn.state_version, at=NOW
    )
    if stage == "post_attempt":
        return gateway, turn, None

    admission = await admit_output(
        store, turn, snapshot, attempt, [tool_call(attempt, mcp_key())]
    )
    stored_call = admission.accepted[0]
    turn = await store.get_turn(turn.id)
    if stage == "post_finalized_output":
        return gateway, turn, None

    binding = snapshot.tool_plan.binding_for(mcp_key())
    checkpoint = await store.commit_executable_call_checkpoint(
        agent_turn_id=turn.id,
        snapshot_id=snapshot.snapshot_id,
        attempt_id=attempt.attempt_id,
        tool_call_item_id=stored_call.item_id,
        call_id=stored_call.call_id,
        binding=binding,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        stable_operation_key="op-f05",
        at=NOW,
    )
    turn = checkpoint.turn
    if stage == "post_barrier":
        return gateway, turn, stored_call.call_id

    stored, turn = await store.mark_tool_dispatch_after_barrier(
        stored_call.call_id,
        binding=binding,
        expected_tool_version=checkpoint.execution.row_version,
        expected_turn_version=turn.state_version,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        expected_replay_version=await store.replay_version(turn.conversation_turn_id),
        at=NOW,
    )
    if stage == "post_dispatch_mark":
        return gateway, turn, stored_call.call_id

    if stage == "post_executor_invocation":
        # The executor ran and the process died before anything about the result committed.
        from cerebro.harness.tool_runtime import ToolInvocationRequest

        await gateway.invoke(
            ToolInvocationRequest(
                call_id=stored_call.call_id,
                agent_turn_id=turn.id,
                binding=binding,
                wire_name="payments__charge",
                arguments={"amount": 10},
                stable_operation_key="op-f05",
            )
        )
        return gateway, turn, stored_call.call_id

    runtime = HarnessToolRuntime(
        store, catalog=catalog, gateway=gateway, artifacts=artifacts
    )
    await runtime._invoke_and_resolve(
        stored=stored,
        turn=turn,
        binding=binding,
        wire_name="payments__charge",
        arguments={"amount": 10},
        attempt_number=1,
        at=NOW,
    )
    return gateway, await store.get_turn(turn.id), stored_call.call_id


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.asyncio
async def test_f05_crash_matrix(stage: str, test_db: Settings):
    """Every pre-barrier boundary invokes nothing; every later one keeps one stable call."""
    store = HarnessStore()
    catalog = keyed_catalog()
    gateway, turn, call_id = await _drive_to(stage, store, catalog, test_db)

    await db.close()
    await db.connect(test_db.db_path)

    executions = await _count("SELECT COUNT(*) AS count FROM tool_executions")
    if stage in PRE_BARRIER:
        assert gateway.invocations == []
        assert executions == 0
        assert call_id is None
        return

    # After the barrier there is exactly one execution identity, whatever happened next.
    assert executions == 1
    stored = await store.get_tool_execution(call_id)
    assert stored.execution.call_id == call_id
    assert stored.execution.stable_operation_key == "op-f05"
    snapshot = await store.get_step_snapshot(stored.execution.step_snapshot_id)
    assert snapshot.tool_plan.binding_for(mcp_key()) is not None
    assert stored.execution.binds_exactly(snapshot.tool_plan.binding_for(mcp_key()))

    recovered_turn = await store.get_turn(turn.id)
    results = [
        item
        for item in await store.list_inference_items(recovered_turn.conversation_turn_id)
        if isinstance(item, ToolResultItem)
    ]

    if stage == "post_barrier":
        assert gateway.invocations == []
        assert stored.execution.dispatch_state == "not_dispatched"
        assert results == []
        assert recovered_turn.needs_attention is False
    elif stage == "post_dispatch_mark":
        assert gateway.invocations == []
        assert stored.execution.dispatch_state == "dispatch_may_have_escaped"
        assert results == []
        assert recovered_turn.needs_attention is True
    elif stage == "post_executor_invocation":
        assert len(gateway.invocations) == 1
        assert gateway.invocations[0].stable_operation_key == "op-f05"
        assert stored.execution.dispatch_state == "dispatch_may_have_escaped"
        assert stored.execution.resolution is None
        assert results == []
        # Uncertainty survives; the restart has no evidence the effect did not happen.
        assert recovered_turn.needs_attention is True
        assert recovered_turn.unresolved_effect_count == 1
    else:
        assert len(gateway.invocations) == 1
        assert stored.execution.dispatch_state == "resolved"
        assert stored.execution.resolution.status == "success"
        assert len(results) == 1
        assert results[0].raw_output_ref is not None
        assert recovered_turn.needs_attention is False
        artifacts = await store.list_call_artifacts(call_id)
        assert len(artifacts) == 1


@pytest.mark.asyncio
async def test_raw_output_never_reaches_events_or_operator_surfaces(test_db: Settings):
    """Durable evidence stays in the artifact store; nothing generic carries the payload."""
    from tests.harness_phase1c import executable_call

    store = HarnessStore()
    catalog = FakeToolCatalog([catalog_entry(mcp_key(), generation="g1")])
    fixture = await executable_call(store, catalog, occurrence="redaction")
    secret = "SECRET-RAW-OUTPUT-" + "z" * 200
    gateway = FakeExecutorGateway([KnownInvocation(raw_output=secret)])
    artifacts = ArtifactStore(test_db.data_dir / "harness_artifacts")
    outcome = await HarnessToolRuntime(
        store, catalog=catalog, gateway=gateway, artifacts=artifacts
    ).execute_call(fixture.call_id)

    events = await store.list_turn_events(fixture.turn.id)
    assert secret not in str(events)
    assert secret not in str(outcome.describe())
    index = await store.get_artifact(outcome.artifact["artifact_ref"])
    assert secret not in str(index.describe())
    unresolved = await store.list_unresolved_tool_executions(fixture.turn.id)
    assert secret not in str(unresolved)
    # The complete evidence is still recoverable through the one path that may read it.
    assert await artifacts.read(index.artifact_ref) == secret


@pytest.mark.asyncio
async def test_existing_phase_1b_harness_data_survives_the_006_upgrade(tmp_path):
    """Migration 006 is additive: Phase 1B rows keep their meaning and gain safe defaults."""
    import shutil
    from pathlib import Path

    old_dir = tmp_path / "through-005"
    old_dir.mkdir()
    source_dir = Path(__file__).resolve().parents[1] / "cerebro" / "migrations"
    for name in (
        "001_init.sql",
        "002_add_last_read_message_id.sql",
        "003_add_leases.sql",
        "004_agent_quota.sql",
        "005_harness_durable_store.sql",
    ):
        shutil.copy2(source_dir / name, old_dir / name)

    database = tmp_path / "through-005.db"
    await db.connect(database)
    assert await db.migrate(old_dir) == [1, 2, 3, 4, 5]

    store = HarnessStore()
    turn = await running_turn(store, occurrence="pre-006")
    items, history_version = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        [],
        expected_history_version=0,
        at=NOW,
    )
    before_turns = await db.fetch_all("SELECT id,state_version,lifecycle FROM agent_turns")
    before_events = await db.fetch_all("SELECT event_id,event_type FROM turn_events")
    await db.close()

    await db.connect(database)
    assert await db.migrate() == [6]
    assert await db.fetch_all("SELECT id,state_version,lifecycle FROM agent_turns") == (
        before_turns
    )
    assert await db.fetch_all("SELECT event_id,event_type FROM turn_events") == before_events

    metadata = await store.metadata()
    assert metadata.schema_epoch == 2
    assert metadata.security_revocation_epoch == 0
    assert await store.replay_version(turn.conversation_turn_id) == 0
    reopened = await store.get_turn(turn.id)
    assert reopened.lifecycle == "running"
    assert items == [] and history_version == 0
    await db.close()
