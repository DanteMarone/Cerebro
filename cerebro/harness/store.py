"""Durable SQLite repository for Harness v1 canonical execution state.

Harness state stays separate from collaboration messages, product tasks, legacy tool_calls and
audit_events. Compound semantic writes use db.run_in_writer(), the existing BEGIN IMMEDIATE
single-writer path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable

from pydantic import BaseModel, Field

from cerebro import db
from cerebro.harness.attempts import InferenceAttempt, InferenceCompletionStatus
from cerebro.harness.errors import InferenceError
from cerebro.harness.exceptions import (
    DuplicateHarnessIdentity,
    HarnessRecordNotFound,
    HarnessStateError,
    StaleHarnessWrite,
    UnsupportedFormatVersion,
)
from cerebro.harness.execution import ToolExecution
from cerebro.harness.history import InferenceHistory
from cerebro.harness.ids import (
    AgentTurnId,
    ArtifactRef,
    CerebroCallId,
    ConversationTurnId,
    InferenceAttemptId,
    InferenceItemId,
    StepSnapshotId,
    ToolBindingGeneration,
)
from cerebro.harness.items import (
    InferenceItem,
    ProviderOpaqueItem,
    ToolCallItem,
    ToolResultItem,
)
from cerebro.harness.artifacts import ARTIFACT_FORMAT_VERSION, StagedArtifact, StoredArtifact
from cerebro.harness.snapshot import STEP_SNAPSHOT_FORMAT_VERSION, StepSnapshot
from cerebro.harness.tooling import ToolBinding, ToolKey
from cerebro.harness.serialization import (
    SUPPORTED_ATTEMPT_FORMAT_VERSIONS,
    SUPPORTED_ITEM_FORMAT_VERSIONS,
    SUPPORTED_TOOL_EXECUTION_FORMAT_VERSIONS,
    SUPPORTED_TURN_FORMAT_VERSIONS,
    SUPPORTED_STEP_SNAPSHOT_FORMAT_VERSIONS,
    canonical_json,
    dump_attempt,
    dump_item,
    dump_step_snapshot,
    dump_tool_execution,
    dump_turn,
    load_attempt,
    load_item,
    load_step_snapshot,
    load_tool_execution,
    load_turn,
)
from cerebro.harness.turn import AgentTurn, AgentTurnLifecycle
from cerebro.harness.wake import CausalWakeKey

HARNESS_SCHEMA_EPOCH = 2
HARNESS_STORAGE_FORMAT_VERSION = 2
STEP_SNAPSHOT_STORAGE_FORMAT_VERSION = 1
STEP_SNAPSHOT_EXECUTABLE_FORMAT_VERSION = STEP_SNAPSHOT_FORMAT_VERSION
TURN_EVENT_FORMAT_VERSION = 1

# Item kinds whose arrival advances the durable provider-replay checkpoint version. Anything a
# later request must be able to reproduce exactly counts; ordinary assistant prose does not.
_REPLAY_REQUIRED_OPAQUE = "required_for_correctness"

# Attempt states whose finalized output may still make a call executable. `completed` is the
# ordinary case, not an edge one: a provider finishes with `tool_calls_pending` and only then does
# the tool run, so demanding `active` here would block every real dispatch. `abandoned`,
# `failed` and `cancelled_before_dispatch` are excluded, because output from an attempt the turn
# has moved on from must not authorise an external effect.
_ATTEMPT_STATES_THAT_MAY_AUTHORISE_A_TOOL = frozenset({"active", "completed"})

_TERMINAL_LIFECYCLES = frozenset({"completed", "cancelled", "failed"})
_ALLOWED_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "suspended", "cancelled", "failed"}),
    "running": frozenset({"suspended", "completed", "cancelled", "failed"}),
    "suspended": frozenset({"running", "cancelled", "failed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
}
_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HarnessMetadata(BaseModel):
    """The active durable Harness storage and execution epochs."""

    model_config = {"frozen": True}
    schema_epoch: int
    storage_format_version: int
    active_execution_epoch: int
    security_revocation_epoch: int
    updated_at: str


class StepSnapshotIdentity(BaseModel):
    """The superseded Phase 1B identity-only snapshot envelope (`format_version` 1).

    Kept readable so Phase 1B rows and regressions still load. `StepSnapshot` in
    `cerebro.harness.snapshot` is the executable form, and only that form can make a call
    executable; the two share a table and are never interchangeable.
    """

    model_config = {"frozen": True}
    snapshot_id: StepSnapshotId
    format_version: int = STEP_SNAPSHOT_STORAGE_FORMAT_VERSION
    agent_turn_id: AgentTurnId
    step_index: int = Field(ge=0)
    turn_version_at_creation: int = Field(ge=0)
    created_at: str


@dataclass(frozen=True)
class StoredInferenceAttempt:
    """A canonical attempt plus its compare-and-set storage version."""

    attempt: InferenceAttempt
    row_version: int


@dataclass(frozen=True)
class StoredToolExecution:
    """A canonical tool execution plus its compare-and-set storage version."""

    execution: ToolExecution
    row_version: int


def _json_object(text: str, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HarnessStateError(f"stored {kind} payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise HarnessStateError(f"stored {kind} payload is not a JSON object")
    return value


def _require_row_version(kind: str, version: int, supported: frozenset[int]) -> None:
    if version not in supported:
        raise UnsupportedFormatVersion(kind, version, supported)


def _turn_from_row(row: Any) -> AgentTurn:
    _require_row_version("AgentTurn", row["format_version"], SUPPORTED_TURN_FORMAT_VERSIONS)
    turn = load_turn(_json_object(row["payload_json"], "AgentTurn"))
    wake = turn.causal_wake_key
    expected = {
        "id": str(turn.id),
        "format_version": turn.format_version,
        "state_version": turn.state_version,
        "execution_epoch": turn.execution_epoch,
        "conversation_turn_id": str(turn.conversation_turn_id),
        "causal_wake_serialized": wake.serialized(),
        "causal_wake_hash": wake.stable_hash(),
        "lifecycle": turn.lifecycle,
        "suspension_reason": turn.suspension_reason,
        "current_step_index": turn.current_step_index,
        "active_step_snapshot_id": (
            str(turn.active_step_snapshot_id) if turn.active_step_snapshot_id is not None else None
        ),
        "active_inference_attempt_id": (
            str(turn.active_inference_attempt_id)
            if turn.active_inference_attempt_id is not None
            else None
        ),
        "product_outcome_kind": turn.product_outcome_kind,
        "final_message_id": turn.final_message_id,
        "failure_kind": turn.failure_kind,
        "needs_attention": int(turn.needs_attention),
        "unresolved_effect_count": turn.unresolved_effect_count,
    }
    for column, value in expected.items():
        if row[column] != value:
            raise HarnessStateError(
                f"AgentTurn {turn.id} column {column} disagrees with its canonical payload"
            )
    return turn


def _attempt_from_row(row: Any) -> StoredInferenceAttempt:
    _require_row_version(
        "InferenceAttempt", row["format_version"], SUPPORTED_ATTEMPT_FORMAT_VERSIONS
    )
    attempt = load_attempt(_json_object(row["payload_json"], "InferenceAttempt"))
    expected = {
        "attempt_id": str(attempt.attempt_id),
        "format_version": attempt.format_version,
        "agent_turn_id": str(attempt.agent_turn_id),
        "step_snapshot_id": str(attempt.step_snapshot_id),
        "dispatch_state": attempt.dispatch_state,
        "semantic_state": attempt.semantic_state,
        "dispatch_barrier_committed": int(attempt.dispatch_barrier_committed),
    }
    for column, value in expected.items():
        if row[column] != value:
            raise HarnessStateError(
                f"InferenceAttempt {attempt.attempt_id} column {column} disagrees with payload"
            )
    return StoredInferenceAttempt(attempt, row["row_version"])


def _item_from_row(row: Any) -> InferenceItem:
    _require_row_version("InferenceItem", row["format_version"], SUPPORTED_ITEM_FORMAT_VERSIONS)
    item = load_item(_json_object(row["payload_json"], "InferenceItem"))
    expected = {
        "item_id": str(item.item_id),
        "format_version": item.format_version,
        "agent_turn_id": str(item.agent_turn_id),
        "sequence_no": item.sequence_no,
        "item_type": item.item_type,
        "producing_attempt_id": (
            str(item.producing_attempt_id) if item.producing_attempt_id is not None else None
        ),
        "superseded_at": item.superseded_at,
        "superseded_reason": item.superseded_reason,
        "superseding_attempt_id": (
            str(item.superseding_attempt_id) if item.superseding_attempt_id is not None else None
        ),
    }
    for column, value in expected.items():
        if row[column] != value:
            raise HarnessStateError(
                f"InferenceItem {item.item_id} column {column} disagrees with payload"
            )
    return item


def _tool_from_row(row: Any) -> StoredToolExecution:
    _require_row_version(
        "ToolExecution", row["format_version"], SUPPORTED_TOOL_EXECUTION_FORMAT_VERSIONS
    )
    execution = load_tool_execution(_json_object(row["payload_json"], "ToolExecution"))
    resolution_kind = (
        execution.resolution.resolution_kind if execution.resolution is not None else None
    )
    expected = {
        "call_id": str(execution.call_id),
        "format_version": execution.format_version,
        "agent_turn_id": str(execution.agent_turn_id),
        "step_snapshot_id": str(execution.step_snapshot_id),
        "tool_call_item_id": str(execution.tool_call_item_id),
        "tool_key": execution.tool_key.canonical(),
        "dispatch_state": execution.dispatch_state,
        "resolution_kind": resolution_kind,
        "resolution_status": (
            execution.resolution.status if resolution_kind == "known" else None
        ),
        "resolution_reason": (
            execution.resolution.reason if resolution_kind == "indeterminate" else None
        ),
        "dispatch_marked_at": execution.dispatch_marked_at,
        "resolved_at": execution.resolved_at,
        "stable_operation_key": execution.stable_operation_key,
        "binding_executor_identity": execution.binding_executor_identity,
        "recovery_effect_class": execution.recovery_capability.effect_class,
        "recovery_repeat_semantics": execution.recovery_capability.repeat_semantics,
        "raw_output_ref": (
            str(execution.raw_output_ref) if execution.raw_output_ref is not None else None
        ),
        "model_output_item_id": (
            str(execution.model_output_item_id)
            if execution.model_output_item_id is not None
            else None
        ),
    }
    for column, value in expected.items():
        if row[column] != value:
            raise HarnessStateError(
                f"ToolExecution {execution.call_id} column {column} disagrees with payload"
            )
    return StoredToolExecution(execution, row["row_version"])


def _step_snapshot_from_row(row: Any) -> StepSnapshot:
    """Strictly decode one executable snapshot and re-check every queryable column.

    An executable snapshot is the only description of what was runnable for a step. A row whose
    indexed columns disagree with its canonical envelope is not a snapshot with a typo; it is
    two different answers to that question, so it fails closed.
    """
    version = row["format_version"]
    if version not in SUPPORTED_STEP_SNAPSHOT_FORMAT_VERSIONS:
        raise UnsupportedFormatVersion(
            "StepSnapshot", version, SUPPORTED_STEP_SNAPSHOT_FORMAT_VERSIONS
        )
    snapshot = load_step_snapshot(_json_object(row["storage_envelope_json"], "StepSnapshot"))
    expected = {
        "snapshot_id": str(snapshot.snapshot_id),
        "agent_turn_id": str(snapshot.agent_turn_id),
        "step_index": snapshot.step_index,
        "turn_version_at_creation": snapshot.turn_version_at_creation,
        **snapshot.queryable_columns(),
    }
    for column, value in expected.items():
        if row[column] != value:
            raise HarnessStateError(
                f"StepSnapshot {snapshot.snapshot_id} column {column} disagrees with its "
                f"immutable envelope"
            )
    return snapshot


def _artifact_from_row(row: Any) -> StoredArtifact:
    """Decode one artifact index row without touching its payload."""
    if row["format_version"] != ARTIFACT_FORMAT_VERSION:
        raise UnsupportedFormatVersion(
            "HarnessArtifact", row["format_version"], frozenset({ARTIFACT_FORMAT_VERSION})
        )
    return StoredArtifact(
        artifact_ref=ArtifactRef(row["artifact_ref"]),
        agent_turn_id=AgentTurnId(row["agent_turn_id"]),
        call_id=CerebroCallId(row["call_id"]),
        tool_key=ToolKey.parse(row["tool_key"]),
        binding_generation=ToolBindingGeneration(row["binding_generation"]),
        content_type=row["content_type"],
        storage_backend=row["storage_backend"],
        byte_size=row["byte_size"],
        content_sha256=row["content_sha256"],
        retention_policy=row["retention_policy"],
        provenance=_json_object(row["provenance_json"], "HarnessArtifact"),
        created_at=row["created_at"],
    )


def _replay_weight(item: Any) -> int:
    """How much one appended item advances the durable provider-replay checkpoint.

    Only material a later request must reproduce exactly counts: replay-required opaque protocol
    state and a tool call carrying a replay-required provider handle.
    """
    if isinstance(item, ProviderOpaqueItem):
        return 1 if item.replay_requirement == _REPLAY_REQUIRED_OPAQUE else 0
    if isinstance(item, ToolCallItem):
        ref = item.provider_ref
        return 1 if ref is not None and ref.replay_required else 0
    return 0


async def _fetch_one_conn(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    cursor = await conn.execute(sql, params)
    return await cursor.fetchone()


async def _fetch_all_conn(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    cursor = await conn.execute(sql, params)
    return list(await cursor.fetchall())


async def _turn_conn(conn: Any, turn_id: AgentTurnId | str) -> AgentTurn:
    row = await _fetch_one_conn(conn, "SELECT * FROM agent_turns WHERE id = ?", (str(turn_id),))
    if row is None:
        raise HarnessRecordNotFound(f"AgentTurn {turn_id} does not exist")
    return _turn_from_row(row)


async def _attempt_conn(conn: Any, attempt_id: InferenceAttemptId) -> StoredInferenceAttempt:
    row = await _fetch_one_conn(
        conn, "SELECT * FROM inference_attempts WHERE attempt_id = ?", (str(attempt_id),)
    )
    if row is None:
        raise HarnessRecordNotFound(f"InferenceAttempt {attempt_id} does not exist")
    return _attempt_from_row(row)


async def _tool_conn(conn: Any, call_id: CerebroCallId) -> StoredToolExecution:
    row = await _fetch_one_conn(
        conn, "SELECT * FROM tool_executions WHERE call_id = ?", (str(call_id),)
    )
    if row is None:
        raise HarnessRecordNotFound(f"ToolExecution {call_id} does not exist")
    return _tool_from_row(row)


async def _append_event(
    conn: Any,
    turn: AgentTurn,
    event_type: str,
    *,
    at: str,
    snapshot_id: StepSnapshotId | None = None,
    attempt_id: InferenceAttemptId | None = None,
    call_id: CerebroCallId | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    row = await _fetch_one_conn(
        conn,
        "SELECT COALESCE(MAX(event_sequence), -1) + 1 AS next_sequence "
        "FROM turn_events WHERE agent_turn_id = ?",
        (str(turn.id),),
    )
    sequence = row["next_sequence"]
    payload = {
        "event_format_version": TURN_EVENT_FORMAT_VERSION,
        "event_type": event_type,
        "agent_turn_id": str(turn.id),
        "event_sequence": sequence,
        "resulting_turn_state_version": turn.state_version,
        "step_snapshot_id": str(snapshot_id) if snapshot_id is not None else None,
        "inference_attempt_id": str(attempt_id) if attempt_id is not None else None,
        "cerebro_call_id": str(call_id) if call_id is not None else None,
        "detail": detail or {},
        "created_at": at,
    }
    await conn.execute(
        """
        INSERT INTO turn_events (
            event_format_version, agent_turn_id, event_sequence, event_type,
            resulting_turn_state_version, step_snapshot_id, inference_attempt_id,
            cerebro_call_id, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            TURN_EVENT_FORMAT_VERSION,
            str(turn.id),
            sequence,
            event_type,
            turn.state_version,
            str(snapshot_id) if snapshot_id is not None else None,
            str(attempt_id) if attempt_id is not None else None,
            str(call_id) if call_id is not None else None,
            canonical_json(payload),
            at,
        ),
    )


def _turn_values(turn: AgentTurn) -> dict[str, Any]:
    wake = turn.causal_wake_key
    return {
        "id": str(turn.id),
        "format_version": turn.format_version,
        "state_version": turn.state_version,
        "execution_epoch": turn.execution_epoch,
        "conversation_turn_id": str(turn.conversation_turn_id),
        "causal_wake_serialized": wake.serialized(),
        "causal_wake_hash": wake.stable_hash(),
        "wake_kind": wake.wake_kind,
        "target_agent_id": wake.target_agent_id,
        "channel_id": turn.channel_id,
        "trigger_message_id": turn.trigger_message_id,
        "occurrence_id": wake.occurrence_id,
        "agent_id": turn.agent_id,
        "root_agent_turn_id": str(turn.root_agent_turn_id) if turn.root_agent_turn_id else None,
        "parent_agent_turn_id": str(turn.parent_agent_turn_id) if turn.parent_agent_turn_id else None,
        "product_task_id": turn.product_task_id,
        "lifecycle": turn.lifecycle,
        "suspension_reason": turn.suspension_reason,
        "cancel_requested_at": turn.cancel_requested_at,
        "current_step_index": turn.current_step_index,
        "active_step_snapshot_id": (
            str(turn.active_step_snapshot_id) if turn.active_step_snapshot_id else None
        ),
        "active_inference_attempt_id": (
            str(turn.active_inference_attempt_id) if turn.active_inference_attempt_id else None
        ),
        "product_outcome_kind": turn.product_outcome_kind,
        "final_message_id": turn.final_message_id,
        "failure_kind": turn.failure_kind,
        "needs_attention": int(turn.needs_attention),
        "unresolved_effect_count": turn.unresolved_effect_count,
        "created_at": turn.created_at,
        "started_at": turn.started_at,
        "updated_at": turn.updated_at,
        "completed_at": turn.completed_at,
        "payload_json": canonical_json(dump_turn(turn)),
    }


async def _update_turn_conn(conn: Any, turn: AgentTurn, expected_version: int) -> None:
    values = _turn_values(turn)
    values["expected_version"] = expected_version
    cursor = await conn.execute(
        """
        UPDATE agent_turns SET
            format_version=:format_version, state_version=:state_version,
            execution_epoch=:execution_epoch, lifecycle=:lifecycle,
            suspension_reason=:suspension_reason, cancel_requested_at=:cancel_requested_at,
            current_step_index=:current_step_index,
            active_step_snapshot_id=:active_step_snapshot_id,
            active_inference_attempt_id=:active_inference_attempt_id,
            product_outcome_kind=:product_outcome_kind, final_message_id=:final_message_id,
            failure_kind=:failure_kind, needs_attention=:needs_attention,
            unresolved_effect_count=:unresolved_effect_count, started_at=:started_at,
            updated_at=:updated_at, completed_at=:completed_at, payload_json=:payload_json
        WHERE id=:id AND state_version=:expected_version
        """,
        values,
    )
    if cursor.rowcount != 1:
        raise StaleHarnessWrite(
            f"AgentTurn {turn.id} expected state_version {expected_version} is stale"
        )


def _updated_turn(turn: AgentTurn, *, at: str, **changes: Any) -> AgentTurn:
    payload = turn.model_dump(mode="python")
    payload.update(changes)
    payload["state_version"] = turn.state_version + 1
    payload["updated_at"] = at
    return AgentTurn.model_validate(payload)


async def _insert_tool_execution(conn: Any, execution: ToolExecution) -> None:
    """Insert one durable ToolExecution row with its frozen binding evidence.

    The binding generation, executor identity and recovery capability are written as queryable
    columns as well as canonical JSON. A stale-binding check that had to parse a blob would be
    one convenience query away from silently skipping itself.
    """
    await conn.execute(
        """
        INSERT INTO tool_executions (
            call_id,format_version,row_version,agent_turn_id,step_snapshot_id,
            tool_call_item_id,tool_key,admitted_turn_version,dispatch_state,
            resolution_kind,resolution_status,resolution_reason,binding_generation,
            stable_operation_key,admitted_at,dispatch_marked_at,resolved_at,payload_json,
            binding_executor_identity,recovery_effect_class,recovery_repeat_semantics,
            raw_output_ref,model_output_item_id
        ) VALUES (?,?,0,?,?,?,?,?,?,NULL,NULL,NULL,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(execution.call_id),
            execution.format_version,
            str(execution.agent_turn_id),
            str(execution.step_snapshot_id),
            str(execution.tool_call_item_id),
            execution.tool_key.canonical(),
            execution.admitted_turn_version,
            execution.dispatch_state,
            str(execution.binding_generation),
            execution.stable_operation_key,
            execution.admitted_at,
            execution.dispatch_marked_at,
            execution.resolved_at,
            canonical_json(dump_tool_execution(execution)),
            execution.binding_executor_identity,
            execution.recovery_capability.effect_class,
            execution.recovery_capability.repeat_semantics,
            str(execution.raw_output_ref) if execution.raw_output_ref is not None else None,
            (
                str(execution.model_output_item_id)
                if execution.model_output_item_id is not None
                else None
            ),
        ),
    )


async def _append_tool_result_conn(
    conn: Any,
    turn: AgentTurn,
    result: ToolResultItem,
    *,
    expected_history_version: int,
    at: str,
) -> tuple[ToolResultItem, int]:
    history = await _fetch_one_conn(
        conn,
        "SELECT * FROM inference_histories WHERE conversation_turn_id=?",
        (str(turn.conversation_turn_id),),
    )
    if history is None:
        raise HarnessRecordNotFound(f"InferenceHistory {turn.conversation_turn_id} is missing")
    if history["version"] != expected_history_version:
        raise StaleHarnessWrite(
            f"InferenceHistory {turn.conversation_turn_id} expected "
            f"{expected_history_version}, found {history['version']}"
        )
    item = result.model_copy(
        update={
            "agent_turn_id": turn.id,
            "sequence_no": history["next_sequence"],
        }
    )
    item = load_item(dump_item(item))
    await conn.execute(
        """
        INSERT INTO inference_items (
            item_id,format_version,conversation_turn_id,agent_turn_id,sequence_no,
            producing_attempt_id,item_type,superseded_at,superseded_reason,
            superseding_attempt_id,payload_json,created_at
        ) VALUES (?,?,?,?,?,NULL,?,?,?,?,?,?)
        """,
        (
            str(item.item_id),
            item.format_version,
            str(turn.conversation_turn_id),
            str(turn.id),
            item.sequence_no,
            item.item_type,
            item.superseded_at,
            item.superseded_reason,
            str(item.superseding_attempt_id) if item.superseding_attempt_id else None,
            canonical_json(dump_item(item)),
            at,
        ),
    )
    new_history_version = expected_history_version + 1
    cursor = await conn.execute(
        "UPDATE inference_histories SET version=?,next_sequence=?,updated_at=? "
        "WHERE conversation_turn_id=? AND version=?",  # a tool result carries no replay material
        (
            new_history_version,
            history["next_sequence"] + 1,
            at,
            str(turn.conversation_turn_id),
            expected_history_version,
        ),
    )
    if cursor.rowcount != 1:
        raise StaleHarnessWrite(f"InferenceHistory {turn.conversation_turn_id} lost its CAS")
    return item, new_history_version


@dataclass(frozen=True)
class ExecutableBarrierFacts:
    """The durable facts section 17 A-L requires, read back inside one writer transaction."""

    turn: AgentTurn
    snapshot: StepSnapshot
    attempt: InferenceAttempt
    call_item: ToolCallItem
    binding: ToolBinding
    history_version: int
    replay_version: int
    security_revocation_epoch: int


@dataclass(frozen=True)
class ExecutableCallCheckpoint:
    """The committed executable pre-side-effect checkpoint for one call."""

    execution: StoredToolExecution
    turn: AgentTurn
    snapshot: StepSnapshot
    history_version: int
    replay_version: int


async def _verify_executable_barrier(
    conn: Any,
    *,
    agent_turn_id: AgentTurnId,
    snapshot_id: StepSnapshotId,
    attempt_id: InferenceAttemptId,
    tool_call_item_id: InferenceItemId,
    call_id: CerebroCallId,
    binding: ToolBinding,
    expected_turn_version: int,
    expected_history_version: int,
    expected_replay_version: int,
    require_provider_call_ref: bool,
    required_opaque_kinds: tuple[str, ...],
) -> ExecutableBarrierFacts:
    """Verify section 17 A, B, C, D, F, G, H and J against durable truth, or fail closed.

    These may have been committed by earlier authoritative snapshot/output transactions, so the
    barrier does not re-write them; it proves they are still exactly what the call was frozen
    against. Every check raises rather than degrading, because a barrier that passes on partial
    evidence is not a barrier.
    """
    turn = await _turn_conn(conn, agent_turn_id)
    if turn.state_version != expected_turn_version:
        raise StaleHarnessWrite(
            f"AgentTurn {agent_turn_id} expected {expected_turn_version}, "
            f"found {turn.state_version}"
        )
    if turn.is_terminal:
        raise HarnessStateError("a terminal AgentTurn has no executable call")

    # A. the immutable executable snapshot exists and is still this turn's active step.
    snapshot_row = await _fetch_one_conn(
        conn, "SELECT * FROM step_snapshots WHERE snapshot_id = ?", (str(snapshot_id),)
    )
    if snapshot_row is None:
        raise HarnessRecordNotFound(f"StepSnapshot {snapshot_id} does not exist")
    if snapshot_row["format_version"] != STEP_SNAPSHOT_EXECUTABLE_FORMAT_VERSION:
        raise HarnessStateError(
            f"StepSnapshot {snapshot_id} is format_version "
            f"{snapshot_row['format_version']}; only an executable snapshot can make a call "
            f"executable"
        )
    snapshot = _step_snapshot_from_row(snapshot_row)
    if snapshot.agent_turn_id != turn.id:
        raise HarnessStateError("StepSnapshot does not belong to this AgentTurn")
    if turn.active_step_snapshot_id != snapshot.snapshot_id:
        raise HarnessStateError("the executable checkpoint requires the active StepSnapshot")
    if snapshot.step_index != turn.current_step_index:
        raise HarnessStateError("StepSnapshot is not the turn's current step")

    # B. the active provider attempt identity exists and matches snapshot and turn.
    stored_attempt = await _attempt_conn(conn, attempt_id)
    attempt = stored_attempt.attempt
    if attempt.agent_turn_id != turn.id or attempt.step_snapshot_id != snapshot.snapshot_id:
        raise HarnessStateError("InferenceAttempt does not belong to this snapshot and turn")
    if turn.active_inference_attempt_id != attempt.attempt_id:
        raise HarnessStateError("the executable checkpoint requires the active InferenceAttempt")
    if attempt.semantic_state not in _ATTEMPT_STATES_THAT_MAY_AUTHORISE_A_TOOL:
        raise HarnessStateError(
            f"attempt {attempt_id} is {attempt.semantic_state}; its output cannot authorise a "
            f"tool"
        )

    # D. the completed ToolCallItem is persisted and is this call.
    item_row = await _fetch_one_conn(
        conn, "SELECT * FROM inference_items WHERE item_id = ?", (str(tool_call_item_id),)
    )
    if item_row is None:
        raise HarnessRecordNotFound(f"ToolCallItem {tool_call_item_id} is not durable")
    call_item = _item_from_row(item_row)
    if not isinstance(call_item, ToolCallItem):
        raise HarnessStateError("the checkpointed item is not a finalized ToolCallItem")
    if call_item.agent_turn_id != turn.id:
        raise HarnessStateError("ToolCallItem belongs to another AgentTurn")
    if call_item.producing_attempt_id != attempt.attempt_id:
        raise HarnessStateError("ToolCallItem was not produced by the active attempt")
    if call_item.call_id != call_id:
        raise HarnessStateError("ToolCallItem does not carry this CerebroCallId")
    if call_item.is_superseded:
        raise HarnessStateError("a superseded ToolCallItem cannot become executable")
    if call_item.tool_key != binding.key:
        raise HarnessStateError("ToolCallItem names a different tool than the frozen binding")

    # C and G. every finalized item this attempt produced up to the call is durable, ordered
    # and unsuperseded, and every replay-required opaque item the adapter named is present.
    preceding_rows = await _fetch_all_conn(
        conn,
        "SELECT * FROM inference_items WHERE producing_attempt_id=? AND sequence_no<=? "
        "ORDER BY sequence_no,item_id",
        (str(attempt.attempt_id), call_item.sequence_no),
    )
    preceding = [_item_from_row(row) for row in preceding_rows]
    if not preceding or preceding[-1].item_id != call_item.item_id:
        raise HarnessStateError(
            "the ToolCallItem is not the last finalized item of its attempt; provider output "
            "order is not durable"
        )
    sequences = [item.sequence_no for item in preceding]
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        raise HarnessStateError("finalized provider output is not persisted in provider order")
    superseded = [item for item in preceding if item.is_superseded]
    if superseded:
        raise HarnessStateError(
            "a superseded preceding output item cannot support an executable checkpoint"
        )
    persisted_kinds = {
        item.kind for item in preceding if isinstance(item, ProviderOpaqueItem)
    }
    missing_kinds = sorted(set(required_opaque_kinds) - persisted_kinds)
    if missing_kinds:
        raise HarnessStateError(
            f"required ProviderOpaqueItem kinds are not durable: {missing_kinds}"
        )

    # F. the replay-required provider handle is persisted with the call.
    if require_provider_call_ref:
        ref = call_item.provider_ref
        if ref is None or not ref.replay_required:
            raise HarnessStateError(
                "this call requires a replay-required ProviderCallRef; without it the "
                "continuation cannot be reconstructed after the effect has happened"
            )

    # H. history and provider-replay versions match and never trail the frozen snapshot.
    history_row = await _fetch_one_conn(
        conn,
        "SELECT * FROM inference_histories WHERE conversation_turn_id=?",
        (str(turn.conversation_turn_id),),
    )
    if history_row is None:
        raise HarnessRecordNotFound(f"InferenceHistory {turn.conversation_turn_id} is missing")
    if history_row["version"] != expected_history_version:
        raise StaleHarnessWrite(
            f"InferenceHistory {turn.conversation_turn_id} expected "
            f"{expected_history_version}, found {history_row['version']}"
        )
    if history_row["replay_version"] != expected_replay_version:
        raise StaleHarnessWrite(
            f"provider replay checkpoint expected {expected_replay_version}, "
            f"found {history_row['replay_version']}"
        )
    if snapshot.inference_history_version > expected_history_version:
        raise HarnessStateError("snapshot history version is ahead of durable history")
    if snapshot.provider_replay_version > expected_replay_version:
        raise HarnessStateError("snapshot replay version is ahead of durable replay state")

    # J. the frozen plan binds exactly this executor generation and recovery capability.
    frozen = snapshot.tool_plan.binding_for(binding.key)
    if frozen is None:
        raise HarnessStateError(
            f"tool {binding.key.canonical()} is not in the frozen tool plan for this step"
        )
    if frozen != binding:
        raise HarnessStateError(
            f"the offered binding for {binding.key.canonical()} is not the one frozen in the "
            f"snapshot; a call is never rebound to a newer generation"
        )
    if snapshot.tool_plan.grant_evidence and snapshot.tool_plan.evidence_for(binding.key) is None:
        raise HarnessStateError(
            f"no frozen grant evidence for {binding.key.canonical()}"
        )

    metadata_row = await _fetch_one_conn(
        conn, "SELECT * FROM harness_metadata WHERE singleton = 1"
    )
    if metadata_row is None:
        raise HarnessRecordNotFound("Harness metadata is missing")
    current_epoch = metadata_row["security_revocation_epoch"]
    if current_epoch != snapshot.security_revocation_epoch:
        raise HarnessStateError(
            f"security revocation epoch advanced from {snapshot.security_revocation_epoch} to "
            f"{current_epoch}; this call resolves denied under its original identity"
        )

    return ExecutableBarrierFacts(
        turn=turn,
        snapshot=snapshot,
        attempt=attempt,
        call_item=call_item,
        binding=frozen,
        history_version=expected_history_version,
        replay_version=expected_replay_version,
        security_revocation_epoch=current_epoch,
    )


class HarnessStore:
    """Repository for durable Harness state and compare-and-set transitions."""

    async def metadata(self) -> HarnessMetadata:
        """Read and validate the singleton Harness schema/execution metadata."""
        row = await db.fetch_one("SELECT * FROM harness_metadata WHERE singleton = 1")
        if row is None:
            raise HarnessRecordNotFound("Harness metadata is missing; run migrations")
        if row["schema_epoch"] != HARNESS_SCHEMA_EPOCH:
            raise UnsupportedFormatVersion(
                "HarnessSchema", row["schema_epoch"], frozenset({HARNESS_SCHEMA_EPOCH})
            )
        if row["storage_format_version"] != HARNESS_STORAGE_FORMAT_VERSION:
            raise UnsupportedFormatVersion(
                "HarnessStorage",
                row["storage_format_version"],
                frozenset({HARNESS_STORAGE_FORMAT_VERSION}),
            )
        return HarnessMetadata(**{key: row[key] for key in HarnessMetadata.model_fields})

    async def admit_turn(self, turn: AgentTurn) -> AgentTurn:
        """Atomically admit one causal occurrence or return its existing durable turn."""
        turn = load_turn(dump_turn(turn))
        wake = turn.causal_wake_key
        if turn.state_version != 0 or turn.lifecycle != "queued":
            raise HarnessStateError("new AgentTurn must be queued at state_version 0")
        if turn.agent_id != wake.target_agent_id or turn.channel_id != wake.channel_id:
            raise HarnessStateError("AgentTurn identity must match its CausalWakeKey target")
        if turn.trigger_message_id != wake.trigger_message_id:
            raise HarnessStateError("AgentTurn trigger must match its CausalWakeKey")

        async def _tx(conn: Any) -> AgentTurn:
            metadata = await _fetch_one_conn(
                conn, "SELECT * FROM harness_metadata WHERE singleton = 1"
            )
            if metadata is None:
                raise HarnessRecordNotFound("Harness metadata is missing")
            if turn.execution_epoch != metadata["active_execution_epoch"]:
                raise HarnessStateError("AgentTurn does not belong to the active execution epoch")
            existing = await _fetch_one_conn(
                conn,
                "SELECT * FROM agent_turns WHERE causal_wake_hash = ?",
                (wake.stable_hash(),),
            )
            if existing is not None:
                if existing["causal_wake_serialized"] != wake.serialized():
                    raise DuplicateHarnessIdentity("CausalWakeKey hash collision detected")
                return _turn_from_row(existing)
            reused_id = await _fetch_one_conn(
                conn, "SELECT 1 FROM agent_turns WHERE id = ?", (str(turn.id),)
            )
            if reused_id is not None:
                raise DuplicateHarnessIdentity(f"AgentTurnId {turn.id} is already in use")
            await conn.execute(
                """
                INSERT INTO agent_turns (
                    id,format_version,state_version,execution_epoch,conversation_turn_id,
                    causal_wake_serialized,causal_wake_hash,wake_kind,target_agent_id,channel_id,
                    trigger_message_id,occurrence_id,agent_id,root_agent_turn_id,parent_agent_turn_id,
                    product_task_id,lifecycle,suspension_reason,cancel_requested_at,current_step_index,
                    active_step_snapshot_id,active_inference_attempt_id,product_outcome_kind,
                    final_message_id,failure_kind,needs_attention,unresolved_effect_count,created_at,
                    started_at,updated_at,completed_at,payload_json
                ) VALUES (
                    :id,:format_version,:state_version,:execution_epoch,:conversation_turn_id,
                    :causal_wake_serialized,:causal_wake_hash,:wake_kind,:target_agent_id,:channel_id,
                    :trigger_message_id,:occurrence_id,:agent_id,:root_agent_turn_id,
                    :parent_agent_turn_id,:product_task_id,:lifecycle,:suspension_reason,
                    :cancel_requested_at,:current_step_index,:active_step_snapshot_id,
                    :active_inference_attempt_id,:product_outcome_kind,:final_message_id,
                    :failure_kind,:needs_attention,:unresolved_effect_count,:created_at,:started_at,
                    :updated_at,:completed_at,:payload_json
                )
                """,
                _turn_values(turn),
            )
            await conn.execute(
                "INSERT OR IGNORE INTO inference_histories "
                "(conversation_turn_id,version,next_sequence,updated_at) VALUES (?,0,0,?)",
                (str(turn.conversation_turn_id), turn.created_at),
            )
            await _append_event(conn, turn, "turn.created", at=turn.created_at)
            return turn

        return await db.run_in_writer(_tx)

    async def get_turn(self, turn_id: AgentTurnId | str) -> AgentTurn:
        """Load one canonical turn with strict format and column checks."""
        row = await db.fetch_one("SELECT * FROM agent_turns WHERE id = ?", (str(turn_id),))
        if row is None:
            raise HarnessRecordNotFound(f"AgentTurn {turn_id} does not exist")
        return _turn_from_row(row)

    async def get_turn_for_wake(self, wake: CausalWakeKey) -> AgentTurn | None:
        """Return the turn admitted for a deterministic causal key, if any."""
        row = await db.fetch_one(
            "SELECT * FROM agent_turns WHERE causal_wake_hash = ?", (wake.stable_hash(),)
        )
        if row is None:
            return None
        if row["causal_wake_serialized"] != wake.serialized():
            raise DuplicateHarnessIdentity("CausalWakeKey hash collision detected")
        return _turn_from_row(row)

    async def transition_turn(
        self,
        turn_id: AgentTurnId,
        *,
        expected_version: int,
        lifecycle: AgentTurnLifecycle,
        at: str | None = None,
        suspension_reason: str | None = None,
        product_outcome_kind: Any = _UNSET,
        final_message_id: Any = _UNSET,
        failure_kind: Any = _UNSET,
        failure_detail: Any = _UNSET,
    ) -> AgentTurn:
        """Compare-and-set a monotonic lifecycle transition and append its event."""
        transition_at = at or _now()

        async def _tx(conn: Any) -> AgentTurn:
            current = await _turn_conn(conn, turn_id)
            if current.state_version != expected_version:
                raise StaleHarnessWrite(
                    f"AgentTurn {turn_id} expected {expected_version}, found "
                    f"{current.state_version}"
                )
            if lifecycle not in _ALLOWED_LIFECYCLE_TRANSITIONS[current.lifecycle]:
                raise HarnessStateError(
                    f"AgentTurn lifecycle cannot move {current.lifecycle} -> {lifecycle}"
                )
            changes: dict[str, Any] = {"lifecycle": lifecycle}
            if lifecycle == "running":
                changes.update(
                    suspension_reason=None, started_at=current.started_at or transition_at
                )
            elif lifecycle == "suspended":
                changes["suspension_reason"] = suspension_reason
            elif suspension_reason is not None:
                raise HarnessStateError("suspension_reason requires suspended lifecycle")
            if lifecycle in _TERMINAL_LIFECYCLES:
                changes["completed_at"] = transition_at
            for name, value in (
                ("product_outcome_kind", product_outcome_kind),
                ("final_message_id", final_message_id),
                ("failure_kind", failure_kind),
                ("failure_detail", failure_detail),
            ):
                if value is not _UNSET:
                    changes[name] = value
            updated = _updated_turn(current, at=transition_at, **changes)
            await _update_turn_conn(conn, updated, expected_version)
            event_type = {
                "running": "turn.started",
                "suspended": "turn.suspended",
                "completed": "turn.completed",
                "cancelled": "turn.cancelled",
                "failed": "turn.failed",
            }[lifecycle]
            detail = {"reason": suspension_reason} if suspension_reason else {}
            await _append_event(conn, updated, event_type, at=transition_at, detail=detail)
            return updated

        return await db.run_in_writer(_tx)

    async def list_non_terminal_turns(self, execution_epoch: int) -> list[AgentTurn]:
        """List recovery candidates deterministically for one execution epoch."""
        rows = await db.fetch_all("SELECT * FROM agent_turns ORDER BY created_at,id")
        turns = [_turn_from_row(row) for row in rows]
        return [
            turn
            for turn in turns
            if turn.execution_epoch == execution_epoch and not turn.is_terminal
        ]

    async def list_recovery_candidate_ids(self) -> list[str]:
        """Enumerate durable turn identities without decoding semantic candidate fields.

        Recovery reloads each identity independently so one malformed canonical row cannot prevent
        later active-epoch turns from receiving a conservative disposition.
        """
        rows = await db.fetch_all("SELECT id FROM agent_turns ORDER BY created_at,id")
        return [row["id"] for row in rows]

    async def commit_snapshot_identity(
        self,
        snapshot: StepSnapshotIdentity,
        *,
        expected_turn_version: int,
    ) -> tuple[StepSnapshotIdentity, AgentTurn]:
        """Commit the superseded Phase 1B identity-only seam and make it active for the turn.

        Retained so the Phase 1B store regressions keep exercising the turn/snapshot transitions
        they were written against. It describes nothing executable: `format_version` 1 can never
        satisfy the pre-side-effect barrier, which requires the Phase 1C executable snapshot.
        """
        if snapshot.format_version != STEP_SNAPSHOT_STORAGE_FORMAT_VERSION:
            raise UnsupportedFormatVersion(
                "StepSnapshotIdentity",
                snapshot.format_version,
                frozenset({STEP_SNAPSHOT_STORAGE_FORMAT_VERSION}),
            )
        if snapshot.turn_version_at_creation != expected_turn_version:
            raise HarnessStateError("snapshot creation version must equal expected turn version")

        async def _tx(conn: Any) -> tuple[StepSnapshotIdentity, AgentTurn]:
            turn = await _turn_conn(conn, snapshot.agent_turn_id)
            if turn.state_version != expected_turn_version:
                raise StaleHarnessWrite(
                    f"AgentTurn {turn.id} expected {expected_turn_version}, "
                    f"found {turn.state_version}"
                )
            if turn.is_terminal:
                raise HarnessStateError("terminal AgentTurn cannot admit a new StepSnapshot")
            if snapshot.step_index < turn.current_step_index:
                raise HarnessStateError("StepSnapshot step_index cannot rewind current step")
            await conn.execute(
                """
                INSERT INTO step_snapshots (
                    snapshot_id,format_version,agent_turn_id,step_index,
                    turn_version_at_creation,storage_envelope_json,created_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    str(snapshot.snapshot_id),
                    snapshot.format_version,
                    str(snapshot.agent_turn_id),
                    snapshot.step_index,
                    snapshot.turn_version_at_creation,
                    canonical_json(snapshot.model_dump(mode="json")),
                    snapshot.created_at,
                ),
            )
            updated = _updated_turn(
                turn,
                at=snapshot.created_at,
                current_step_index=snapshot.step_index,
                active_step_snapshot_id=snapshot.snapshot_id,
            )
            await _update_turn_conn(conn, updated, expected_turn_version)
            await _append_event(
                conn,
                updated,
                "step.snapshot_committed",
                at=snapshot.created_at,
                snapshot_id=snapshot.snapshot_id,
            )
            return snapshot, updated

        return await db.run_in_writer(_tx)

    async def get_snapshot_identity(self, snapshot_id: StepSnapshotId) -> StepSnapshotIdentity:
        """Load the immutable snapshot identity envelope with strict format handling."""
        row = await db.fetch_one(
            "SELECT * FROM step_snapshots WHERE snapshot_id = ?", (str(snapshot_id),)
        )
        if row is None:
            raise HarnessRecordNotFound(f"StepSnapshotIdentity {snapshot_id} does not exist")
        if row["format_version"] != STEP_SNAPSHOT_STORAGE_FORMAT_VERSION:
            raise UnsupportedFormatVersion(
                "StepSnapshotIdentity",
                row["format_version"],
                frozenset({STEP_SNAPSHOT_STORAGE_FORMAT_VERSION}),
            )
        snapshot = StepSnapshotIdentity.model_validate(
            _json_object(row["storage_envelope_json"], "StepSnapshotIdentity")
        )
        if str(snapshot.snapshot_id) != row["snapshot_id"]:
            raise HarnessStateError("snapshot identity column disagrees with its envelope")
        return snapshot

    async def commit_step_snapshot(
        self,
        snapshot: StepSnapshot,
        *,
        expected_turn_version: int,
    ) -> tuple[StepSnapshot, AgentTurn]:
        """Commit the immutable executable snapshot and make it the turn's active step.

        The snapshot is written whole: the canonical envelope plus every queryable column, in
        one transaction with the turn projection and its event. There is no window in which a
        snapshot exists but is not yet the thing recovery would read.
        """
        snapshot = load_step_snapshot(dump_step_snapshot(snapshot))
        if snapshot.turn_version_at_creation != expected_turn_version:
            raise HarnessStateError("snapshot creation version must equal expected turn version")

        async def _tx(conn: Any) -> tuple[StepSnapshot, AgentTurn]:
            turn = await _turn_conn(conn, snapshot.agent_turn_id)
            if turn.state_version != expected_turn_version:
                raise StaleHarnessWrite(
                    f"AgentTurn {turn.id} expected {expected_turn_version}, "
                    f"found {turn.state_version}"
                )
            if turn.is_terminal:
                raise HarnessStateError("terminal AgentTurn cannot admit a new StepSnapshot")
            if snapshot.step_index < turn.current_step_index:
                raise HarnessStateError("StepSnapshot step_index cannot rewind current step")
            metadata = await _fetch_one_conn(
                conn, "SELECT * FROM harness_metadata WHERE singleton = 1"
            )
            if metadata is None:
                raise HarnessRecordNotFound("Harness metadata is missing")
            if snapshot.security_revocation_epoch != metadata["security_revocation_epoch"]:
                raise HarnessStateError(
                    "a snapshot must freeze the current security revocation epoch"
                )
            history = await _fetch_one_conn(
                conn,
                "SELECT * FROM inference_histories WHERE conversation_turn_id=?",
                (str(turn.conversation_turn_id),),
            )
            if history is None:
                raise HarnessRecordNotFound(
                    f"InferenceHistory {turn.conversation_turn_id} is missing"
                )
            if snapshot.inference_history_version > history["version"]:
                raise HarnessStateError("snapshot history version is ahead of durable history")
            if snapshot.provider_replay_version > history["replay_version"]:
                raise HarnessStateError("snapshot replay version is ahead of durable replay")
            columns = snapshot.queryable_columns()
            names = ",".join(columns)
            placeholders = ",".join("?" for _ in columns)
            await conn.execute(
                f"""
                INSERT INTO step_snapshots (
                    snapshot_id,format_version,agent_turn_id,step_index,
                    turn_version_at_creation,storage_envelope_json,created_at,{names}
                ) VALUES (?,?,?,?,?,?,?,{placeholders})
                """,
                (
                    str(snapshot.snapshot_id),
                    snapshot.format_version,
                    str(snapshot.agent_turn_id),
                    snapshot.step_index,
                    snapshot.turn_version_at_creation,
                    canonical_json(dump_step_snapshot(snapshot)),
                    snapshot.created_at,
                    *columns.values(),
                ),
            )
            updated = _updated_turn(
                turn,
                at=snapshot.created_at,
                current_step_index=snapshot.step_index,
                active_step_snapshot_id=snapshot.snapshot_id,
            )
            await _update_turn_conn(conn, updated, expected_turn_version)
            await _append_event(
                conn,
                updated,
                "step.snapshot_committed",
                at=snapshot.created_at,
                snapshot_id=snapshot.snapshot_id,
                detail={
                    "format_version": snapshot.format_version,
                    "tool_plan_hash": snapshot.tool_plan.plan_hash(),
                    "tool_count": len(snapshot.tool_plan.bindings),
                    "security_revocation_epoch": snapshot.security_revocation_epoch,
                },
            )
            return snapshot, updated

        return await db.run_in_writer(_tx)

    async def get_step_snapshot(self, snapshot_id: StepSnapshotId) -> StepSnapshot:
        """Load one immutable executable snapshot, failing closed on any divergence."""
        row = await db.fetch_one(
            "SELECT * FROM step_snapshots WHERE snapshot_id = ?", (str(snapshot_id),)
        )
        if row is None:
            raise HarnessRecordNotFound(f"StepSnapshot {snapshot_id} does not exist")
        if row["format_version"] != STEP_SNAPSHOT_EXECUTABLE_FORMAT_VERSION:
            raise UnsupportedFormatVersion(
                "StepSnapshot",
                row["format_version"],
                frozenset({STEP_SNAPSHOT_EXECUTABLE_FORMAT_VERSION}),
            )
        return _step_snapshot_from_row(row)

    async def replay_version(self, conversation_turn_id: ConversationTurnId) -> int:
        """The durable provider-replay checkpoint version for one conversation history."""
        row = await db.fetch_one(
            "SELECT replay_version FROM inference_histories WHERE conversation_turn_id = ?",
            (str(conversation_turn_id),),
        )
        if row is None:
            raise HarnessRecordNotFound(f"InferenceHistory {conversation_turn_id} is missing")
        return row["replay_version"]

    async def security_revocation_epoch(self) -> int:
        """The current durable security revocation epoch."""
        return (await self.metadata()).security_revocation_epoch

    async def advance_security_revocation_epoch(self, *, at: str | None = None) -> int:
        """Advance the revocation epoch, invalidating every earlier grant snapshot.

        Monotonic and coarse on purpose. Fine-grained revocation would need per-grant state that
        an interrupted turn cannot be trusted to have read; an epoch is one comparison that a
        snapshot froze and dispatch re-checks.
        """
        changed_at = at or _now()

        async def _tx(conn: Any) -> int:
            row = await _fetch_one_conn(
                conn, "SELECT * FROM harness_metadata WHERE singleton = 1"
            )
            if row is None:
                raise HarnessRecordNotFound("Harness metadata is missing")
            new_epoch = row["security_revocation_epoch"] + 1
            await conn.execute(
                "UPDATE harness_metadata SET security_revocation_epoch=?,updated_at=? "
                "WHERE singleton=1",
                (new_epoch, changed_at),
            )
            return new_epoch

        return await db.run_in_writer(_tx)

    async def admit_inference_attempt(
        self,
        attempt: InferenceAttempt,
        *,
        expected_turn_version: int,
        at: str | None = None,
    ) -> tuple[StoredInferenceAttempt, AgentTurn]:
        """Persist an admitted attempt before dispatch and bind it to the active turn."""
        attempt = load_attempt(dump_attempt(attempt))
        admitted_at = at or _now()
        if attempt.turn_version_admitted != expected_turn_version:
            raise HarnessStateError("attempt admitted version must equal expected turn version")
        if attempt.dispatch_state != "admitted" or attempt.semantic_state != "active":
            raise HarnessStateError("new InferenceAttempt must be active and admitted")

        async def _tx(conn: Any) -> tuple[StoredInferenceAttempt, AgentTurn]:
            turn = await _turn_conn(conn, attempt.agent_turn_id)
            if turn.state_version != expected_turn_version:
                raise StaleHarnessWrite(
                    f"AgentTurn {turn.id} expected {expected_turn_version}, "
                    f"found {turn.state_version}"
                )
            if turn.is_terminal:
                raise HarnessStateError("terminal AgentTurn cannot admit an InferenceAttempt")
            snapshot = await _fetch_one_conn(
                conn,
                "SELECT agent_turn_id FROM step_snapshots WHERE snapshot_id = ?",
                (str(attempt.step_snapshot_id),),
            )
            if snapshot is None or snapshot["agent_turn_id"] != str(turn.id):
                raise HarnessStateError("attempt snapshot does not belong to its AgentTurn")
            if turn.active_step_snapshot_id != attempt.step_snapshot_id:
                raise HarnessStateError("attempt must bind to the active snapshot identity")
            await conn.execute(
                """
                INSERT INTO inference_attempts (
                    attempt_id,format_version,row_version,agent_turn_id,step_snapshot_id,
                    attempt_generation,turn_version_admitted,dispatch_state,semantic_state,
                    dispatch_barrier_committed,request_semantic_hash,provider_request_id,
                    completion_status,started_at,completed_at,payload_json
                ) VALUES (?,?,0,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(attempt.attempt_id),
                    attempt.format_version,
                    str(attempt.agent_turn_id),
                    str(attempt.step_snapshot_id),
                    attempt.attempt_generation,
                    attempt.turn_version_admitted,
                    attempt.dispatch_state,
                    attempt.semantic_state,
                    int(attempt.dispatch_barrier_committed),
                    attempt.request_semantic_hash,
                    attempt.provider_request_id,
                    attempt.completion_status,
                    attempt.started_at,
                    attempt.completed_at,
                    canonical_json(dump_attempt(attempt)),
                ),
            )
            updated_turn = _updated_turn(
                turn, at=admitted_at, active_inference_attempt_id=attempt.attempt_id
            )
            await _update_turn_conn(conn, updated_turn, expected_turn_version)
            await _append_event(
                conn,
                updated_turn,
                "inference.attempt_admitted",
                at=admitted_at,
                snapshot_id=attempt.step_snapshot_id,
                attempt_id=attempt.attempt_id,
            )
            return StoredInferenceAttempt(attempt, 0), updated_turn

        return await db.run_in_writer(_tx)

    async def get_inference_attempt(
        self, attempt_id: InferenceAttemptId
    ) -> StoredInferenceAttempt:
        """Load one versioned inference attempt."""
        row = await db.fetch_one(
            "SELECT * FROM inference_attempts WHERE attempt_id = ?", (str(attempt_id),)
        )
        if row is None:
            raise HarnessRecordNotFound(f"InferenceAttempt {attempt_id} does not exist")
        return _attempt_from_row(row)

    async def _transition_attempt(
        self,
        attempt_id: InferenceAttemptId,
        *,
        expected_attempt_version: int,
        expected_turn_version: int,
        at: str,
        event_type: str,
        mutate: Callable[[InferenceAttempt], None],
    ) -> tuple[StoredInferenceAttempt, AgentTurn]:
        async def _tx(conn: Any) -> tuple[StoredInferenceAttempt, AgentTurn]:
            stored = await _attempt_conn(conn, attempt_id)
            if stored.row_version != expected_attempt_version:
                raise StaleHarnessWrite(
                    f"InferenceAttempt {attempt_id} expected {expected_attempt_version}, "
                    f"found {stored.row_version}"
                )
            turn = await _turn_conn(conn, stored.attempt.agent_turn_id)
            if turn.state_version != expected_turn_version:
                raise StaleHarnessWrite(
                    f"AgentTurn {turn.id} expected {expected_turn_version}, "
                    f"found {turn.state_version}"
                )
            if event_type == "inference.dispatch_marked":
                if turn.is_terminal:
                    raise HarnessStateError("terminal AgentTurn cannot dispatch a provider attempt")
                if turn.active_inference_attempt_id != stored.attempt.attempt_id:
                    raise HarnessStateError("provider dispatch requires the active inference attempt")
                if turn.active_step_snapshot_id != stored.attempt.step_snapshot_id:
                    raise HarnessStateError("provider dispatch requires the active StepSnapshot")
            updated_attempt = stored.attempt.model_copy(deep=True)
            mutate(updated_attempt)
            updated_attempt = load_attempt(dump_attempt(updated_attempt))
            new_version = stored.row_version + 1
            cursor = await conn.execute(
                """
                UPDATE inference_attempts SET
                    format_version=?,row_version=?,dispatch_state=?,semantic_state=?,
                    dispatch_barrier_committed=?,provider_request_id=?,completion_status=?,
                    started_at=?,completed_at=?,payload_json=?
                WHERE attempt_id=? AND row_version=?
                """,
                (
                    updated_attempt.format_version,
                    new_version,
                    updated_attempt.dispatch_state,
                    updated_attempt.semantic_state,
                    int(updated_attempt.dispatch_barrier_committed),
                    updated_attempt.provider_request_id,
                    updated_attempt.completion_status,
                    updated_attempt.started_at,
                    updated_attempt.completed_at,
                    canonical_json(dump_attempt(updated_attempt)),
                    str(attempt_id),
                    expected_attempt_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleHarnessWrite(f"InferenceAttempt {attempt_id} lost its CAS")
            updated_turn = _updated_turn(turn, at=at)
            await _update_turn_conn(conn, updated_turn, expected_turn_version)
            await _append_event(
                conn,
                updated_turn,
                event_type,
                at=at,
                snapshot_id=updated_attempt.step_snapshot_id,
                attempt_id=attempt_id,
            )
            return StoredInferenceAttempt(updated_attempt, new_version), updated_turn

        return await db.run_in_writer(_tx)

    async def mark_attempt_dispatch_may_have_escaped(
        self,
        attempt_id: InferenceAttemptId,
        *,
        expected_attempt_version: int,
        expected_turn_version: int,
        at: str | None = None,
    ) -> tuple[StoredInferenceAttempt, AgentTurn]:
        """Commit the conservative provider dispatch barrier with two-level CAS."""
        marked_at = at or _now()
        return await self._transition_attempt(
            attempt_id,
            expected_attempt_version=expected_attempt_version,
            expected_turn_version=expected_turn_version,
            at=marked_at,
            event_type="inference.dispatch_marked",
            mutate=lambda value: value.mark_dispatch_may_have_escaped(started_at=marked_at),
        )

    async def complete_attempt(
        self,
        attempt_id: InferenceAttemptId,
        status: InferenceCompletionStatus,
        *,
        expected_attempt_version: int,
        expected_turn_version: int,
        provider_request_id: str | None = None,
        at: str | None = None,
    ) -> tuple[StoredInferenceAttempt, AgentTurn]:
        """Record authoritative completion without losing dispatch-barrier truth."""
        completed_at = at or _now()
        return await self._transition_attempt(
            attempt_id,
            expected_attempt_version=expected_attempt_version,
            expected_turn_version=expected_turn_version,
            at=completed_at,
            event_type="inference.completed",
            mutate=lambda value: value.mark_completed(
                status, completed_at=completed_at, provider_request_id=provider_request_id
            ),
        )

    async def fail_attempt(
        self,
        attempt_id: InferenceAttemptId,
        error: InferenceError,
        *,
        expected_attempt_version: int,
        expected_turn_version: int,
        at: str | None = None,
    ) -> tuple[StoredInferenceAttempt, AgentTurn]:
        """Record a terminal failure while retaining pre/post-dispatch truth."""
        failed_at = at or _now()
        return await self._transition_attempt(
            attempt_id,
            expected_attempt_version=expected_attempt_version,
            expected_turn_version=expected_turn_version,
            at=failed_at,
            event_type="inference.failed",
            mutate=lambda value: value.mark_failed(error, completed_at=failed_at),
        )

    async def cancel_attempt_before_dispatch(
        self,
        attempt_id: InferenceAttemptId,
        *,
        expected_attempt_version: int,
        expected_turn_version: int,
        at: str | None = None,
    ) -> tuple[StoredInferenceAttempt, AgentTurn]:
        """Record cancellation only while durable facts prove dispatch did not escape."""
        cancelled_at = at or _now()
        return await self._transition_attempt(
            attempt_id,
            expected_attempt_version=expected_attempt_version,
            expected_turn_version=expected_turn_version,
            at=cancelled_at,
            event_type="inference.failed",
            mutate=lambda value: value.mark_cancelled_before_dispatch(
                completed_at=cancelled_at
            ),
        )

    async def abandon_attempt(
        self,
        attempt_id: InferenceAttemptId,
        reason: str,
        *,
        expected_attempt_version: int,
        expected_turn_version: int,
        superseded_by_attempt_id: InferenceAttemptId | None = None,
        at: str | None = None,
    ) -> tuple[StoredInferenceAttempt, AgentTurn]:
        """Durably abandon an attempt; item supersession remains an explicit operation."""
        abandoned_at = at or _now()
        return await self._transition_attempt(
            attempt_id,
            expected_attempt_version=expected_attempt_version,
            expected_turn_version=expected_turn_version,
            at=abandoned_at,
            event_type="inference.abandoned",
            mutate=lambda value: value.mark_abandoned(
                reason,
                superseded_by_attempt_id=superseded_by_attempt_id,
                completed_at=abandoned_at,
            ),
        )

    async def append_inference_items(
        self,
        conversation_turn_id: ConversationTurnId,
        agent_turn_id: AgentTurnId,
        items: list[InferenceItem],
        *,
        expected_history_version: int,
        at: str | None = None,
    ) -> tuple[list[InferenceItem], int]:
        """Append finalized items atomically and advance conversation history version."""
        if not items:
            return [], expected_history_version
        appended_at = at or _now()

        async def _tx(conn: Any) -> tuple[list[InferenceItem], int]:
            turn = await _turn_conn(conn, agent_turn_id)
            if turn.conversation_turn_id != conversation_turn_id:
                raise HarnessStateError("history owner does not match the AgentTurn")
            history = await _fetch_one_conn(
                conn,
                "SELECT * FROM inference_histories WHERE conversation_turn_id = ?",
                (str(conversation_turn_id),),
            )
            if history is None:
                raise HarnessRecordNotFound(f"InferenceHistory {conversation_turn_id} is missing")
            if history["version"] != expected_history_version:
                raise StaleHarnessWrite(
                    f"InferenceHistory {conversation_turn_id} expected "
                    f"{expected_history_version}, found {history['version']}"
                )
            next_sequence = history["next_sequence"]
            stored_items: list[InferenceItem] = []
            for offered in items:
                if offered.agent_turn_id not in (None, agent_turn_id):
                    raise HarnessStateError("InferenceItem names another AgentTurn")
                sequence_no = offered.sequence_no
                if sequence_no is None:
                    sequence_no = next_sequence
                if sequence_no != next_sequence:
                    raise HarnessStateError(
                        f"InferenceItem sequence {sequence_no} is not head {next_sequence}"
                    )
                item = offered.model_copy(
                    update={"agent_turn_id": agent_turn_id, "sequence_no": sequence_no}
                )
                item = load_item(dump_item(item))
                if item.producing_attempt_id is not None:
                    attempt = await _fetch_one_conn(
                        conn,
                        "SELECT agent_turn_id FROM inference_attempts WHERE attempt_id = ?",
                        (str(item.producing_attempt_id),),
                    )
                    if attempt is None or attempt["agent_turn_id"] != str(agent_turn_id):
                        raise HarnessStateError("provider item does not name this turn's attempt")
                await conn.execute(
                    """
                    INSERT INTO inference_items (
                        item_id,format_version,conversation_turn_id,agent_turn_id,sequence_no,
                        producing_attempt_id,item_type,superseded_at,superseded_reason,
                        superseding_attempt_id,payload_json,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(item.item_id),
                        item.format_version,
                        str(conversation_turn_id),
                        str(agent_turn_id),
                        item.sequence_no,
                        str(item.producing_attempt_id) if item.producing_attempt_id else None,
                        item.item_type,
                        item.superseded_at,
                        item.superseded_reason,
                        str(item.superseding_attempt_id) if item.superseding_attempt_id else None,
                        canonical_json(dump_item(item)),
                        appended_at,
                    ),
                )
                stored_items.append(item)
                next_sequence += 1
            new_version = expected_history_version + len(stored_items)
            new_replay_version = history["replay_version"] + sum(
                _replay_weight(item) for item in stored_items
            )
            cursor = await conn.execute(
                """
                UPDATE inference_histories
                SET version=?,next_sequence=?,replay_version=?,updated_at=?
                WHERE conversation_turn_id=? AND version=?
                """,
                (
                    new_version,
                    next_sequence,
                    new_replay_version,
                    appended_at,
                    str(conversation_turn_id),
                    expected_history_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleHarnessWrite(f"InferenceHistory {conversation_turn_id} lost its CAS")
            await _append_event(
                conn,
                turn,
                "inference.output_checkpointed",
                at=appended_at,
                detail={
                    "item_count": len(stored_items),
                    "history_version": new_version,
                    "replay_version": new_replay_version,
                },
            )
            return stored_items, new_version

        return await db.run_in_writer(_tx)

    async def list_inference_items(
        self,
        conversation_turn_id: ConversationTurnId,
        *,
        include_superseded: bool = False,
        agent_turn_id: AgentTurnId | None = None,
    ) -> list[InferenceItem]:
        """Read deterministic conversation order, optionally filtered to one turn."""
        rows = await db.fetch_all(
            "SELECT * FROM inference_items WHERE conversation_turn_id=? "
            "ORDER BY sequence_no,item_id",
            (str(conversation_turn_id),),
        )
        items = [_item_from_row(row) for row in rows]
        return [
            item
            for item in items
            if (include_superseded or not item.is_superseded)
            and (agent_turn_id is None or item.agent_turn_id == agent_turn_id)
        ]

    async def supersede_attempt_items(
        self,
        conversation_turn_id: ConversationTurnId,
        attempt_id: InferenceAttemptId,
        *,
        expected_history_version: int,
        reason: str,
        at: str,
        protected_call_ids: tuple[CerebroCallId, ...] = (),
        superseding_attempt_id: InferenceAttemptId | None = None,
    ) -> tuple[list[InferenceItem], int]:
        """Durably apply AR-02 supersession without deleting audit evidence."""

        async def _tx(conn: Any) -> tuple[list[InferenceItem], int]:
            attempt = await _attempt_conn(conn, attempt_id)
            if attempt.attempt.semantic_state != "abandoned":
                raise HarnessStateError(
                    "attempt output may be superseded only after durable abandonment"
                )
            history_row = await _fetch_one_conn(
                conn,
                "SELECT * FROM inference_histories WHERE conversation_turn_id = ?",
                (str(conversation_turn_id),),
            )
            if history_row is None:
                raise HarnessRecordNotFound(f"InferenceHistory {conversation_turn_id} is missing")
            if history_row["version"] != expected_history_version:
                raise StaleHarnessWrite(
                    f"InferenceHistory {conversation_turn_id} expected "
                    f"{expected_history_version}, found {history_row['version']}"
                )
            rows = await _fetch_all_conn(
                conn,
                "SELECT * FROM inference_items WHERE conversation_turn_id=? "
                "ORDER BY sequence_no,item_id",
                (str(conversation_turn_id),),
            )
            history = InferenceHistory(
                conversation_turn_id,
                [_item_from_row(row) for row in rows],
                version=expected_history_version,
            )
            turn = await _turn_conn(conn, attempt.attempt.agent_turn_id)
            if turn.conversation_turn_id != conversation_turn_id:
                raise HarnessStateError("attempt does not belong to this conversation history")
            attempt_call_item_ids = {
                item.item_id
                for item in history.audit_history()
                if isinstance(item, ToolCallItem)
                and item.producing_attempt_id == attempt_id
                and not item.is_superseded
            }
            tool_rows = await _fetch_all_conn(
                conn,
                "SELECT * FROM tool_executions ORDER BY admitted_at,call_id",
            )
            durable_protected_call_ids = {
                stored.execution.call_id
                for stored in (_tool_from_row(row) for row in tool_rows)
                if stored.execution.tool_call_item_id in attempt_call_item_ids
                and stored.execution.may_have_escaped
            }
            all_protected_call_ids = tuple(
                sorted(set(protected_call_ids) | durable_protected_call_ids, key=str)
            )
            superseded = history.supersede_abandoned_attempt(
                attempt_id,
                reason=reason,
                at=at,
                protected_call_ids=all_protected_call_ids,
                superseding_attempt_id=superseding_attempt_id,
            )
            if not superseded:
                return [], expected_history_version
            for item in superseded:
                await conn.execute(
                    """
                    UPDATE inference_items SET
                        superseded_at=?,superseded_reason=?,superseding_attempt_id=?,payload_json=?
                    WHERE item_id=?
                    """,
                    (
                        item.superseded_at,
                        item.superseded_reason,
                        str(item.superseding_attempt_id) if item.superseding_attempt_id else None,
                        canonical_json(dump_item(item)),
                        str(item.item_id),
                    ),
                )
            cursor = await conn.execute(
                "UPDATE inference_histories SET version=?,updated_at=? "
                "WHERE conversation_turn_id=? AND version=?",
                (history.version, at, str(conversation_turn_id), expected_history_version),
            )
            if cursor.rowcount != 1:
                raise StaleHarnessWrite(f"InferenceHistory {conversation_turn_id} lost its CAS")
            await _append_event(
                conn,
                turn,
                "inference.abandoned",
                at=at,
                attempt_id=attempt_id,
                detail={"superseded_item_count": len(superseded)},
            )
            return superseded, history.version

        return await db.run_in_writer(_tx)

    async def history_version(self, conversation_turn_id: ConversationTurnId) -> int:
        """Return the compare-and-set version for one conversation-owned history."""
        row = await db.fetch_one(
            "SELECT version FROM inference_histories WHERE conversation_turn_id = ?",
            (str(conversation_turn_id),),
        )
        if row is None:
            raise HarnessRecordNotFound(f"InferenceHistory {conversation_turn_id} is missing")
        return row["version"]

    async def create_tool_execution(
        self,
        execution: ToolExecution,
        *,
        expected_turn_version: int,
    ) -> StoredToolExecution:
        """Admit one call without making it dispatchable or invoking an executor."""
        execution = load_tool_execution(dump_tool_execution(execution))
        if execution.admitted_turn_version != expected_turn_version:
            raise HarnessStateError("tool admitted version must equal expected turn version")
        if execution.dispatch_state != "not_dispatched":
            raise HarnessStateError("new ToolExecution must be not_dispatched")

        async def _tx(conn: Any) -> StoredToolExecution:
            turn = await _turn_conn(conn, execution.agent_turn_id)
            if turn.state_version != expected_turn_version:
                raise StaleHarnessWrite(
                    f"AgentTurn {turn.id} expected {expected_turn_version}, "
                    f"found {turn.state_version}"
                )
            if turn.is_terminal:
                raise HarnessStateError("terminal AgentTurn cannot admit a ToolExecution")
            snapshot = await _fetch_one_conn(
                conn,
                "SELECT agent_turn_id FROM step_snapshots WHERE snapshot_id = ?",
                (str(execution.step_snapshot_id),),
            )
            if snapshot is None or snapshot["agent_turn_id"] != str(turn.id):
                raise HarnessStateError("tool snapshot does not belong to its AgentTurn")
            item_row = await _fetch_one_conn(
                conn,
                "SELECT * FROM inference_items WHERE item_id = ?",
                (str(execution.tool_call_item_id),),
            )
            if item_row is None:
                raise HarnessRecordNotFound("tool-call inference item is not durable")
            item = _item_from_row(item_row)
            if item.agent_turn_id != execution.agent_turn_id:
                raise HarnessStateError("ToolCallItem does not belong to the ToolExecution turn")
            if (
                not isinstance(item, ToolCallItem)
                or item.call_id != execution.call_id
                or item.tool_key != execution.tool_key
            ):
                raise HarnessStateError("ToolExecution does not match its ToolCallItem")
            await _insert_tool_execution(conn, execution)
            await _append_event(
                conn,
                turn,
                "tool.call_admitted",
                at=execution.admitted_at,
                snapshot_id=execution.step_snapshot_id,
                call_id=execution.call_id,
            )
            return StoredToolExecution(execution, 0)

        return await db.run_in_writer(_tx)

    async def commit_executable_call_checkpoint(
        self,
        *,
        agent_turn_id: AgentTurnId,
        snapshot_id: StepSnapshotId,
        attempt_id: InferenceAttemptId,
        tool_call_item_id: InferenceItemId,
        call_id: CerebroCallId,
        binding: ToolBinding,
        expected_turn_version: int,
        expected_history_version: int,
        expected_replay_version: int,
        stable_operation_key: str | None = None,
        require_provider_call_ref: bool = False,
        required_opaque_kinds: tuple[str, ...] = (),
        at: str | None = None,
    ) -> ExecutableCallCheckpoint:
        """Commit the section 17 / AR-06 pre-side-effect barrier atomically.

        A, B, C, F, G and H may already have been committed by earlier authoritative snapshot
        and output transactions; this verifies them and fails closed if any is missing or stale.
        D, E, E2, I, J, K and L commit together here, in the existing single-writer
        `BEGIN IMMEDIATE` transaction. A crash before that commit leaves the call
        non-executable, and no external tool has been invoked because nothing may invoke one
        until a *later* transaction moves the execution to `dispatch_may_have_escaped`.
        """
        committed_at = at or _now()
        capability = binding.recovery_capability
        if capability.requires_stable_operation_key and not stable_operation_key:
            raise HarnessStateError(
                f"tool {binding.key.canonical()} declares repeat_semantics="
                f"'stable_idempotency_key'; E2 requires a durable operation key before the "
                f"call is dispatch eligible"
            )

        async def _tx(conn: Any) -> ExecutableCallCheckpoint:
            facts = await _verify_executable_barrier(
                conn,
                agent_turn_id=agent_turn_id,
                snapshot_id=snapshot_id,
                attempt_id=attempt_id,
                tool_call_item_id=tool_call_item_id,
                call_id=call_id,
                binding=binding,
                expected_turn_version=expected_turn_version,
                expected_history_version=expected_history_version,
                expected_replay_version=expected_replay_version,
                require_provider_call_ref=require_provider_call_ref,
                required_opaque_kinds=required_opaque_kinds,
            )
            existing = await _fetch_one_conn(
                conn,
                "SELECT call_id FROM tool_executions WHERE call_id=? OR tool_call_item_id=?",
                (str(call_id), str(tool_call_item_id)),
            )
            if existing is not None:
                raise DuplicateHarnessIdentity(
                    f"ToolCallItem {tool_call_item_id} already has execution identity "
                    f"{existing['call_id']}; one completed call has exactly one ToolExecution"
                )
            # I, J, E and E2 in one row.
            execution = ToolExecution(
                call_id=call_id,
                agent_turn_id=facts.turn.id,
                step_snapshot_id=facts.snapshot.snapshot_id,
                tool_call_item_id=tool_call_item_id,
                tool_key=facts.binding.key,
                admitted_turn_version=expected_turn_version,
                binding_generation=facts.binding.binding_generation,
                binding_executor_identity=facts.binding.executor_identity,
                recovery_capability=facts.binding.recovery_capability,
                stable_operation_key=stable_operation_key,
                admitted_at=committed_at,
            )
            execution = load_tool_execution(dump_tool_execution(execution))
            if not execution.dispatch_eligible:
                raise HarnessStateError("E2 is unsatisfied; the call is not dispatch eligible")
            await _insert_tool_execution(conn, execution)
            # K, and L in the same transaction.
            updated_turn = _updated_turn(facts.turn, at=committed_at)
            await _update_turn_conn(conn, updated_turn, expected_turn_version)
            await _append_event(
                conn,
                updated_turn,
                "tool.call_admitted",
                at=committed_at,
                snapshot_id=facts.snapshot.snapshot_id,
                attempt_id=facts.attempt.attempt_id,
                call_id=call_id,
                detail={
                    "checkpoint": "executable_pre_side_effect",
                    "tool_key": facts.binding.key.canonical(),
                    "binding_generation": str(facts.binding.binding_generation),
                    "repeat_semantics": facts.binding.recovery_capability.repeat_semantics,
                    "stable_operation_key_assigned": bool(stable_operation_key),
                    "history_version": facts.history_version,
                    "replay_version": facts.replay_version,
                    "security_revocation_epoch": facts.security_revocation_epoch,
                },
            )
            return ExecutableCallCheckpoint(
                execution=StoredToolExecution(execution, 0),
                turn=updated_turn,
                snapshot=facts.snapshot,
                history_version=facts.history_version,
                replay_version=facts.replay_version,
            )

        return await db.run_in_writer(_tx)

    async def mark_tool_dispatch_after_barrier(
        self,
        call_id: CerebroCallId,
        *,
        binding: ToolBinding,
        expected_tool_version: int,
        expected_turn_version: int,
        expected_history_version: int,
        expected_replay_version: int,
        require_provider_call_ref: bool = False,
        required_opaque_kinds: tuple[str, ...] = (),
        at: str | None = None,
    ) -> tuple[StoredToolExecution, AgentTurn]:
        """Re-verify the whole barrier and commit dispatch uncertainty in one transaction.

        Verification and the dispatch mark cannot be two transactions. If they were, a
        revocation, an abandonment or a rebinding could land between them and the executor would
        be invoked against facts that were true a moment ago.
        """
        marked_at = at or _now()

        async def _tx(conn: Any) -> tuple[StoredToolExecution, AgentTurn]:
            stored = await _tool_conn(conn, call_id)
            if stored.row_version != expected_tool_version:
                raise StaleHarnessWrite(
                    f"ToolExecution {call_id} expected {expected_tool_version}, "
                    f"found {stored.row_version}"
                )
            execution = stored.execution
            if execution.dispatch_state != "not_dispatched":
                raise HarnessStateError(
                    f"ToolExecution {call_id} is already {execution.dispatch_state}; the "
                    f"dispatch mark is committed exactly once"
                )
            if not execution.binds_exactly(binding):
                raise HarnessStateError(
                    "the offered binding is not the frozen executable identity of this call"
                )
            current_turn = await _turn_conn(conn, execution.agent_turn_id)
            active_attempt_id = current_turn.active_inference_attempt_id
            if active_attempt_id is None:
                raise HarnessStateError(
                    "the turn has no active InferenceAttempt; barrier condition B is unmet"
                )
            facts = await _verify_executable_barrier(
                conn,
                agent_turn_id=execution.agent_turn_id,
                snapshot_id=execution.step_snapshot_id,
                attempt_id=active_attempt_id,
                tool_call_item_id=execution.tool_call_item_id,
                call_id=call_id,
                binding=binding,
                expected_turn_version=expected_turn_version,
                expected_history_version=expected_history_version,
                expected_replay_version=expected_replay_version,
                require_provider_call_ref=require_provider_call_ref,
                required_opaque_kinds=required_opaque_kinds,
            )
            updated = execution.model_copy(deep=True)
            updated.mark_dispatch_may_have_escaped(at=marked_at)
            updated = load_tool_execution(dump_tool_execution(updated))
            new_version = stored.row_version + 1
            cursor = await conn.execute(
                """
                UPDATE tool_executions SET
                    row_version=?,dispatch_state=?,dispatch_marked_at=?,payload_json=?
                WHERE call_id=? AND row_version=?
                """,
                (
                    new_version,
                    updated.dispatch_state,
                    updated.dispatch_marked_at,
                    canonical_json(dump_tool_execution(updated)),
                    str(call_id),
                    expected_tool_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleHarnessWrite(f"ToolExecution {call_id} lost its CAS")
            count_row = await _fetch_one_conn(
                conn,
                "SELECT COUNT(*) AS count FROM tool_executions WHERE agent_turn_id=? "
                "AND (dispatch_state='dispatch_may_have_escaped' "
                "OR resolution_kind='indeterminate')",
                (str(facts.turn.id),),
            )
            unresolved_count = count_row["count"]
            updated_turn = _updated_turn(
                facts.turn,
                at=marked_at,
                unresolved_effect_count=unresolved_count,
                needs_attention=unresolved_count > 0,
            )
            await _update_turn_conn(conn, updated_turn, expected_turn_version)
            await _append_event(
                conn,
                updated_turn,
                "tool.dispatch_marked",
                at=marked_at,
                snapshot_id=updated.step_snapshot_id,
                call_id=call_id,
                detail={"binding_generation": str(updated.binding_generation)},
            )
            return StoredToolExecution(updated, new_version), updated_turn

        return await db.run_in_writer(_tx)

    async def get_artifact(self, artifact_ref: ArtifactRef) -> StoredArtifact:
        """Read one artifact index row. The payload itself comes from `ArtifactStore.read`."""
        row = await db.fetch_one(
            "SELECT * FROM harness_artifacts WHERE artifact_ref = ?", (str(artifact_ref),)
        )
        if row is None:
            raise HarnessRecordNotFound(f"artifact {artifact_ref} does not exist")
        return _artifact_from_row(row)

    async def list_call_artifacts(self, call_id: CerebroCallId) -> list[StoredArtifact]:
        """Every durable raw-output artifact recorded for one call, oldest first."""
        rows = await db.fetch_all(
            "SELECT * FROM harness_artifacts WHERE call_id=? ORDER BY created_at,artifact_ref",
            (str(call_id),),
        )
        return [_artifact_from_row(row) for row in rows]

    async def get_tool_execution(self, call_id: CerebroCallId) -> StoredToolExecution:
        """Load one versioned ToolExecution."""
        row = await db.fetch_one(
            "SELECT * FROM tool_executions WHERE call_id = ?", (str(call_id),)
        )
        if row is None:
            raise HarnessRecordNotFound(f"ToolExecution {call_id} does not exist")
        return _tool_from_row(row)

    async def _transition_tool(
        self,
        call_id: CerebroCallId,
        *,
        expected_tool_version: int,
        expected_turn_version: int,
        at: str,
        event_type: str,
        mutate: Callable[[ToolExecution], None],
        result_item: ToolResultItem | None = None,
        expected_history_version: int | None = None,
        artifact: StagedArtifact | None = None,
    ) -> tuple[StoredToolExecution, AgentTurn]:
        async def _tx(conn: Any) -> tuple[StoredToolExecution, AgentTurn]:
            stored = await _tool_conn(conn, call_id)
            if stored.row_version != expected_tool_version:
                raise StaleHarnessWrite(
                    f"ToolExecution {call_id} expected {expected_tool_version}, "
                    f"found {stored.row_version}"
                )
            turn = await _turn_conn(conn, stored.execution.agent_turn_id)
            if turn.state_version != expected_turn_version:
                raise StaleHarnessWrite(
                    f"AgentTurn {turn.id} expected {expected_turn_version}, "
                    f"found {turn.state_version}"
                )
            if event_type == "tool.dispatch_marked" and turn.is_terminal:
                raise HarnessStateError("terminal AgentTurn cannot dispatch a tool execution")
            updated = stored.execution.model_copy(deep=True)
            mutate(updated)
            updated = load_tool_execution(dump_tool_execution(updated))
            event_detail: dict[str, Any] = {}
            if result_item is not None:
                if result_item.call_id != updated.call_id or result_item.tool_key != updated.tool_key:
                    raise HarnessStateError("ToolResultItem does not match its ToolExecution")
                if expected_history_version is None:
                    raise HarnessStateError("result append requires expected_history_version")
                # A reference that outlives its object is worse than no reference: it looks like
                # durable evidence and reads as a missing file. Both directions fail closed.
                if result_item.raw_output_ref is not None and artifact is None:
                    raise HarnessStateError(
                        "a committed raw_output_ref requires its staged durable artifact"
                    )
                if artifact is not None:
                    if result_item.raw_output_ref != artifact.artifact_ref:
                        raise HarnessStateError(
                            "ToolResultItem.raw_output_ref does not name the staged artifact"
                        )
                    if artifact.call_id != updated.call_id:
                        raise HarnessStateError("staged artifact belongs to another call")
                    if updated.raw_output_ref != artifact.artifact_ref:
                        raise HarnessStateError(
                            "ToolExecution must reference the staged raw output artifact"
                        )
                    await conn.execute(
                        """
                        INSERT INTO harness_artifacts (
                            artifact_ref,format_version,agent_turn_id,call_id,tool_key,
                            binding_generation,content_type,storage_backend,byte_size,
                            content_sha256,inline_payload,relative_path,retention_policy,
                            provenance_json,created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        artifact.insert_values(),
                    )
                    event_detail["artifact_ref"] = str(artifact.artifact_ref)
                    event_detail["raw_output_bytes"] = artifact.byte_size
                stored_result, history_version = await _append_tool_result_conn(
                    conn,
                    turn,
                    result_item,
                    expected_history_version=expected_history_version,
                    at=at,
                )
                if updated.model_output_item_id != stored_result.item_id:
                    raise HarnessStateError("ToolExecution must reference the stored result item")
                event_detail["history_version"] = history_version
            resolution = updated.resolution
            kind = resolution.resolution_kind if resolution is not None else None
            status = resolution.status if resolution is not None and kind == "known" else None
            reason = (
                resolution.reason if resolution is not None and kind == "indeterminate" else None
            )
            new_version = stored.row_version + 1
            cursor = await conn.execute(
                """
                UPDATE tool_executions SET
                    format_version=?,row_version=?,dispatch_state=?,resolution_kind=?,
                    resolution_status=?,resolution_reason=?,stable_operation_key=?,
                    dispatch_marked_at=?,resolved_at=?,payload_json=?,
                    raw_output_ref=?,model_output_item_id=?
                WHERE call_id=? AND row_version=?
                """,
                (
                    updated.format_version,
                    new_version,
                    updated.dispatch_state,
                    kind,
                    status,
                    reason,
                    updated.stable_operation_key,
                    updated.dispatch_marked_at,
                    updated.resolved_at,
                    canonical_json(dump_tool_execution(updated)),
                    str(updated.raw_output_ref) if updated.raw_output_ref is not None else None,
                    (
                        str(updated.model_output_item_id)
                        if updated.model_output_item_id is not None
                        else None
                    ),
                    str(call_id),
                    expected_tool_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleHarnessWrite(f"ToolExecution {call_id} lost its CAS")
            count_row = await _fetch_one_conn(
                conn,
                "SELECT COUNT(*) AS count FROM tool_executions WHERE agent_turn_id=? "
                "AND (dispatch_state='dispatch_may_have_escaped' "
                "OR resolution_kind='indeterminate')",
                (str(turn.id),),
            )
            unresolved_count = count_row["count"]
            updated_turn = _updated_turn(
                turn,
                at=at,
                unresolved_effect_count=unresolved_count,
                needs_attention=unresolved_count > 0,
            )
            await _update_turn_conn(conn, updated_turn, expected_turn_version)
            await _append_event(
                conn,
                updated_turn,
                event_type,
                at=at,
                snapshot_id=updated.step_snapshot_id,
                call_id=call_id,
                detail=event_detail,
            )
            return StoredToolExecution(updated, new_version), updated_turn

        return await db.run_in_writer(_tx)

    async def mark_tool_dispatch_may_have_escaped(
        self,
        call_id: CerebroCallId,
        *,
        expected_tool_version: int,
        expected_turn_version: int,
        at: str | None = None,
    ) -> tuple[StoredToolExecution, AgentTurn]:
        """Commit tool dispatch uncertainty and turn attention in one transaction.

        The Phase 1B primitive, kept for the store-level regressions that exercise dispatch
        uncertainty directly. It does **not** verify the executable pre-side-effect barrier, so it
        is not the path an executor may be invoked behind: `HarnessToolRuntime` uses
        `mark_tool_dispatch_after_barrier`, which re-verifies A-L/E2 in the same transaction.
        """
        marked_at = at or _now()
        return await self._transition_tool(
            call_id,
            expected_tool_version=expected_tool_version,
            expected_turn_version=expected_turn_version,
            at=marked_at,
            event_type="tool.dispatch_marked",
            mutate=lambda value: value.mark_dispatch_may_have_escaped(at=marked_at),
        )

    async def resolve_tool_known(
        self,
        call_id: CerebroCallId,
        status: Any,
        *,
        expected_tool_version: int,
        expected_turn_version: int,
        result_item: ToolResultItem | None = None,
        expected_history_version: int | None = None,
        artifact: StagedArtifact | None = None,
        at: str | None = None,
    ) -> tuple[StoredToolExecution, AgentTurn]:
        """Commit a known outcome, its raw evidence and attention in one transaction."""
        if (result_item is None) != (expected_history_version is None):
            raise HarnessStateError(
                "result_item and expected_history_version must be supplied together"
            )
        if artifact is not None and result_item is None:
            raise HarnessStateError("a staged artifact needs its canonical ToolResultItem")
        resolved_at = at or _now()
        return await self._transition_tool(
            call_id,
            expected_tool_version=expected_tool_version,
            expected_turn_version=expected_turn_version,
            at=resolved_at,
            event_type="tool.resolved",
            mutate=lambda value: value.resolve_known(
                status,
                at=resolved_at,
                raw_output_ref=artifact.artifact_ref if artifact is not None else None,
                model_output_item_id=result_item.item_id if result_item is not None else None,
            ),
            result_item=result_item,
            expected_history_version=expected_history_version,
            artifact=artifact,
        )

    async def resolve_tool_indeterminate(
        self,
        call_id: CerebroCallId,
        reason: str,
        *,
        expected_tool_version: int,
        expected_turn_version: int,
        reconciliation_attempted: bool = False,
        at: str | None = None,
    ) -> tuple[StoredToolExecution, AgentTurn]:
        """Commit truthful indeterminacy without clearing durable attention."""
        resolved_at = at or _now()
        return await self._transition_tool(
            call_id,
            expected_tool_version=expected_tool_version,
            expected_turn_version=expected_turn_version,
            at=resolved_at,
            event_type="tool.indeterminate",
            mutate=lambda value: value.resolve_indeterminate(
                reason,
                at=resolved_at,
                reconciliation_attempted=reconciliation_attempted,
            ),
        )

    async def list_turns_needing_attention(self) -> list[AgentTurn]:
        """Return the durable operator-discovery surface for uncertain effects."""
        rows = await db.fetch_all("SELECT * FROM agent_turns ORDER BY updated_at,id")
        turns = [_turn_from_row(row) for row in rows]
        return [turn for turn in turns if turn.needs_attention]

    async def list_unresolved_tool_executions(
        self, turn_id: AgentTurnId
    ) -> list[StoredToolExecution]:
        """List unresolved calls with identity, tool key, state and reason."""
        rows = await db.fetch_all(
            "SELECT * FROM tool_executions WHERE agent_turn_id=? ORDER BY admitted_at,call_id",
            (str(turn_id),),
        )
        executions = [_tool_from_row(row) for row in rows]
        return [stored for stored in executions if stored.execution.is_unresolved_effect]

    async def list_turn_events(self, turn_id: AgentTurnId) -> list[dict[str, Any]]:
        """Read sparse semantic transition evidence in monotonic order."""
        rows = await db.fetch_all(
            "SELECT * FROM turn_events WHERE agent_turn_id=? ORDER BY event_sequence",
            (str(turn_id),),
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            if row["event_format_version"] != TURN_EVENT_FORMAT_VERSION:
                raise UnsupportedFormatVersion(
                    "TurnEvent",
                    row["event_format_version"],
                    frozenset({TURN_EVENT_FORMAT_VERSION}),
                )
            events.append(_json_object(row["payload_json"], "TurnEvent"))
        return events
