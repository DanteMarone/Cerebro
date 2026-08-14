-- Cerebro v2 Database Schema (§4)

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT,
    description TEXT,
    workspace_path TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    display_name TEXT,
    avatar TEXT,
    role TEXT,
    provider TEXT,
    model TEXT,
    params_json TEXT,
    api_key_ref TEXT,
    home_path TEXT,
    enabled INTEGER,
    delegation_enabled INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_teams (
    agent_id TEXT,
    team_id TEXT,
    PRIMARY KEY(agent_id, team_id)
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    team_id TEXT,
    kind TEXT,
    name TEXT,
    topic TEXT,
    created_by TEXT,
    created_at TEXT,
    archived_at TEXT,
    summary TEXT,
    summary_upto_msg INTEGER
);

CREATE TABLE IF NOT EXISTS channel_members (
    channel_id TEXT,
    member_id TEXT,
    member_kind TEXT,
    listen_mode TEXT DEFAULT 'active',
    joined_at TEXT,
    last_read_message_id INTEGER DEFAULT 0,
    PRIMARY KEY(channel_id, member_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT,
    author_id TEXT,
    author_kind TEXT,
    kind TEXT,
    body TEXT,
    quote_msg_id INTEGER,
    turn_id TEXT,
    depth INTEGER DEFAULT 0,
    created_at TEXT,
    meta_json TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    message_id INTEGER,
    agent_id TEXT,
    server TEXT,
    tool TEXT,
    args_json TEXT,
    result_json TEXT,
    status TEXT,
    error TEXT,
    started_at TEXT,
    ended_at TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT,
    body TEXT,
    owner_agent_id TEXT,
    channel_id TEXT,
    team_id TEXT,
    status TEXT,
    artifacts_json TEXT,
    created_at TEXT,
    updated_at TEXT,
    due_at TEXT
);

CREATE TABLE IF NOT EXISTS cron_jobs (
    id TEXT PRIMARY KEY,
    agent_id TEXT,
    cron_expr TEXT,
    timezone TEXT,
    target_channel_id TEXT,
    prompt TEXT,
    enabled INTEGER,
    last_run_at TEXT,
    next_run_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    actor_id TEXT,
    actor_kind TEXT,
    action TEXT,
    target TEXT,
    detail_json TEXT,
    revert_ref TEXT,
    reverted_at TEXT
);

CREATE TABLE IF NOT EXISTS budget_usage (
    scope TEXT,
    scope_id TEXT,
    period TEXT,
    window_start TEXT,
    calls INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    usd REAL,
    delegations INTEGER,
    PRIMARY KEY(scope, scope_id, period, window_start)
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_id_id ON messages(channel_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_turn_id ON messages(turn_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_ts ON audit_events(ts);
CREATE INDEX IF NOT EXISTS idx_tasks_owner_status ON tasks(owner_agent_id, status);
CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run ON cron_jobs(next_run_at);
