# Harness v1 adversarial failure audit handoff

Issue: #208 — `Review: adversarial failure-mode audit for Harness v1`

Branch: `research/harness-v1-failure-audit`

Status: active research. This branch is documentation-only; do not modify production or test code here.

## Authoritative inputs

This audit uses the exact baselines requested by issue #208:

- Codex research: `research/codex-harness-mining@3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- Goose research: `research/goose-harness-mining@ddb3ad9b5951fcbfe51420aac10df213200ccad5`
- Provider normalization: `research/provider-api-normalization@f33801a853b6e6952e07767c83947fd582a41f13`
- Architecture reconciliation tracker: issue #206
- Current Cerebro source used only for local constraints: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`
- Accepted Phase 0 characterization used for current observable behavior: `test/harness-v1-phase0-characterization@df542c53f587c8963ce84e8d83d731473ee7bd0d`

No new upstream mining is being performed. Codex/Goose findings remain conceptual inspiration only; no upstream implementation code is copied or adapted by this audit.

## Current conclusion

The proposed Harness v1 direction is viable, but the current proposal is stronger on **pre-side-effect replay correctness** than on **post-side-effect crash consistency**.

The provider-normalization work correctly requires finalized provider output, native call references, required opaque replay material, and an executable inference checkpoint to be durable before a Cerebro tool side effect begins. That closes the dangerous “late provider signature/call ID” window if implemented literally.

The unresolved failure boundary is immediately after dispatch:

```text
side effect may have happened
  > process dies or loses ownership
  > no durable terminal ToolResult exists
  > replacement worker cannot know whether repeating the call is safe
```

For arbitrary non-idempotent external effects, exactly-once execution cannot be recovered from a normal database checkpoint alone. Harness v1 therefore needs an explicit invariant for **uncertain post-dispatch outcomes**: a call whose effect may have escaped must not be automatically re-executed unless the executor supplies a stable idempotency/reconciliation guarantee.

A second Phase 1-class blocker is worker fencing. Current Cerebro leases are TTL mutex rows with `resource`, holder identity and expiry, but no fencing generation/token. An expired or partitioned old worker can therefore remain alive after a replacement acquires the same logical ownership unless Harness v1 conditions every durable transition and external dispatch on a newer execution epoch/version.

A third blocker is the dual-write boundary between durable execution state and the final shared channel message. The architecture says final chat remains completion-ordered and describes atomic completion, but it does not yet specify the database invariant that prevents either:

- visible final message committed while `AgentTurn` remains recoverable/non-terminal, causing a duplicate answer after restart; or
- `AgentTurn` committed completed while the final channel message is absent forever.

## Current-source constraints confirmed

At `main@57e9c4...`:

- `cerebro/db.py` uses SQLite WAL plus a per-process single-writer queue; explicit `run_in_writer()` transactions are available.
- `db.migrate()` applies each SQL migration under `BEGIN IMMEDIATE` and records the schema version in the same transaction.
- `cerebro/api/app.py` runs migrations at process startup before starting `RuntimeService`, but there is no worker compatibility/fencing check against other already-running processes.
- `cerebro/migrations/003_add_leases.sql` has no fencing epoch/token column.
- `cerebro/api/leases.py` and `cerebro/store.py` implement TTL lease acquire/renew/release by holder identity.
- `docs/LEASE_GUARD.md` explicitly says the Git commit guard is a workflow guard, not a security boundary.
- Phase 0 proves final agent chat rows are inserted only at completion and concurrent replies are ordered by completion time; Harness v1 must preserve that product behavior.
- Current provider concurrency semaphores and `TurnGuard` state are process-local, so they must not be treated as crash-recovery ownership mechanisms.

## Deliverables

Required files:

- `HANDOFF.md` — this resumable checkpoint
- `RISK_REGISTER.md` — full risk records and Phase 1 disposition
- `CRASH_CONSISTENCY.md` — crash windows and durable commit boundaries
- `CONCURRENCY_AND_IDEMPOTENCY.md` — worker/workspace/tool/retry races
- `REQUIRED_INVARIANTS.md` — minimum invariants issue #206 should freeze before implementation

## Work remaining

1. Finish the risk register with exact trigger sequences, incorrect states, severity, likelihood, detectability, current-design coverage, missing invariants, required tests, and Phase 1 disposition.
2. Write crash-consistency analysis around inference attempts, tool dispatch/outcome uncertainty, execution event/projection dual writes, final message commit, and migration/restart windows.
3. Write concurrency/idempotency analysis for lease expiry/split brain, stale snapshots/revocation, shared git/workspace mutation, cancellation races, semantic retries, parallel calls, and parent/child execution.
4. Reduce the findings into a compact invariant set for issue #206.
5. Update this handoff with final branch head and conclusions.

## Testing

Documentation-only branch. Per root `AGENTS.md`, lint/test runs are not required for documentation-only changes.
