-- 003_add_leases.sql: Distributed mutex leases (§8.7)

CREATE TABLE IF NOT EXISTS leases (
    resource TEXT PRIMARY KEY,
    holder_id TEXT NOT NULL,
    holder_kind TEXT NOT NULL DEFAULT 'agent',
    channel_id TEXT,
    reason TEXT NOT NULL DEFAULT '',
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leases_expires_at ON leases (expires_at);
