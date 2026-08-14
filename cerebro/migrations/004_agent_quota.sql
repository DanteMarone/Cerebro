-- Self-reported harness quota for CLI-backed agents.
--
-- Cerebro can measure tokens for the providers it calls itself (LM Studio, Gemini) because it sees
-- the Usage deltas. It cannot see how much of a five-hour window Claude has left, or how much of a
-- weekly budget Codex has left: those live inside another vendor's harness and are not exposed to
-- us. The honest model is therefore self-report -- the agent tells Cerebro, and Cerebro records
-- WHO said it and WHEN, so a stale number can be shown as stale instead of passing for a
-- measurement.
--
-- reported_at is what makes this table trustworthy. A quota figure with no age attached is worse
-- than no figure, because it looks like fact.

-- reported_by is separate from agent_id because both are real cases: an agent reports its own
-- window, and Dante relays a number he read off a harness UI on behalf of an agent that cannot see
-- it. Recording only the subject would let the second case masquerade as the first. Attribution is
-- assigned by the server from the authenticated principal and never taken from the request body,
-- which is §6.2 applied to a number rather than a sentence.

CREATE TABLE IF NOT EXISTS agent_quota (
    agent_id      TEXT NOT NULL,
    window_name   TEXT NOT NULL,          -- '5h', 'weekly', or whatever the harness meters
    pct_remaining REAL,                   -- 0..100, NULL when the agent only knows it is limited
    resets_at     TEXT,                   -- ISO8601, NULL when unknown
    note          TEXT,
    reported_at   TEXT NOT NULL,
    reported_by   TEXT NOT NULL,          -- the principal that made the claim
    PRIMARY KEY (agent_id, window_name)
);

CREATE INDEX IF NOT EXISTS idx_agent_quota_reported_at ON agent_quota(reported_at);
