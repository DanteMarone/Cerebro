"""Adversarial persistence and recovery tests for Harness v1 Phase 1B."""

import asyncio
import json
from pathlib import Path
import shutil

import pytest

from cerebro import db
from cerebro.config import Settings
from cerebro.harness import (
    AgentTurn,
    AgentTurnId,
    CausalWakeKey,
    ConversationTurnId,
    InferenceAttempt,
    InferenceAttemptId,
    InferenceItemId,
    JsonToolInput,
    MessageItem,
    Provenance,
    StepSnapshotId,
    TextPart,
    ToolBindingGeneration,
    ToolCallItem,
    ToolExecution,
    ToolKey,
    ToolRecoveryCapability,
    ToolResultItem,
)
from cerebro.harness.exceptions import HarnessStateError, StaleHarnessWrite
from cerebro.harness.recovery import TurnRecoveryDriver
from cerebro.harness.serialization import canonical_json
from cerebro.harness.store import HarnessStore, StepSnapshotIdentity

NOW = "2026-08-30T12:00:00+00:00"
LATER = "2026-08-30T12:01:00+00:00"


def make_turn(
    *,
    occurrence: str = "manual-1",
    wake_kind: str = "explicit_turn",
    trigger_message_id: int | None = None,
    conversation_id: ConversationTurnId | None = None,
) -> AgentTurn:
    wake = CausalWakeKey(
        wake_kind=wake_kind,
        target_agent_id="jarvis",
        channel_id="channel-1",
        trigger_message_id=trigger_message_id,
        occurrence_id=occurrence if trigger_message_id is None else None,
    )
    return AgentTurn(
        id=AgentTurnId.generate(),
        conversation_turn_id=conversation_id or ConversationTurnId.generate(),
        causal_wake_key=wake,
        trigger_message_id=trigger_message_id,
        channel_id="channel-1",
        agent_id="jarvis",
        created_at=NOW,
        updated_at=NOW,
    )


def user_item(text: str, *, item_id: InferenceItemId | None = None) -> MessageItem:
    return MessageItem(
        item_id=item_id or InferenceItemId.generate(),
        origin="context_projection",
        role="user",
        content=[TextPart(text=text)],
        provenance=Provenance(source_kind="collaboration_message"),
    )


def tool_key() -> ToolKey:
    return ToolKey(source_type="core", source_id="core_tools", namespace="core", name="notify")


async def running_turn_with_attempt(
    store: HarnessStore,
    *,
    occurrence: str = "manual-1",
) -> tuple[AgentTurn, StepSnapshotIdentity, InferenceAttempt]:
    turn = await store.admit_turn(make_turn(occurrence=occurrence))
    turn = await store.transition_turn(
        turn.id, expected_version=0, lifecycle="running", at=NOW
    )
    snapshot = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=0,
        turn_version_at_creation=turn.state_version,
        created_at=NOW,
    )
    _, turn = await store.commit_snapshot_identity(
        snapshot, expected_turn_version=turn.state_version
    )
    attempt = InferenceAttempt(
        attempt_id=InferenceAttemptId.generate(),
        agent_turn_id=turn.id,
        step_snapshot_id=snapshot.snapshot_id,
        turn_version_admitted=turn.state_version,
        request_semantic_hash="a" * 64,
    )
    _, turn = await store.admit_inference_attempt(
        attempt, expected_turn_version=turn.state_version, at=NOW
    )
    return turn, snapshot, attempt


async def tool_execution_fixture(
    store: HarnessStore,
) -> tuple[AgentTurn, ToolExecution]:
    turn, snapshot, attempt = await running_turn_with_attempt(store)
    call = ToolCallItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt.attempt_id,
        call_id="ccall_fixture",
        tool_key=tool_key(),
        input=JsonToolInput(value={"body": "hello"}),
    )
    stored_items, _ = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        [call],
        expected_history_version=0,
        at=NOW,
    )
    call = stored_items[0]
    execution = ToolExecution(
        call_id=call.call_id,
        agent_turn_id=turn.id,
        step_snapshot_id=snapshot.snapshot_id,
        tool_call_item_id=call.item_id,
        tool_key=call.tool_key,
        admitted_turn_version=turn.state_version,
        binding_generation=ToolBindingGeneration.generate(),
        recovery_capability=ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="never_automatic_repeat"
        ),
        admitted_at=NOW,
    )
    await store.create_tool_execution(execution, expected_turn_version=turn.state_version)
    return turn, execution


@pytest.mark.asyncio
async def test_fresh_schema_contains_additive_harness_tables_and_indexes(test_db: Settings):
    tables = {
        row["name"]
        for row in await db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert {
        "harness_metadata",
        "agent_turns",
        "turn_events",
        "step_snapshots",
        "inference_histories",
        "inference_items",
        "inference_attempts",
        "tool_executions",
    }.issubset(tables)
    indexes = {
        row["name"]
        for row in await db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert {
        "idx_agent_turns_recovery",
        "idx_agent_turns_attention",
        "idx_inference_items_conversation_order",
        "idx_inference_items_turn_order",
        "idx_inference_attempts_turn_generation",
        "idx_tool_executions_turn_state",
    }.issubset(indexes)


@pytest.mark.asyncio
async def test_duplicate_causal_admission_converges_under_concurrency(test_db: Settings):
    store = HarnessStore()
    wake_turn = make_turn(occurrence="same-occurrence")
    duplicate = make_turn(
        occurrence="same-occurrence", conversation_id=wake_turn.conversation_turn_id
    )
    first, second = await asyncio.gather(
        store.admit_turn(wake_turn), store.admit_turn(duplicate)
    )
    assert first.id == second.id
    rows = await db.fetch_all("SELECT id FROM agent_turns")
    assert rows == [{"id": str(first.id)}]


@pytest.mark.asyncio
async def test_distinct_occurrence_identity_admits_distinct_turn(test_db: Settings):
    store = HarnessStore()
    first = await store.admit_turn(make_turn(occurrence="manual-1"))
    second = await store.admit_turn(make_turn(occurrence="manual-2"))
    assert first.id != second.id
    assert first.causal_wake_key.serialized() != second.causal_wake_key.serialized()


@pytest.mark.asyncio
async def test_stale_turn_transition_and_terminal_rewind_fail(test_db: Settings):
    store = HarnessStore()
    turn = await store.admit_turn(make_turn())
    running = await store.transition_turn(
        turn.id, expected_version=0, lifecycle="running", at=NOW
    )
    with pytest.raises(StaleHarnessWrite):
        await store.transition_turn(
            turn.id, expected_version=0, lifecycle="suspended", suspension_reason="stale"
        )
    completed = await store.transition_turn(
        turn.id,
        expected_version=running.state_version,
        lifecycle="completed",
        product_outcome_kind="topic_pass",
        at=LATER,
    )
    with pytest.raises(HarnessStateError):
        await store.transition_turn(
            turn.id, expected_version=completed.state_version, lifecycle="running"
        )
    current = await store.get_turn(turn.id)
    assert current.lifecycle == "completed"
    assert current.state_version == completed.state_version


@pytest.mark.asyncio
async def test_compound_item_append_rolls_back_every_write(test_db: Settings):
    store = HarnessStore()
    turn = await store.admit_turn(make_turn())
    duplicate_id = InferenceItemId.generate()
    with pytest.raises(Exception):
        await store.append_inference_items(
            turn.conversation_turn_id,
            turn.id,
            [user_item("first", item_id=duplicate_id), user_item("second", item_id=duplicate_id)],
            expected_history_version=0,
            at=NOW,
        )
    assert await store.list_inference_items(turn.conversation_turn_id) == []
    assert await store.history_version(turn.conversation_turn_id) == 0
    events = await store.list_turn_events(turn.id)
    assert [event["event_type"] for event in events] == ["turn.created"]


@pytest.mark.asyncio
async def test_ordered_conversation_history_survives_close_and_reopen(
    test_db: Settings,
):
    store = HarnessStore()
    turn = await store.admit_turn(make_turn())
    items, version = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        [user_item("one"), user_item("two")],
        expected_history_version=0,
        at=NOW,
    )
    assert version == 2
    await db.close()
    await db.connect(test_db.db_path)
    await db.migrate()
    reopened = await store.list_inference_items(turn.conversation_turn_id)
    assert [item.content[0].text for item in reopened] == ["one", "two"]
    assert [item.sequence_no for item in reopened] == [0, 1]
    assert all(item.agent_turn_id == turn.id for item in reopened)
    assert [item.item_id for item in reopened] == [item.item_id for item in items]


@pytest.mark.asyncio
async def test_attempt_barrier_truth_survives_close_and_reopen(test_db: Settings):
    store = HarnessStore()
    turn, _, attempt = await running_turn_with_attempt(store)
    stored, turn = await store.mark_attempt_dispatch_may_have_escaped(
        attempt.attempt_id,
        expected_attempt_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    assert stored.attempt.may_have_reached_provider is True
    await db.close()
    await db.connect(test_db.db_path)
    await db.migrate()
    reopened = await store.get_inference_attempt(attempt.attempt_id)
    assert reopened.row_version == 1
    assert reopened.attempt.dispatch_state == "dispatch_may_have_escaped"
    assert reopened.attempt.dispatch_barrier_committed is True


@pytest.mark.asyncio
async def test_attempt_item_supersession_is_durable_audit_metadata(test_db: Settings):
    store = HarnessStore()
    turn, _, attempt = await running_turn_with_attempt(store)
    provider_items = [
        MessageItem(
            item_id=InferenceItemId.generate(),
            origin="provider_attempt",
            producing_attempt_id=attempt.attempt_id,
            role="assistant",
            content=[TextPart(text=text)],
            provenance=Provenance(source_kind="provider_attempt", source_id="lmstudio"),
        )
        for text in ("partial one", "partial two")
    ]
    await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        provider_items,
        expected_history_version=0,
        at=NOW,
    )
    superseded, version = await store.supersede_attempt_items(
        turn.conversation_turn_id,
        attempt.attempt_id,
        expected_history_version=2,
        reason="attempt abandoned after restart",
        at=LATER,
    )
    assert version == 3
    assert len(superseded) == 2
    assert await store.list_inference_items(turn.conversation_turn_id) == []
    audit = await store.list_inference_items(
        turn.conversation_turn_id, include_superseded=True
    )
    assert [item.superseded_reason for item in audit] == [
        "attempt abandoned after restart",
        "attempt abandoned after restart",
    ]


@pytest.mark.asyncio
async def test_stale_attempt_transition_is_explicit(test_db: Settings):
    store = HarnessStore()
    turn, _, attempt = await running_turn_with_attempt(store)
    _, turn = await store.mark_attempt_dispatch_may_have_escaped(
        attempt.attempt_id,
        expected_attempt_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    with pytest.raises(StaleHarnessWrite):
        await store.complete_attempt(
            attempt.attempt_id,
            "end_turn",
            expected_attempt_version=0,
            expected_turn_version=turn.state_version,
            at=LATER,
        )


@pytest.mark.asyncio
async def test_cancel_before_dispatch_never_erases_post_barrier_truth(test_db: Settings):
    store = HarnessStore()
    turn, _, attempt = await running_turn_with_attempt(store)
    cancelled, _ = await store.cancel_attempt_before_dispatch(
        attempt.attempt_id,
        expected_attempt_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    assert cancelled.attempt.semantic_state == "cancelled_before_dispatch"
    assert cancelled.attempt.may_have_reached_provider is False

    other_turn, _, other_attempt = await running_turn_with_attempt(
        store, occurrence="manual-2"
    )
    dispatched, other_turn = await store.mark_attempt_dispatch_may_have_escaped(
        other_attempt.attempt_id,
        expected_attempt_version=0,
        expected_turn_version=other_turn.state_version,
        at=NOW,
    )
    with pytest.raises(HarnessStateError):
        await store.cancel_attempt_before_dispatch(
            other_attempt.attempt_id,
            expected_attempt_version=dispatched.row_version,
            expected_turn_version=other_turn.state_version,
            at=LATER,
        )
    persisted = await store.get_inference_attempt(other_attempt.attempt_id)
    assert persisted.attempt.dispatch_barrier_committed is True


@pytest.mark.asyncio
async def test_indeterminate_tool_and_attention_survive_reopen(test_db: Settings):
    store = HarnessStore()
    turn, execution = await tool_execution_fixture(store)
    stored, turn = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    assert stored.execution.dispatch_state == "dispatch_may_have_escaped"
    assert turn.needs_attention is True
    stored, turn = await store.resolve_tool_indeterminate(
        execution.call_id,
        "remote outcome unavailable",
        expected_tool_version=stored.row_version,
        expected_turn_version=turn.state_version,
        at=LATER,
    )
    assert stored.execution.resolution.resolution_kind == "indeterminate"
    assert turn.needs_attention is True
    assert turn.unresolved_effect_count == 1
    await db.close()
    await db.connect(test_db.db_path)
    await db.migrate()
    attention = await store.list_turns_needing_attention()
    unresolved = await store.list_unresolved_tool_executions(turn.id)
    assert [value.id for value in attention] == [turn.id]
    assert unresolved[0].execution.call_id == execution.call_id
    assert unresolved[0].execution.resolution.reason == "remote outcome unavailable"


@pytest.mark.asyncio
async def test_known_tool_resolution_atomically_clears_attention(test_db: Settings):
    store = HarnessStore()
    turn, execution = await tool_execution_fixture(store)
    stored, turn = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    result = ToolResultItem(
        item_id=InferenceItemId.generate(),
        call_id=execution.call_id,
        tool_key=execution.tool_key,
        status="success",
        content=[TextPart(text="sent")],
    )
    stored, turn = await store.resolve_tool_known(
        execution.call_id,
        "success",
        expected_tool_version=stored.row_version,
        expected_turn_version=turn.state_version,
        result_item=result,
        expected_history_version=1,
        at=LATER,
    )
    assert stored.execution.resolution.status == "success"
    assert stored.execution.model_output_item_id == result.item_id
    assert turn.needs_attention is False
    assert turn.unresolved_effect_count == 0
    assert await store.list_unresolved_tool_executions(turn.id) == []
    history = await store.list_inference_items(turn.conversation_turn_id)
    assert [item.item_type for item in history] == ["tool_call", "tool_result"]


@pytest.mark.asyncio
async def test_failed_result_compound_write_preserves_uncertain_truth(test_db: Settings):
    store = HarnessStore()
    turn, execution = await tool_execution_fixture(store)
    stored, turn = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    duplicate_result = ToolResultItem(
        item_id=execution.tool_call_item_id,
        call_id=execution.call_id,
        tool_key=execution.tool_key,
        status="success",
        content=[TextPart(text="would collide")],
    )
    with pytest.raises(Exception):
        await store.resolve_tool_known(
            execution.call_id,
            "success",
            expected_tool_version=stored.row_version,
            expected_turn_version=turn.state_version,
            result_item=duplicate_result,
            expected_history_version=1,
            at=LATER,
        )
    unchanged_execution = await store.get_tool_execution(execution.call_id)
    unchanged_turn = await store.get_turn(turn.id)
    assert unchanged_execution.execution.dispatch_state == "dispatch_may_have_escaped"
    assert unchanged_execution.row_version == stored.row_version
    assert unchanged_turn.needs_attention is True
    assert await store.history_version(turn.conversation_turn_id) == 1


@pytest.mark.asyncio
async def test_recovery_scan_suspends_nonterminal_work_without_effects(test_db: Settings):
    store = HarnessStore()
    queued = await store.admit_turn(make_turn(occurrence="queued"))
    running, execution = await tool_execution_fixture(store)
    _, running = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=running.state_version,
        at=NOW,
    )
    decisions = await TurnRecoveryDriver(store).scan(at=LATER)
    assert [decision.turn_id for decision in decisions] == sorted(
        [queued.id, running.id], key=str
    )
    assert all(decision.action == "suspended" for decision in decisions)
    recovered_queued = await store.get_turn(queued.id)
    recovered_running = await store.get_turn(running.id)
    assert recovered_queued.lifecycle == "suspended"
    assert recovered_running.lifecycle == "suspended"
    assert recovered_running.needs_attention is True
    assert "unresolved tool effect" in recovered_running.suspension_reason
    assert await store.get_tool_execution(execution.call_id)


@pytest.mark.asyncio
async def test_recovery_scan_leaves_existing_suspension_unchanged(test_db: Settings):
    store = HarnessStore()
    turn = await store.admit_turn(make_turn())
    turn = await store.transition_turn(
        turn.id,
        expected_version=0,
        lifecycle="suspended",
        suspension_reason="operator review",
        at=NOW,
    )
    decisions = await TurnRecoveryDriver(store).scan(at=LATER)
    assert decisions[0].action == "already_suspended"
    unchanged = await store.get_turn(turn.id)
    assert unchanged.state_version == turn.state_version
    assert unchanged.suspension_reason == "operator review"


@pytest.mark.asyncio
async def test_unknown_attempt_format_version_fails_closed(test_db: Settings):
    store = HarnessStore()
    _, _, attempt = await running_turn_with_attempt(store)
    payload = await db.fetch_one(
        "SELECT payload_json FROM inference_attempts WHERE attempt_id = ?",
        (str(attempt.attempt_id),),
    )
    body = json.loads(payload["payload_json"])
    body["format_version"] = 99
    future = await db.enqueue_write(
        """
        UPDATE inference_attempts
        SET format_version=99,row_version=row_version+1,payload_json=?
        WHERE attempt_id=?
        """,
        (canonical_json(body), str(attempt.attempt_id)),
    )
    await future
    with pytest.raises(Exception, match="format_version 99"):
        await store.get_inference_attempt(attempt.attempt_id)


@pytest.mark.asyncio
async def test_migration_from_pre_phase1b_schema_preserves_product_data(tmp_path: Path):
    old_dir = tmp_path / "old-migrations"
    old_dir.mkdir()
    source_dir = Path(__file__).resolve().parents[1] / "cerebro" / "migrations"
    for name in (
        "001_init.sql",
        "002_add_last_read_message_id.sql",
        "003_add_leases.sql",
        "004_agent_quota.sql",
    ):
        shutil.copy2(source_dir / name, old_dir / name)
    database = tmp_path / "pre-phase1b.db"
    await db.connect(database)
    assert await db.migrate(old_dir) == [1, 2, 3, 4]
    message_write = await db.enqueue_write(
        """
        INSERT INTO messages (
            channel_id,author_id,author_kind,kind,body,turn_id,depth,created_at,meta_json
        ) VALUES ('channel-1','dante','human','chat','keep me','legacy-turn',0,?, '{}')
        """,
        (NOW,),
    )
    await message_write
    task_write = await db.enqueue_write(
        """
        INSERT INTO tasks (id,title,body,status,created_at,updated_at)
        VALUES ('task-1','Existing','unchanged','pending',?,?)
        """,
        (NOW, NOW),
    )
    await task_write
    tool_write = await db.enqueue_write(
        """
        INSERT INTO tool_calls (id,agent_id,server,tool,args_json,status,started_at)
        VALUES ('legacy-call','jarvis','core','notify','{}','success',?)
        """,
        (NOW,),
    )
    await tool_write
    audit_write = await db.enqueue_write(
        """
        INSERT INTO audit_events (ts,actor_id,actor_kind,action,target,detail_json)
        VALUES (?,'dante','human','test','legacy','{}')
        """,
        (NOW,),
    )
    await audit_write
    before_messages = await db.fetch_all("SELECT * FROM messages")
    before_tasks = await db.fetch_all("SELECT * FROM tasks")
    before_tool_calls = await db.fetch_all("SELECT * FROM tool_calls")
    before_audit_events = await db.fetch_all("SELECT * FROM audit_events")
    await db.close()
    await db.connect(database)
    assert await db.migrate() == [5]
    assert await db.fetch_all("SELECT * FROM messages") == before_messages
    assert await db.fetch_all("SELECT * FROM tasks") == before_tasks
    assert await db.fetch_all("SELECT * FROM tool_calls") == before_tool_calls
    assert await db.fetch_all("SELECT * FROM audit_events") == before_audit_events
    assert await db.fetch_one("SELECT * FROM harness_metadata WHERE singleton=1") is not None
    await db.close()
