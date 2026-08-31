-- Harness v1 Phase 1B additive durable execution store.
-- Collaboration messages, product tasks, legacy tool_calls and audit_events remain untouched.

CREATE TABLE IF NOT EXISTS harness_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_epoch INTEGER NOT NULL CHECK (schema_epoch >= 1),
    storage_format_version INTEGER NOT NULL CHECK (storage_format_version >= 1),
    active_execution_epoch INTEGER NOT NULL CHECK (active_execution_epoch >= 0),
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO harness_metadata (
    singleton, schema_epoch, storage_format_version, active_execution_epoch, updated_at
) VALUES (1, 1, 1, 0, datetime('now'));

CREATE TABLE IF NOT EXISTS agent_turns (
    id TEXT PRIMARY KEY,
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    state_version INTEGER NOT NULL CHECK (state_version >= 0),
    execution_epoch INTEGER NOT NULL CHECK (execution_epoch >= 0),
    conversation_turn_id TEXT NOT NULL,
    causal_wake_serialized TEXT NOT NULL UNIQUE,
    causal_wake_hash TEXT NOT NULL UNIQUE,
    wake_kind TEXT NOT NULL CHECK (
        wake_kind IN ('direct_message', 'channel_poll', 'explicit_turn')
    ),
    target_agent_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    trigger_message_id INTEGER,
    occurrence_id TEXT,
    agent_id TEXT NOT NULL,
    root_agent_turn_id TEXT,
    parent_agent_turn_id TEXT,
    product_task_id TEXT,
    lifecycle TEXT NOT NULL CHECK (
        lifecycle IN ('queued', 'running', 'suspended', 'completed', 'cancelled', 'failed')
    ),
    suspension_reason TEXT,
    cancel_requested_at TEXT,
    current_step_index INTEGER NOT NULL CHECK (current_step_index >= 0),
    active_step_snapshot_id TEXT,
    active_inference_attempt_id TEXT,
    product_outcome_kind TEXT CHECK (
        product_outcome_kind IS NULL OR product_outcome_kind IN (
            'final_message', 'topic_pass', 'topic_silent_stop', 'fail_closed_error'
        )
    ),
    final_message_id INTEGER,
    failure_kind TEXT,
    needs_attention INTEGER NOT NULL CHECK (needs_attention IN (0, 1)),
    unresolved_effect_count INTEGER NOT NULL CHECK (unresolved_effect_count >= 0),
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT,
    completed_at TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    CHECK (lifecycle != 'suspended' OR suspension_reason IS NOT NULL),
    CHECK (lifecycle != 'completed' OR product_outcome_kind IS NOT NULL),
    CHECK (
        needs_attention = CASE WHEN unresolved_effect_count > 0 THEN 1 ELSE 0 END
    ),
    FOREIGN KEY (root_agent_turn_id) REFERENCES agent_turns(id),
    FOREIGN KEY (parent_agent_turn_id) REFERENCES agent_turns(id)
);

CREATE TABLE IF NOT EXISTS inference_histories (
    conversation_turn_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version >= 0),
    next_sequence INTEGER NOT NULL CHECK (next_sequence >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turn_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_format_version INTEGER NOT NULL CHECK (event_format_version >= 1),
    agent_turn_id TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK (event_sequence >= 0),
    event_type TEXT NOT NULL,
    resulting_turn_state_version INTEGER NOT NULL CHECK (resulting_turn_state_version >= 0),
    step_snapshot_id TEXT,
    inference_attempt_id TEXT,
    cerebro_call_id TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL,
    UNIQUE (agent_turn_id, event_sequence),
    FOREIGN KEY (agent_turn_id) REFERENCES agent_turns(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS step_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    agent_turn_id TEXT NOT NULL,
    step_index INTEGER NOT NULL CHECK (step_index >= 0),
    turn_version_at_creation INTEGER NOT NULL CHECK (turn_version_at_creation >= 0),
    storage_envelope_json TEXT NOT NULL CHECK (json_valid(storage_envelope_json)),
    created_at TEXT NOT NULL,
    UNIQUE (agent_turn_id, step_index, snapshot_id),
    FOREIGN KEY (agent_turn_id) REFERENCES agent_turns(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS inference_attempts (
    attempt_id TEXT PRIMARY KEY,
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    row_version INTEGER NOT NULL CHECK (row_version >= 0),
    agent_turn_id TEXT NOT NULL,
    step_snapshot_id TEXT NOT NULL,
    attempt_generation INTEGER NOT NULL CHECK (attempt_generation >= 1),
    turn_version_admitted INTEGER NOT NULL CHECK (turn_version_admitted >= 0),
    dispatch_state TEXT NOT NULL CHECK (
        dispatch_state IN ('admitted', 'dispatch_may_have_escaped', 'terminal')
    ),
    semantic_state TEXT NOT NULL CHECK (
        semantic_state IN (
            'active', 'completed', 'failed', 'abandoned', 'cancelled_before_dispatch'
        )
    ),
    dispatch_barrier_committed INTEGER NOT NULL CHECK (
        dispatch_barrier_committed IN (0, 1)
    ),
    request_semantic_hash TEXT NOT NULL,
    provider_request_id TEXT,
    completion_status TEXT,
    started_at TEXT,
    completed_at TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    FOREIGN KEY (agent_turn_id) REFERENCES agent_turns(id) ON DELETE RESTRICT,
    FOREIGN KEY (step_snapshot_id) REFERENCES step_snapshots(snapshot_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS inference_items (
    item_id TEXT PRIMARY KEY,
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    conversation_turn_id TEXT NOT NULL,
    agent_turn_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 0),
    producing_attempt_id TEXT,
    item_type TEXT NOT NULL CHECK (
        item_type IN ('message', 'tool_call', 'tool_result', 'reasoning_summary', 'provider_opaque')
    ),
    superseded_at TEXT,
    superseded_reason TEXT,
    superseding_attempt_id TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL,
    UNIQUE (conversation_turn_id, sequence_no),
    FOREIGN KEY (conversation_turn_id) REFERENCES inference_histories(conversation_turn_id),
    FOREIGN KEY (agent_turn_id) REFERENCES agent_turns(id) ON DELETE RESTRICT,
    FOREIGN KEY (producing_attempt_id) REFERENCES inference_attempts(attempt_id),
    FOREIGN KEY (superseding_attempt_id) REFERENCES inference_attempts(attempt_id)
);

CREATE TABLE IF NOT EXISTS tool_executions (
    call_id TEXT PRIMARY KEY,
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    row_version INTEGER NOT NULL CHECK (row_version >= 0),
    agent_turn_id TEXT NOT NULL,
    step_snapshot_id TEXT NOT NULL,
    tool_call_item_id TEXT NOT NULL,
    tool_key TEXT NOT NULL,
    admitted_turn_version INTEGER NOT NULL CHECK (admitted_turn_version >= 0),
    dispatch_state TEXT NOT NULL CHECK (
        dispatch_state IN ('not_dispatched', 'dispatch_may_have_escaped', 'resolved')
    ),
    resolution_kind TEXT CHECK (
        resolution_kind IS NULL OR resolution_kind IN ('known', 'indeterminate')
    ),
    resolution_status TEXT,
    resolution_reason TEXT,
    binding_generation TEXT NOT NULL,
    stable_operation_key TEXT,
    admitted_at TEXT NOT NULL,
    dispatch_marked_at TEXT,
    resolved_at TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    CHECK (
        (dispatch_state = 'resolved' AND resolution_kind IS NOT NULL)
        OR (dispatch_state != 'resolved' AND resolution_kind IS NULL)
    ),
    CHECK (resolution_kind != 'indeterminate' OR dispatch_marked_at IS NOT NULL),
    FOREIGN KEY (agent_turn_id) REFERENCES agent_turns(id) ON DELETE RESTRICT,
    FOREIGN KEY (step_snapshot_id) REFERENCES step_snapshots(snapshot_id) ON DELETE RESTRICT,
    FOREIGN KEY (tool_call_item_id) REFERENCES inference_items(item_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_agent_turns_recovery
    ON agent_turns(execution_epoch, lifecycle, created_at, id);
CREATE INDEX IF NOT EXISTS idx_agent_turns_attention
    ON agent_turns(needs_attention, updated_at, id);
CREATE INDEX IF NOT EXISTS idx_turn_events_turn_sequence
    ON turn_events(agent_turn_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_inference_items_conversation_order
    ON inference_items(conversation_turn_id, sequence_no, item_id);
CREATE INDEX IF NOT EXISTS idx_inference_items_turn_order
    ON inference_items(agent_turn_id, sequence_no, item_id);
CREATE INDEX IF NOT EXISTS idx_inference_items_attempt
    ON inference_items(producing_attempt_id, sequence_no);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inference_attempts_turn_generation
    ON inference_attempts(agent_turn_id, attempt_generation);
CREATE INDEX IF NOT EXISTS idx_tool_executions_turn_state
    ON tool_executions(agent_turn_id, dispatch_state, resolution_kind, call_id);

CREATE TRIGGER IF NOT EXISTS trg_agent_turns_version_and_lifecycle
BEFORE UPDATE ON agent_turns
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.state_version != OLD.state_version + 1
        THEN RAISE(ABORT, 'agent_turn state_version must advance exactly once')
    END;
    SELECT CASE
        WHEN OLD.lifecycle IN ('completed', 'cancelled', 'failed')
             AND NEW.lifecycle != OLD.lifecycle
        THEN RAISE(ABORT, 'terminal agent_turn lifecycle cannot change')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_step_snapshots_immutable
BEFORE UPDATE ON step_snapshots
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'step snapshot identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_inference_attempts_monotonic
BEFORE UPDATE ON inference_attempts
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.row_version != OLD.row_version + 1
        THEN RAISE(ABORT, 'inference attempt row_version must advance exactly once')
    END;
    SELECT CASE
        WHEN (CASE NEW.dispatch_state
                WHEN 'admitted' THEN 0
                WHEN 'dispatch_may_have_escaped' THEN 1
                ELSE 2 END)
             < (CASE OLD.dispatch_state
                WHEN 'admitted' THEN 0
                WHEN 'dispatch_may_have_escaped' THEN 1
                ELSE 2 END)
        THEN RAISE(ABORT, 'inference attempt dispatch state cannot rewind')
    END;
    SELECT CASE
        WHEN OLD.dispatch_state = 'terminal'
        THEN RAISE(ABORT, 'terminal inference attempt cannot change')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_inference_items_identity_and_supersession
BEFORE UPDATE ON inference_items
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.item_id != OLD.item_id
          OR NEW.format_version != OLD.format_version
          OR NEW.conversation_turn_id != OLD.conversation_turn_id
          OR NEW.agent_turn_id != OLD.agent_turn_id
          OR NEW.sequence_no != OLD.sequence_no
          OR NEW.item_type != OLD.item_type
        THEN RAISE(ABORT, 'inference item identity and ordering are immutable')
    END;
    SELECT CASE
        WHEN OLD.superseded_at IS NOT NULL AND NEW.superseded_at IS NULL
        THEN RAISE(ABORT, 'inference item supersession cannot rewind')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_tool_executions_monotonic
BEFORE UPDATE ON tool_executions
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.row_version != OLD.row_version + 1
        THEN RAISE(ABORT, 'tool execution row_version must advance exactly once')
    END;
    SELECT CASE
        WHEN (CASE NEW.dispatch_state
                WHEN 'not_dispatched' THEN 0
                WHEN 'dispatch_may_have_escaped' THEN 1
                ELSE 2 END)
             < (CASE OLD.dispatch_state
                WHEN 'not_dispatched' THEN 0
                WHEN 'dispatch_may_have_escaped' THEN 1
                ELSE 2 END)
        THEN RAISE(ABORT, 'tool execution dispatch state cannot rewind')
    END;
    SELECT CASE
        WHEN OLD.dispatch_state = 'resolved'
        THEN RAISE(ABORT, 'resolved tool execution cannot change')
    END;
END;
