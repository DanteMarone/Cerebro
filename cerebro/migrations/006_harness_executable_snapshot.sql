-- Harness v1 Phase 1C executable snapshot, replay checkpoint and raw-output artifacts.
-- Additive only. Migration 005 is merged and immutable; nothing here rewrites it.
-- Collaboration messages, product tasks, legacy tool_calls and audit_events remain untouched.

ALTER TABLE harness_metadata ADD COLUMN security_revocation_epoch INTEGER NOT NULL DEFAULT 0;

ALTER TABLE inference_histories ADD COLUMN replay_version INTEGER NOT NULL DEFAULT 0;

-- Frozen executable identity for a format_version >= 2 StepSnapshot. Every column is a
-- query-critical projection of the canonical envelope and is re-checked against it on read.
ALTER TABLE step_snapshots ADD COLUMN provider_config_id TEXT;
ALTER TABLE step_snapshots ADD COLUMN provider_id TEXT;
ALTER TABLE step_snapshots ADD COLUMN adapter_dialect TEXT;
ALTER TABLE step_snapshots ADD COLUMN adapter_dialect_version TEXT;
ALTER TABLE step_snapshots ADD COLUMN model_profile_id TEXT;
ALTER TABLE step_snapshots ADD COLUMN model_profile_version INTEGER;
ALTER TABLE step_snapshots ADD COLUMN inference_history_version INTEGER;
ALTER TABLE step_snapshots ADD COLUMN provider_replay_version INTEGER;
ALTER TABLE step_snapshots ADD COLUMN context_projection_version INTEGER;
ALTER TABLE step_snapshots ADD COLUMN token_budget INTEGER;
ALTER TABLE step_snapshots ADD COLUMN tool_plan_hash TEXT;
ALTER TABLE step_snapshots ADD COLUMN tool_plan_catalog_version INTEGER;
ALTER TABLE step_snapshots ADD COLUMN permission_policy_version INTEGER;
ALTER TABLE step_snapshots ADD COLUMN security_revocation_epoch INTEGER;
ALTER TABLE step_snapshots ADD COLUMN workspace_ref TEXT;
ALTER TABLE step_snapshots ADD COLUMN cwd TEXT;
ALTER TABLE step_snapshots ADD COLUMN environment_ref TEXT;
ALTER TABLE step_snapshots ADD COLUMN environment_version INTEGER;
ALTER TABLE step_snapshots ADD COLUMN completion_policy_version INTEGER;

-- Frozen binding evidence and durable output references for one admitted call.
ALTER TABLE tool_executions ADD COLUMN binding_executor_identity TEXT;
ALTER TABLE tool_executions ADD COLUMN recovery_effect_class TEXT;
ALTER TABLE tool_executions ADD COLUMN recovery_repeat_semantics TEXT;
ALTER TABLE tool_executions ADD COLUMN raw_output_ref TEXT;
ALTER TABLE tool_executions ADD COLUMN model_output_item_id TEXT;

-- One admitted ToolCallItem can never grow a second execution identity.
CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_executions_call_item
    ON tool_executions(tool_call_item_id);

CREATE TABLE IF NOT EXISTS harness_artifacts (
    artifact_ref TEXT PRIMARY KEY,
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    agent_turn_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    tool_key TEXT NOT NULL,
    binding_generation TEXT NOT NULL,
    content_type TEXT NOT NULL,
    storage_backend TEXT NOT NULL CHECK (storage_backend IN ('inline', 'file')),
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    content_sha256 TEXT NOT NULL,
    inline_payload TEXT,
    relative_path TEXT,
    retention_policy TEXT NOT NULL,
    provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json)),
    created_at TEXT NOT NULL,
    CHECK (
        (storage_backend = 'inline' AND inline_payload IS NOT NULL AND relative_path IS NULL)
        OR (storage_backend = 'file' AND relative_path IS NOT NULL AND inline_payload IS NULL)
    ),
    FOREIGN KEY (agent_turn_id) REFERENCES agent_turns(id) ON DELETE RESTRICT,
    FOREIGN KEY (call_id) REFERENCES tool_executions(call_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_harness_artifacts_call
    ON harness_artifacts(call_id, created_at, artifact_ref);
CREATE INDEX IF NOT EXISTS idx_harness_artifacts_turn
    ON harness_artifacts(agent_turn_id, created_at, artifact_ref);
CREATE INDEX IF NOT EXISTS idx_step_snapshots_executable
    ON step_snapshots(agent_turn_id, format_version, step_index, snapshot_id);

CREATE TRIGGER IF NOT EXISTS trg_step_snapshots_executable_identity
BEFORE INSERT ON step_snapshots
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.format_version = 2 AND (
            NEW.provider_config_id IS NULL
            OR NEW.provider_id IS NULL
            OR NEW.adapter_dialect IS NULL
            OR NEW.adapter_dialect_version IS NULL
            OR NEW.model_profile_id IS NULL
            OR NEW.model_profile_version IS NULL
            OR NEW.inference_history_version IS NULL
            OR NEW.provider_replay_version IS NULL
            OR NEW.context_projection_version IS NULL
            OR NEW.token_budget IS NULL
            OR NEW.tool_plan_hash IS NULL
            OR NEW.tool_plan_catalog_version IS NULL
            OR NEW.permission_policy_version IS NULL
            OR NEW.security_revocation_epoch IS NULL
            OR NEW.workspace_ref IS NULL
            OR NEW.cwd IS NULL
            OR NEW.environment_ref IS NULL
            OR NEW.environment_version IS NULL
            OR NEW.completion_policy_version IS NULL
        )
        THEN RAISE(ABORT, 'executable step snapshot requires complete frozen execution identity')
    END;
    SELECT CASE
        WHEN NEW.format_version = 1 AND (
            NEW.provider_config_id IS NOT NULL
            OR NEW.model_profile_id IS NOT NULL
            OR NEW.tool_plan_hash IS NOT NULL
            OR NEW.security_revocation_epoch IS NOT NULL
        )
        THEN RAISE(ABORT, 'identity-only step snapshot cannot carry executable identity')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_harness_artifacts_immutable
BEFORE UPDATE ON harness_artifacts
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'harness artifact evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_inference_histories_replay_monotonic
BEFORE UPDATE ON inference_histories
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.replay_version < OLD.replay_version
        THEN RAISE(ABORT, 'provider replay version cannot rewind')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_tool_executions_output_refs_immutable
BEFORE UPDATE ON tool_executions
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN OLD.raw_output_ref IS NOT NULL AND NEW.raw_output_ref IS NOT OLD.raw_output_ref
        THEN RAISE(ABORT, 'committed raw output reference cannot be replaced')
    END;
    SELECT CASE
        WHEN OLD.model_output_item_id IS NOT NULL
             AND NEW.model_output_item_id IS NOT OLD.model_output_item_id
        THEN RAISE(ABORT, 'canonical tool result item cannot be replaced')
    END;
    SELECT CASE
        WHEN OLD.binding_generation != NEW.binding_generation
        THEN RAISE(ABORT, 'frozen tool binding generation cannot be rebound')
    END;
    SELECT CASE
        WHEN OLD.stable_operation_key IS NOT NULL
             AND NEW.stable_operation_key IS NOT OLD.stable_operation_key
        THEN RAISE(ABORT, 'stable operation key cannot change after assignment')
    END;
END;

UPDATE harness_metadata
SET schema_epoch = 2, storage_format_version = 2, updated_at = datetime('now')
WHERE singleton = 1;
