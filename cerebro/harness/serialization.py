"""Versioned serialization for the canonical Harness contracts.

Three families carry their own `format_version` and are versioned independently: inference
items, inference attempts and tool executions (AR-10). A schema epoch is not a substitute — a
row has to be readable on its own terms, without knowing which epoch wrote it.

Reads are strict. An unknown or future `format_version` raises rather than being parsed
optimistically, because a field this build silently ignores is a replay requirement it silently
drops.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ConfigDict, TypeAdapter, ValidationError

from cerebro.harness.attempts import INFERENCE_ATTEMPT_FORMAT_VERSION, InferenceAttempt
from cerebro.harness.events import InferenceEvent
from cerebro.harness.exceptions import UnsupportedFormatVersion
from cerebro.harness.execution import TOOL_EXECUTION_FORMAT_VERSION, ToolExecution
from cerebro.harness.items import INFERENCE_ITEM_FORMAT_VERSION, InferenceItem
from cerebro.harness.request import InferenceRequest
from cerebro.harness.snapshot import (
    STEP_SNAPSHOT_FORMAT_VERSION,
    TOOL_PLAN_FORMAT_VERSION,
    StepSnapshot,
    ToolPlanSnapshot,
)
from cerebro.harness.turn import AGENT_TURN_FORMAT_VERSION, AgentTurn
from cerebro.harness.wake import CAUSAL_WAKE_KEY_VERSION

__all__ = [
    "SUPPORTED_ATTEMPT_FORMAT_VERSIONS",
    "SUPPORTED_ITEM_FORMAT_VERSIONS",
    "SUPPORTED_STEP_SNAPSHOT_FORMAT_VERSIONS",
    "SUPPORTED_TOOL_PLAN_FORMAT_VERSIONS",
    "SUPPORTED_TURN_FORMAT_VERSIONS",
    "SUPPORTED_TOOL_EXECUTION_FORMAT_VERSIONS",
    "canonical_json",
    "dump_attempt",
    "dump_event",
    "dump_item",
    "dump_request",
    "dump_step_snapshot",
    "dump_tool_execution",
    "dump_tool_plan",
    "dump_turn",
    "load_attempt",
    "load_event",
    "load_item",
    "load_request",
    "load_step_snapshot",
    "load_tool_execution",
    "load_tool_plan",
    "load_turn",
]

SUPPORTED_ITEM_FORMAT_VERSIONS: frozenset[int] = frozenset({INFERENCE_ITEM_FORMAT_VERSION})
SUPPORTED_ATTEMPT_FORMAT_VERSIONS: frozenset[int] = frozenset({INFERENCE_ATTEMPT_FORMAT_VERSION})
SUPPORTED_TOOL_EXECUTION_FORMAT_VERSIONS: frozenset[int] = frozenset(
    {1, TOOL_EXECUTION_FORMAT_VERSION}
)
SUPPORTED_TURN_FORMAT_VERSIONS: frozenset[int] = frozenset({AGENT_TURN_FORMAT_VERSION})
SUPPORTED_STEP_SNAPSHOT_FORMAT_VERSIONS: frozenset[int] = frozenset(
    {STEP_SNAPSHOT_FORMAT_VERSION}
)
SUPPORTED_TOOL_PLAN_FORMAT_VERSIONS: frozenset[int] = frozenset({TOOL_PLAN_FORMAT_VERSION})

_HIDDEN_INPUT_CONFIG = ConfigDict(hide_input_in_errors=True)
_ITEM_ADAPTER: TypeAdapter[Any] = TypeAdapter(InferenceItem, config=_HIDDEN_INPUT_CONFIG)
_EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(InferenceEvent, config=_HIDDEN_INPUT_CONFIG)


def canonical_json(payload: Any) -> str:
    """Deterministic JSON text. Used wherever bytes are hashed or compared."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _require_version(kind: str, data: dict[str, Any], supported: frozenset[int]) -> None:
    if "format_version" not in data:
        raise UnsupportedFormatVersion(kind, None, supported)
    version = data["format_version"]
    if version not in supported:
        raise UnsupportedFormatVersion(kind, version, supported)


# -- agent turns -------------------------------------------------------------------

def dump_turn(turn: AgentTurn) -> dict[str, Any]:
    """Serialize one canonical durable turn."""
    return turn.model_dump(mode="json")


def load_turn(data: dict[str, Any]) -> AgentTurn:
    """Load a turn while failing closed on turn and nested wake versions."""
    _require_version("AgentTurn", data, SUPPORTED_TURN_FORMAT_VERSIONS)
    wake = data.get("causal_wake_key")
    wake_version = wake.get("key_version") if isinstance(wake, dict) else None
    if wake_version != CAUSAL_WAKE_KEY_VERSION:
        raise UnsupportedFormatVersion(
            "CausalWakeKey", wake_version, frozenset({CAUSAL_WAKE_KEY_VERSION})
        )
    return AgentTurn.model_validate(data)


# -- inference items ----------------------------------------------------------------

def dump_item(item: Any) -> dict[str, Any]:
    """Serialize one canonical item, opaque payload included.

    Replay material is retained exactly here. Redaction belongs to log and UI projections, not
    to the durable form: an adapter cannot continue a conversation from a redacted signature.
    """
    return item.model_dump(mode="json")


def load_item(data: dict[str, Any]) -> Any:
    _require_version("InferenceItem", data, SUPPORTED_ITEM_FORMAT_VERSIONS)
    return _ITEM_ADAPTER.validate_python(data)


# -- executable step snapshots ------------------------------------------------------
#
# The strictest family in the package. A snapshot is the sole record of what was executable, so
# an unrecognised snapshot or tool-plan version is refused rather than parsed for the fields
# this build happens to understand.

def dump_step_snapshot(snapshot: StepSnapshot) -> dict[str, Any]:
    """Serialize one immutable executable snapshot."""
    return snapshot.model_dump(mode="json")


def load_step_snapshot(data: dict[str, Any]) -> StepSnapshot:
    """Load a snapshot, failing closed on both the snapshot and nested tool-plan versions."""
    _require_version("StepSnapshot", data, SUPPORTED_STEP_SNAPSHOT_FORMAT_VERSIONS)
    plan = data.get("tool_plan")
    plan_version = plan.get("format_version") if isinstance(plan, dict) else None
    if plan_version not in SUPPORTED_TOOL_PLAN_FORMAT_VERSIONS:
        raise UnsupportedFormatVersion(
            "ToolPlanSnapshot", plan_version, SUPPORTED_TOOL_PLAN_FORMAT_VERSIONS
        )
    return StepSnapshot.model_validate(data)


def dump_tool_plan(plan: ToolPlanSnapshot) -> dict[str, Any]:
    return plan.model_dump(mode="json")


def load_tool_plan(data: dict[str, Any]) -> ToolPlanSnapshot:
    _require_version("ToolPlanSnapshot", data, SUPPORTED_TOOL_PLAN_FORMAT_VERSIONS)
    return ToolPlanSnapshot.model_validate(data)


# -- inference attempts -------------------------------------------------------------

def dump_attempt(attempt: InferenceAttempt) -> dict[str, Any]:
    return attempt.model_dump(mode="json")


def load_attempt(data: dict[str, Any]) -> InferenceAttempt:
    _require_version("InferenceAttempt", data, SUPPORTED_ATTEMPT_FORMAT_VERSIONS)
    return InferenceAttempt.model_validate(data)


# -- tool executions ----------------------------------------------------------------

def dump_tool_execution(execution: ToolExecution) -> dict[str, Any]:
    return execution.model_dump(mode="json")


def load_tool_execution(data: dict[str, Any]) -> ToolExecution:
    _require_version("ToolExecution", data, SUPPORTED_TOOL_EXECUTION_FORMAT_VERSIONS)
    return ToolExecution.model_validate(data)


# -- requests and events ------------------------------------------------------------
#
# Neither is a persisted family in Phase 1A. They round-trip so adapter tests and fixtures can
# compare structures without hand-written dictionaries.

def dump_request(request: InferenceRequest) -> dict[str, Any]:
    return request.model_dump(mode="json")


def load_request(data: dict[str, Any]) -> InferenceRequest:
    return InferenceRequest.model_validate(data)


def dump_event(event: Any) -> dict[str, Any]:
    return event.model_dump(mode="json")


def load_event(data: dict[str, Any]) -> Any:
    try:
        return _EVENT_ADAPTER.validate_python(data)
    except ValidationError as exc:
        raise ValueError(f"not a canonical InferenceEvent: {data.get('event_type')!r}") from exc
