"""Adversarial persistence and recovery tests for Harness v1 Phase 1B."""

import asyncio
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from cerebro import db
from cerebro.config import Settings
from cerebro.harness import (
    AgentTurn,
    AgentTurnId,
    CausalWakeKey,
    CerebroCallId,
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
from cerebro.harness.exceptions import (
    DuplicateHarnessIdentity,
    HarnessStateError,
    StaleHarnessWrite,
    UnsupportedFormatVersion,
)
from cerebro.harness.recovery import TurnRecoveryDriver
from cerebro.harness.serialization import canonical_json
from cerebro.harness.store import HarnessStore, StepSnapshotIdentity
from cerebro.db import _split_sql_statements

NOW = "2026-08-30T12:00:00+00:00"
LATER = "2026-08-30T12:01:00+00:00"
LATEST = "2026-08-30T12:02:00+00:00"


def make_turn(
    *,
    occurrence: str = "manual-1",
    wake_kind: str = "explicit_turn",
    trigger_message_id: int | None = None,
    conversation_id: ConversationTurnId | None = None,
    created_at: str = NOW,
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
        created_at=created_at,
        updated_at=created_at,
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
    *,
    occurrence: str = "manual-1",
) -> tuple[AgentTurn, ToolExecution]:
    turn, snapshot, attempt = await running_turn_with_attempt(store, occurrence=occurrence)
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


async def multiple_tool_execution_fixture(
    store: HarnessStore,
    *,
    occurrence: str,
    count: int = 2,
) -> tuple[AgentTurn, list[ToolExecution]]:
    """Admit several tool calls on one turn without dispatching any of them."""
    turn, snapshot, attempt = await running_turn_with_attempt(store, occurrence=occurrence)
    calls = [
        ToolCallItem(
            item_id=InferenceItemId.generate(),
            origin="provider_attempt",
            producing_attempt_id=attempt.attempt_id,
            call_id=CerebroCallId.generate(),
            tool_key=tool_key(),
            input=JsonToolInput(value={"body": f"call-{index}"}),
        )
        for index in range(count)
    ]
    stored_calls, _ = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        calls,
        expected_history_version=0,
        at=NOW,
    )
    executions = [
        ToolExecution(
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
        for call in stored_calls
    ]
    for execution in executions:
        await store.create_tool_execution(execution, expected_turn_version=turn.state_version)
    return turn, executions


async def raw_write(sql: str, params: tuple[object, ...] = ()) -> None:
    """Execute one adversarial SQL mutation with transaction rollback on trigger failure."""
    async def _tx(conn):
        await conn.execute(sql, params)

    await db.run_in_writer(_tx)


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
        "idx_inference_attempts_snapshot_generation",
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
    _, turn = await store.abandon_attempt(
        attempt.attempt_id,
        "attempt abandoned after restart",
        expected_attempt_version=0,
        expected_turn_version=turn.state_version,
        at=LATER,
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
    decisions = await TurnRecoveryDriver(store).scan(at=LATER)
    assert decisions[0].turn_id == attempt.agent_turn_id
    recovered = await store.get_turn(attempt.agent_turn_id)
    assert recovered.lifecycle == "suspended"
    assert "corrupt or missing durable references" in recovered.suspension_reason


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
    triggers = {
        row["name"]
        for row in await db.fetch_all("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    assert triggers == {
        "trg_agent_turns_version_and_lifecycle",
        "trg_step_snapshots_immutable",
        "trg_inference_attempts_monotonic",
        "trg_inference_items_identity_and_supersession",
        "trg_tool_executions_monotonic",
    }
    await db.close()


@pytest.mark.asyncio
async def test_escaped_call_prefix_survives_abandonment_after_reopen(test_db: Settings):
    """TG-01: durable ToolExecution truth protects AR-02 history after restart."""
    store = HarnessStore()
    turn, snapshot, attempt = await running_turn_with_attempt(store, occurrence="tg-01")
    stored_attempt, turn = await store.mark_attempt_dispatch_may_have_escaped(
        attempt.attempt_id,
        expected_attempt_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    prefix = MessageItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt.attempt_id,
        role="assistant",
        content=[TextPart(text="causal prefix")],
        provenance=Provenance(source_kind="provider_attempt", source_id="lmstudio"),
    )
    call = ToolCallItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt.attempt_id,
        call_id=CerebroCallId.generate(),
        tool_key=tool_key(),
        input=JsonToolInput(value={"body": "escaped"}),
    )
    trailing = prefix.model_copy(
        update={"item_id": InferenceItemId.generate(), "content": [TextPart(text="trailing")]}
    )
    stored_items, history_version = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        [prefix, call, trailing],
        expected_history_version=0,
        at=NOW,
    )
    call = stored_items[1]
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
    _, turn = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )

    events_before = await store.list_turn_events(turn.id)
    with pytest.raises(HarnessStateError, match="durable abandonment"):
        await store.supersede_attempt_items(
            turn.conversation_turn_id,
            attempt.attempt_id,
            expected_history_version=history_version,
            reason="not abandoned",
            at=LATER,
        )
    assert await store.history_version(turn.conversation_turn_id) == history_version
    assert await store.list_turn_events(turn.id) == events_before

    await db.close()
    await db.connect(test_db.db_path)
    await db.migrate()
    _, turn = await store.abandon_attempt(
        attempt.attempt_id,
        "restart replacement",
        expected_attempt_version=stored_attempt.row_version,
        expected_turn_version=turn.state_version,
        at=LATER,
    )
    superseded, new_version = await store.supersede_attempt_items(
        turn.conversation_turn_id,
        attempt.attempt_id,
        expected_history_version=history_version,
        reason="restart replacement",
        at=LATEST,
    )
    assert [item.item_id for item in superseded] == [stored_items[2].item_id]
    assert new_version == history_version + 1
    active = await store.list_inference_items(turn.conversation_turn_id)
    assert [item.item_id for item in active] == [stored_items[0].item_id, stored_items[1].item_id]


@pytest.mark.asyncio
async def test_recovery_isolates_missing_reference_and_malformed_candidate(test_db: Settings):
    """TG-02: damaged early candidates cannot prevent later conservative suspension."""
    store = HarnessStore()
    damaged, _, _ = await running_turn_with_attempt(store, occurrence="tg-02-damaged")
    malformed = await store.admit_turn(
        make_turn(occurrence="tg-02-malformed", created_at="2026-08-30T12:00:30+00:00")
    )
    later = await store.admit_turn(
        make_turn(occurrence="tg-02-later", created_at="2026-08-30T12:00:59+00:00")
    )
    missing_attempt_id = InferenceAttemptId.generate()
    row = await db.fetch_one("SELECT payload_json FROM agent_turns WHERE id=?", (str(damaged.id),))
    payload = json.loads(row["payload_json"])
    payload["state_version"] = damaged.state_version + 1
    payload["active_inference_attempt_id"] = str(missing_attempt_id)
    await raw_write(
        "UPDATE agent_turns SET state_version=?,active_inference_attempt_id=?,payload_json=? "
        "WHERE id=?",
        (
            damaged.state_version + 1,
            str(missing_attempt_id),
            canonical_json(payload),
            str(damaged.id),
        ),
    )
    await raw_write(
        "UPDATE agent_turns SET format_version=99,state_version=state_version+1 WHERE id=?",
        (str(malformed.id),),
    )

    decisions = await TurnRecoveryDriver(store).scan(at=LATER)
    assert [decision.turn_id for decision in decisions] == [damaged.id, later.id]
    repaired = await store.get_turn(damaged.id)
    assert repaired.lifecycle == "suspended"
    assert "corrupt or missing durable references" in repaired.suspension_reason
    assert (await store.get_turn(later.id)).lifecycle == "suspended"


@pytest.mark.asyncio
async def test_recovery_stale_cas_accepts_new_truth_and_continues(test_db: Settings):
    """TG-03: a recovery CAS race is isolated from later turns."""
    first = await HarnessStore().admit_turn(make_turn(occurrence="tg-03-first"))
    second = await HarnessStore().admit_turn(
        make_turn(occurrence="tg-03-second", created_at=LATER)
    )

    class StaleOnceStore(HarnessStore):
        def __init__(self, racing_turn_id: AgentTurnId) -> None:
            self.racing_turn_id = racing_turn_id
            self.injected = False

        async def transition_turn(self, turn_id, **kwargs):
            if turn_id == self.racing_turn_id and not self.injected:
                self.injected = True
                await super().transition_turn(
                    turn_id,
                    expected_version=kwargs["expected_version"],
                    lifecycle="suspended",
                    suspension_reason="concurrent recovery won",
                    at=kwargs["at"],
                )
                raise StaleHarnessWrite("deterministic recovery race")
            return await super().transition_turn(turn_id, **kwargs)

    racing_store = StaleOnceStore(first.id)
    decisions = await TurnRecoveryDriver(racing_store).scan(at=LATEST)
    assert racing_store.injected is True
    assert [decision.turn_id for decision in decisions] == [first.id, second.id]
    assert decisions[0].action == "already_suspended"
    assert (await racing_store.get_turn(second.id)).lifecycle == "suspended"


@pytest.mark.asyncio
async def test_attempt_generation_is_scoped_to_snapshot(test_db: Settings):
    """TG-04: generation 1 is reusable on a later semantic step, but not the same step."""
    store = HarnessStore()
    turn, first_snapshot, first_attempt = await running_turn_with_attempt(
        store, occurrence="tg-04"
    )
    second_snapshot = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=1,
        turn_version_at_creation=turn.state_version,
        created_at=LATER,
    )
    _, turn = await store.commit_snapshot_identity(
        second_snapshot, expected_turn_version=turn.state_version
    )
    second_attempt = InferenceAttempt(
        attempt_id=InferenceAttemptId.generate(),
        agent_turn_id=turn.id,
        step_snapshot_id=second_snapshot.snapshot_id,
        attempt_generation=1,
        turn_version_admitted=turn.state_version,
        request_semantic_hash="b" * 64,
    )
    _, turn = await store.admit_inference_attempt(
        second_attempt, expected_turn_version=turn.state_version, at=LATER
    )
    duplicate_generation = second_attempt.model_copy(
        update={
            "attempt_id": InferenceAttemptId.generate(),
            "turn_version_admitted": turn.state_version,
            "request_semantic_hash": "c" * 64,
        }
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        await store.admit_inference_attempt(
            duplicate_generation,
            expected_turn_version=turn.state_version,
            at=LATEST,
        )
    stored_first = await store.get_inference_attempt(first_attempt.attempt_id)
    stored_second = await store.get_inference_attempt(second_attempt.attempt_id)
    assert stored_first.attempt.step_snapshot_id == first_snapshot.snapshot_id
    assert stored_second.attempt.step_snapshot_id == second_snapshot.snapshot_id
    assert stored_first.attempt.attempt_generation == stored_second.attempt.attempt_generation == 1


@pytest.mark.asyncio
async def test_terminal_turn_rejects_new_effect_admission_and_dispatch(test_db: Settings):
    """TG-05: every post-terminal effect-authorization gate rolls back atomically."""
    store = HarnessStore()
    turn, snapshot, attempt = await running_turn_with_attempt(store, occurrence="tg-05")
    calls = [
        ToolCallItem(
            item_id=InferenceItemId.generate(),
            origin="provider_attempt",
            producing_attempt_id=attempt.attempt_id,
            call_id=CerebroCallId.generate(),
            tool_key=tool_key(),
            input=JsonToolInput(value={"body": str(index)}),
        )
        for index in range(2)
    ]
    stored_calls, _ = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        calls,
        expected_history_version=0,
        at=NOW,
    )

    def execution_for(call: ToolCallItem) -> ToolExecution:
        return ToolExecution(
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

    admitted_execution = execution_for(stored_calls[0])
    pending_execution = execution_for(stored_calls[1])
    await store.create_tool_execution(
        admitted_execution, expected_turn_version=turn.state_version
    )
    terminal = await store.transition_turn(
        turn.id,
        expected_version=turn.state_version,
        lifecycle="cancelled",
        at=LATER,
    )
    baseline_attempt = await store.get_inference_attempt(attempt.attempt_id)
    baseline_tool = await store.get_tool_execution(admitted_execution.call_id)
    baseline_events = await store.list_turn_events(turn.id)

    new_snapshot = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=1,
        turn_version_at_creation=terminal.state_version,
        created_at=LATEST,
    )
    with pytest.raises(HarnessStateError, match="terminal AgentTurn"):
        await store.commit_snapshot_identity(
            new_snapshot, expected_turn_version=terminal.state_version
        )
    new_attempt = InferenceAttempt(
        attempt_id=InferenceAttemptId.generate(),
        agent_turn_id=turn.id,
        step_snapshot_id=snapshot.snapshot_id,
        attempt_generation=2,
        turn_version_admitted=terminal.state_version,
        request_semantic_hash="d" * 64,
    )
    with pytest.raises(HarnessStateError, match="terminal AgentTurn"):
        await store.admit_inference_attempt(
            new_attempt, expected_turn_version=terminal.state_version, at=LATEST
        )
    with pytest.raises(HarnessStateError, match="terminal AgentTurn"):
        await store.mark_attempt_dispatch_may_have_escaped(
            attempt.attempt_id,
            expected_attempt_version=0,
            expected_turn_version=terminal.state_version,
            at=LATEST,
        )
    pending_execution = pending_execution.model_copy(
        update={"admitted_turn_version": terminal.state_version}
    )
    with pytest.raises(HarnessStateError, match="terminal AgentTurn"):
        await store.create_tool_execution(
            pending_execution, expected_turn_version=terminal.state_version
        )
    with pytest.raises(HarnessStateError, match="terminal AgentTurn"):
        await store.mark_tool_dispatch_may_have_escaped(
            admitted_execution.call_id,
            expected_tool_version=0,
            expected_turn_version=terminal.state_version,
            at=LATEST,
        )

    assert await store.get_turn(turn.id) == terminal
    assert await store.get_inference_attempt(attempt.attempt_id) == baseline_attempt
    assert await store.get_tool_execution(admitted_execution.call_id) == baseline_tool
    assert await store.list_turn_events(turn.id) == baseline_events
    assert await db.fetch_one(
        "SELECT COUNT(*) AS count FROM inference_attempts WHERE agent_turn_id=?",
        (str(turn.id),),
    ) == {"count": 1}
    assert await db.fetch_one(
        "SELECT COUNT(*) AS count FROM tool_executions WHERE agent_turn_id=?",
        (str(turn.id),),
    ) == {"count": 1}


@pytest.mark.asyncio
async def test_provider_dispatch_requires_current_attempt_and_snapshot(test_db: Settings):
    """TG-06: a superseded current projection cannot authorize provider dispatch."""
    store = HarnessStore()
    turn, _, first_attempt = await running_turn_with_attempt(store, occurrence="tg-06")
    second_snapshot = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=1,
        turn_version_at_creation=turn.state_version,
        created_at=LATER,
    )
    _, turn = await store.commit_snapshot_identity(
        second_snapshot, expected_turn_version=turn.state_version
    )
    second_attempt = InferenceAttempt(
        attempt_id=InferenceAttemptId.generate(),
        agent_turn_id=turn.id,
        step_snapshot_id=second_snapshot.snapshot_id,
        attempt_generation=1,
        turn_version_admitted=turn.state_version,
        request_semantic_hash="e" * 64,
    )
    _, turn = await store.admit_inference_attempt(
        second_attempt, expected_turn_version=turn.state_version, at=LATER
    )
    events_before = await store.list_turn_events(turn.id)
    with pytest.raises(HarnessStateError, match="active inference attempt"):
        await store.mark_attempt_dispatch_may_have_escaped(
            first_attempt.attempt_id,
            expected_attempt_version=0,
            expected_turn_version=turn.state_version,
            at=LATEST,
        )
    assert (await store.get_inference_attempt(first_attempt.attempt_id)).row_version == 0
    assert (await store.get_turn(turn.id)).state_version == turn.state_version
    assert await store.list_turn_events(turn.id) == events_before


@pytest.mark.asyncio
async def test_current_step_projection_cannot_rewind(test_db: Settings):
    """TG-07: snapshot identity admission preserves monotonic step projection."""
    store = HarnessStore()
    turn = await store.admit_turn(make_turn(occurrence="tg-07"))
    turn = await store.transition_turn(turn.id, expected_version=0, lifecycle="running", at=NOW)
    step_one = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=1,
        turn_version_at_creation=turn.state_version,
        created_at=NOW,
    )
    _, turn = await store.commit_snapshot_identity(step_one, expected_turn_version=turn.state_version)
    rewind = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=0,
        turn_version_at_creation=turn.state_version,
        created_at=LATER,
    )
    with pytest.raises(HarnessStateError, match="cannot rewind"):
        await store.commit_snapshot_identity(rewind, expected_turn_version=turn.state_version)
    unchanged = await store.get_turn(turn.id)
    assert unchanged.current_step_index == 1
    assert unchanged.active_step_snapshot_id == step_one.snapshot_id
    assert await db.fetch_one(
        "SELECT snapshot_id FROM step_snapshots WHERE snapshot_id=?", (str(rewind.snapshot_id),)
    ) is None


@pytest.mark.asyncio
async def test_terminal_finalization_is_immutable_but_attention_can_reconcile(test_db: Settings):
    """TG-08: SQL freezes terminal identity while existing uncertain effects may resolve."""
    store = HarnessStore()
    turn, execution = await tool_execution_fixture(store, occurrence="tg-08")
    stored, turn = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    terminal = await store.transition_turn(
        turn.id,
        expected_version=turn.state_version,
        lifecycle="completed",
        product_outcome_kind="topic_pass",
        at=LATER,
    )
    row = await db.fetch_one("SELECT payload_json FROM agent_turns WHERE id=?", (str(turn.id),))
    payload = json.loads(row["payload_json"])
    payload.update(
        state_version=terminal.state_version + 1,
        product_outcome_kind="topic_silent_stop",
        failure_kind="rewritten",
        failure_detail={"reason": "rewritten"},
    )
    with pytest.raises(sqlite3.IntegrityError, match="finalization identity cannot change"):
        await raw_write(
            "UPDATE agent_turns SET state_version=state_version+1,"
            "product_outcome_kind='topic_silent_stop',failure_kind='rewritten',payload_json=? "
            "WHERE id=?",
            (canonical_json(payload), str(turn.id)),
        )
    _, reconciled = await store.resolve_tool_known(
        execution.call_id,
        "success",
        expected_tool_version=stored.row_version,
        expected_turn_version=terminal.state_version,
        at=LATEST,
    )
    assert reconciled.lifecycle == "completed"
    assert reconciled.product_outcome_kind == "topic_pass"
    assert reconciled.failure_kind is None
    assert reconciled.needs_attention is False
    assert reconciled.unresolved_effect_count == 0


@pytest.mark.asyncio
async def test_cross_turn_tool_call_cannot_authorize_execution(test_db: Settings):
    """TG-09: ToolExecution admission enforces the ToolCallItem's turn owner."""
    store = HarnessStore()
    turn_a, snapshot_a, _ = await running_turn_with_attempt(store, occurrence="tg-09-a")
    turn_b, _, attempt_b = await running_turn_with_attempt(store, occurrence="tg-09-b")
    call_b = ToolCallItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt_b.attempt_id,
        call_id=CerebroCallId.generate(),
        tool_key=tool_key(),
        input=JsonToolInput(value={"body": "turn-b"}),
    )
    stored_calls, _ = await store.append_inference_items(
        turn_b.conversation_turn_id,
        turn_b.id,
        [call_b],
        expected_history_version=0,
        at=NOW,
    )
    call_b = stored_calls[0]
    cross_turn = ToolExecution(
        call_id=call_b.call_id,
        agent_turn_id=turn_a.id,
        step_snapshot_id=snapshot_a.snapshot_id,
        tool_call_item_id=call_b.item_id,
        tool_key=call_b.tool_key,
        admitted_turn_version=turn_a.state_version,
        binding_generation=ToolBindingGeneration.generate(),
        recovery_capability=ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="never_automatic_repeat"
        ),
        admitted_at=NOW,
    )
    events_before = await store.list_turn_events(turn_a.id)
    with pytest.raises(HarnessStateError, match="does not belong"):
        await store.create_tool_execution(cross_turn, expected_turn_version=turn_a.state_version)
    assert await db.fetch_one(
        "SELECT call_id FROM tool_executions WHERE call_id=?", (str(call_b.call_id),)
    ) is None
    assert await store.list_turn_events(turn_a.id) == events_before


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["lifecycle", "attention"])
async def test_filtered_agent_turn_corruption_fails_closed(
    test_db: Settings, corruption: str
):
    """TG-10: duplicated lifecycle and attention columns cannot hide canonical turns."""
    store = HarnessStore()
    if corruption == "lifecycle":
        turn = await store.admit_turn(make_turn(occurrence="tg-10-lifecycle"))
        await raw_write(
            "UPDATE agent_turns SET lifecycle='failed',state_version=state_version+1 WHERE id=?",
            (str(turn.id),),
        )
        with pytest.raises(HarnessStateError, match="disagrees with its canonical payload"):
            await store.list_non_terminal_turns(0)
    else:
        turn, execution = await tool_execution_fixture(store, occurrence="tg-10-attention")
        _, turn = await store.mark_tool_dispatch_may_have_escaped(
            execution.call_id,
            expected_tool_version=0,
            expected_turn_version=turn.state_version,
            at=NOW,
        )
        await raw_write(
            "UPDATE agent_turns SET needs_attention=0,unresolved_effect_count=0,"
            "state_version=state_version+1 WHERE id=?",
            (str(turn.id),),
        )
        with pytest.raises(HarnessStateError, match="disagrees with its canonical payload"):
            await store.list_turns_needing_attention()


@pytest.mark.asyncio
async def test_sql_only_supersession_cannot_hide_history(test_db: Settings):
    """TG-11: history validates canonical supersession before filtering."""
    store = HarnessStore()
    turn = await store.admit_turn(make_turn(occurrence="tg-11"))
    items, _ = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        [user_item("still active")],
        expected_history_version=0,
        at=NOW,
    )
    await raw_write(
        "UPDATE inference_items SET superseded_at=?,superseded_reason=? WHERE item_id=?",
        (LATER, "sql only", str(items[0].item_id)),
    )
    with pytest.raises(HarnessStateError, match="superseded_at disagrees"):
        await store.list_inference_items(turn.conversation_turn_id)


@pytest.mark.asyncio
async def test_filtered_tool_execution_corruption_fails_closed(test_db: Settings):
    """TG-12: SQL resolution filters cannot hide canonical uncertainty."""
    store = HarnessStore()
    turn, execution = await tool_execution_fixture(store, occurrence="tg-12")
    _, turn = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    await raw_write(
        "UPDATE tool_executions SET row_version=row_version+1,dispatch_state='resolved',"
        "resolution_kind='known',resolution_status='success',resolved_at=? WHERE call_id=?",
        (LATER, str(execution.call_id)),
    )
    with pytest.raises(HarnessStateError, match="dispatch_state disagrees"):
        await store.list_unresolved_tool_executions(turn.id)


@pytest.mark.asyncio
async def test_two_uncertain_calls_preserve_aggregate_attention(test_db: Settings):
    """TG-13: resolving one call cannot clear another call's uncertain truth."""
    store = HarnessStore()
    turn, executions = await multiple_tool_execution_fixture(store, occurrence="tg-13")
    stored = []
    for execution in executions:
        value, turn = await store.mark_tool_dispatch_may_have_escaped(
            execution.call_id,
            expected_tool_version=0,
            expected_turn_version=turn.state_version,
            at=NOW,
        )
        stored.append(value)
    assert turn.unresolved_effect_count == 2
    _, turn = await store.resolve_tool_known(
        executions[0].call_id,
        "success",
        expected_tool_version=stored[0].row_version,
        expected_turn_version=turn.state_version,
        at=LATER,
    )
    assert turn.needs_attention is True
    assert turn.unresolved_effect_count == 1
    _, turn = await store.resolve_tool_indeterminate(
        executions[1].call_id,
        "no recovery authority",
        expected_tool_version=stored[1].row_version,
        expected_turn_version=turn.state_version,
        at=LATEST,
    )
    assert turn.needs_attention is True
    assert turn.unresolved_effect_count == 1


@pytest.mark.asyncio
async def test_terminal_turn_retains_remaining_multi_call_attention(test_db: Settings):
    """TG-14: terminal control state cannot hide another unresolved effect."""
    store = HarnessStore()
    turn, executions = await multiple_tool_execution_fixture(store, occurrence="tg-14")
    stored = []
    for execution in executions:
        value, turn = await store.mark_tool_dispatch_may_have_escaped(
            execution.call_id,
            expected_tool_version=0,
            expected_turn_version=turn.state_version,
            at=NOW,
        )
        stored.append(value)
    turn = await store.transition_turn(
        turn.id,
        expected_version=turn.state_version,
        lifecycle="cancelled",
        at=LATER,
    )
    _, turn = await store.resolve_tool_known(
        executions[0].call_id,
        "success",
        expected_tool_version=stored[0].row_version,
        expected_turn_version=turn.state_version,
        at=LATEST,
    )
    assert turn.lifecycle == "cancelled"
    assert turn.needs_attention is True
    assert turn.unresolved_effect_count == 1
    assert [value.id for value in await store.list_turns_needing_attention()] == [turn.id]
    unresolved = await store.list_unresolved_tool_executions(turn.id)
    assert [value.execution.call_id for value in unresolved] == [executions[1].call_id]


@pytest.mark.asyncio
async def test_migration_triggers_enforce_every_monotonic_boundary(test_db: Settings):
    """TG-15/TG-16: every 005 trigger fires after upgrading a real 001-004 database."""
    old_dir = test_db.data_dir / "trigger-old-migrations"
    old_dir.mkdir()
    source_dir = Path(__file__).resolve().parents[1] / "cerebro" / "migrations"
    for name in (
        "001_init.sql",
        "002_add_last_read_message_id.sql",
        "003_add_leases.sql",
        "004_agent_quota.sql",
    ):
        shutil.copy2(source_dir / name, old_dir / name)
    database = test_db.data_dir / "trigger-upgrade.db"
    await db.close()
    await db.connect(database)
    assert await db.migrate(old_dir) == [1, 2, 3, 4]
    await db.close()
    await db.connect(database)
    assert await db.migrate() == [5]
    store = HarnessStore()
    turn, snapshot, attempt = await running_turn_with_attempt(store, occurrence="tg-15")
    with pytest.raises(sqlite3.IntegrityError, match="step snapshot identity is immutable"):
        await raw_write(
            "UPDATE step_snapshots SET step_index=step_index+1 WHERE snapshot_id=?",
            (str(snapshot.snapshot_id),),
        )
    stored_attempt, turn = await store.mark_attempt_dispatch_may_have_escaped(
        attempt.attempt_id,
        expected_attempt_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    with pytest.raises(sqlite3.IntegrityError, match="dispatch state cannot rewind"):
        await raw_write(
            "UPDATE inference_attempts SET row_version=row_version+1,dispatch_state='admitted' "
            "WHERE attempt_id=?",
            (str(attempt.attempt_id),),
        )
    extra_items, _ = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        [user_item("supersession trigger")],
        expected_history_version=0,
        at=NOW,
    )
    await raw_write(
        "UPDATE inference_items SET superseded_at=?,superseded_reason=? WHERE item_id=?",
        (LATER, "trigger setup", str(extra_items[0].item_id)),
    )
    with pytest.raises(sqlite3.IntegrityError, match="supersession cannot rewind"):
        await raw_write(
            "UPDATE inference_items SET superseded_at=NULL WHERE item_id=?",
            (str(extra_items[0].item_id),),
        )
    call = ToolCallItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt.attempt_id,
        call_id=CerebroCallId.generate(),
        tool_key=tool_key(),
        input=JsonToolInput(value={"body": "trigger"}),
    )
    calls, _ = await store.append_inference_items(
        turn.conversation_turn_id,
        turn.id,
        [call],
        expected_history_version=1,
        at=NOW,
    )
    call = calls[0]
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
    stored_tool, turn = await store.mark_tool_dispatch_may_have_escaped(
        execution.call_id,
        expected_tool_version=0,
        expected_turn_version=turn.state_version,
        at=NOW,
    )
    with pytest.raises(sqlite3.IntegrityError, match="dispatch state cannot rewind"):
        await raw_write(
            "UPDATE tool_executions SET row_version=row_version+1,dispatch_state='not_dispatched' "
            "WHERE call_id=?",
            (str(execution.call_id),),
        )
    _, turn = await store.resolve_tool_known(
        execution.call_id,
        "success",
        expected_tool_version=stored_tool.row_version,
        expected_turn_version=turn.state_version,
        at=LATER,
    )
    with pytest.raises(sqlite3.IntegrityError, match="resolved tool execution cannot change"):
        await raw_write(
            "UPDATE tool_executions SET row_version=row_version+1,stable_operation_key='changed' "
            "WHERE call_id=?",
            (str(execution.call_id),),
        )
    _, turn = await store.abandon_attempt(
        attempt.attempt_id,
        "trigger test",
        expected_attempt_version=stored_attempt.row_version,
        expected_turn_version=turn.state_version,
        at=LATER,
    )
    with pytest.raises(sqlite3.IntegrityError, match="terminal inference attempt cannot change"):
        await raw_write(
            "UPDATE inference_attempts SET row_version=row_version+1,provider_request_id='changed' "
            "WHERE attempt_id=?",
            (str(attempt.attempt_id),),
        )
    with pytest.raises(sqlite3.IntegrityError, match="state_version must advance exactly once"):
        await raw_write(
            "UPDATE agent_turns SET updated_at=? WHERE id=?", (LATEST, str(turn.id))
        )
    terminal = await store.transition_turn(
        turn.id,
        expected_version=turn.state_version,
        lifecycle="cancelled",
        at=LATEST,
    )
    with pytest.raises(sqlite3.IntegrityError, match="terminal agent_turn lifecycle cannot change"):
        await raw_write(
            "UPDATE agent_turns SET state_version=state_version+1,lifecycle='running' WHERE id=?",
            (str(terminal.id),),
        )


def test_migration_splitter_preserves_complete_trigger_bodies():
    """TG-16: migrations 001-005 split only at complete SQLite statements."""
    migration_dir = Path(__file__).resolve().parents[1] / "cerebro" / "migrations"
    statements_by_file = {
        path.name: _split_sql_statements(path.read_text(encoding="utf-8"))
        for path in sorted(migration_dir.glob("00[1-5]_*.sql"))
    }
    assert list(statements_by_file) == [
        "001_init.sql",
        "002_add_last_read_message_id.sql",
        "003_add_leases.sql",
        "004_agent_quota.sql",
        "005_harness_durable_store.sql",
    ]
    assert all(
        sqlite3.complete_statement(statement)
        for statements in statements_by_file.values()
        for statement in statements
    )
    trigger_statements = [
        statement
        for statement in statements_by_file["005_harness_durable_store.sql"]
        if "CREATE TRIGGER" in statement
    ]
    assert len(trigger_statements) == 5
    assert all(statement.rstrip().endswith("END;") for statement in trigger_statements)
    assert all("RAISE(ABORT" in statement for statement in trigger_statements)


@pytest.mark.asyncio
async def test_causal_hash_text_mismatch_fails_closed(test_db: Settings):
    """TG-17: a stable-hash collision cannot alias a different serialized wake."""
    store = HarnessStore()
    existing = await store.admit_turn(make_turn(occurrence="tg-17-existing"))
    offered = make_turn(occurrence="tg-17-offered")
    await raw_write(
        "UPDATE agent_turns SET causal_wake_hash=?,state_version=state_version+1 WHERE id=?",
        (offered.causal_wake_key.stable_hash(), str(existing.id)),
    )
    with pytest.raises(DuplicateHarnessIdentity, match="hash collision"):
        await store.admit_turn(offered)
    with pytest.raises(DuplicateHarnessIdentity, match="hash collision"):
        await store.get_turn_for_wake(offered.causal_wake_key)


@pytest.mark.asyncio
async def test_shared_conversation_history_interleaves_globally_with_cas(test_db: Settings):
    """TG-18: two AgentTurns share one deterministic conversation sequence and CAS head."""
    store = HarnessStore()
    conversation_id = ConversationTurnId.generate()
    first = await store.admit_turn(
        make_turn(occurrence="tg-18-first", conversation_id=conversation_id)
    )
    second = await store.admit_turn(
        make_turn(occurrence="tg-18-second", conversation_id=conversation_id)
    )
    first_items, version = await store.append_inference_items(
        conversation_id,
        first.id,
        [user_item("first")],
        expected_history_version=0,
        at=NOW,
    )
    second_items, version = await store.append_inference_items(
        conversation_id,
        second.id,
        [user_item("second")],
        expected_history_version=version,
        at=LATER,
    )
    with pytest.raises(StaleHarnessWrite):
        await store.append_inference_items(
            conversation_id,
            first.id,
            [user_item("stale")],
            expected_history_version=1,
            at=LATEST,
        )
    final_items, version = await store.append_inference_items(
        conversation_id,
        first.id,
        [user_item("third")],
        expected_history_version=version,
        at=LATEST,
    )
    await db.close()
    await db.connect(test_db.db_path)
    await db.migrate()
    reopened = await store.list_inference_items(conversation_id)
    assert version == 3
    assert [item.item_id for item in reopened] == [
        first_items[0].item_id,
        second_items[0].item_id,
        final_items[0].item_id,
    ]
    assert [item.agent_turn_id for item in reopened] == [first.id, second.id, first.id]
    assert [item.sequence_no for item in reopened] == [0, 1, 2]


@pytest.mark.asyncio
async def test_unknown_formats_fail_closed_across_persisted_families(test_db: Settings):
    """TG-19: discovery and direct reads reject every future durable family version."""
    store = HarnessStore()
    future_turn = await store.admit_turn(make_turn(occurrence="tg-19-turn"))
    row = await db.fetch_one(
        "SELECT payload_json FROM agent_turns WHERE id=?", (str(future_turn.id),)
    )
    payload = json.loads(row["payload_json"])
    payload.update(format_version=99, state_version=future_turn.state_version + 1)
    await raw_write(
        "UPDATE agent_turns SET format_version=99,state_version=state_version+1,payload_json=? "
        "WHERE id=?",
        (canonical_json(payload), str(future_turn.id)),
    )
    with pytest.raises(UnsupportedFormatVersion, match="AgentTurn format_version 99"):
        await store.list_non_terminal_turns(0)

    item_turn = await store.admit_turn(make_turn(occurrence="tg-19-item"))
    future_item = user_item("future item").model_copy(
        update={"format_version": 99, "agent_turn_id": item_turn.id, "sequence_no": 0}
    )
    await raw_write(
        "INSERT INTO inference_items (item_id,format_version,conversation_turn_id,agent_turn_id,"
        "sequence_no,producing_attempt_id,item_type,superseded_at,superseded_reason,"
        "superseding_attempt_id,payload_json,created_at) "
        "VALUES (?,99,?,?,0,NULL,'message',NULL,NULL,NULL,?,?)",
        (
            str(future_item.item_id),
            str(item_turn.conversation_turn_id),
            str(item_turn.id),
            canonical_json(future_item.model_dump(mode="json")),
            NOW,
        ),
    )
    with pytest.raises(UnsupportedFormatVersion, match="InferenceItem format_version 99"):
        await store.list_inference_items(item_turn.conversation_turn_id)

    tool_turn, execution = await tool_execution_fixture(store, occurrence="tg-19-tool")
    row = await db.fetch_one(
        "SELECT payload_json FROM tool_executions WHERE call_id=?", (str(execution.call_id),)
    )
    payload = json.loads(row["payload_json"])
    payload["format_version"] = 99
    await raw_write(
        "UPDATE tool_executions SET format_version=99,row_version=row_version+1,payload_json=? "
        "WHERE call_id=?",
        (canonical_json(payload), str(execution.call_id)),
    )
    with pytest.raises(UnsupportedFormatVersion, match="ToolExecution format_version 99"):
        await store.list_unresolved_tool_executions(tool_turn.id)

    snapshot_turn = await store.admit_turn(make_turn(occurrence="tg-19-snapshot"))
    future_snapshot = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        format_version=99,
        agent_turn_id=snapshot_turn.id,
        step_index=0,
        turn_version_at_creation=snapshot_turn.state_version,
        created_at=NOW,
    )
    await raw_write(
        "INSERT INTO step_snapshots (snapshot_id,format_version,agent_turn_id,step_index,"
        "turn_version_at_creation,storage_envelope_json,created_at) VALUES (?,99,?,0,0,?,?)",
        (
            str(future_snapshot.snapshot_id),
            str(snapshot_turn.id),
            canonical_json(future_snapshot.model_dump(mode="json")),
            NOW,
        ),
    )
    with pytest.raises(UnsupportedFormatVersion, match="StepSnapshotIdentity format_version 99"):
        await store.get_snapshot_identity(future_snapshot.snapshot_id)

    event = await db.fetch_one(
        "SELECT event_id,payload_json FROM turn_events WHERE agent_turn_id=? ORDER BY event_sequence",
        (str(snapshot_turn.id),),
    )
    payload = json.loads(event["payload_json"])
    payload["event_format_version"] = 99
    await raw_write(
        "UPDATE turn_events SET event_format_version=99,payload_json=? WHERE event_id=?",
        (canonical_json(payload), event["event_id"]),
    )
    with pytest.raises(UnsupportedFormatVersion, match="TurnEvent format_version 99"):
        await store.list_turn_events(snapshot_turn.id)
