# Harness v1 adversarial failure audit handoff

Issue: #208 — `Review: adversarial failure-mode audit for Harness v1`

Branch: `research/harness-v1-failure-audit`

Status: **complete**. Documentation-only research; no production or test code was modified.

## Authoritative inputs

This audit used the exact baselines requested by issue #208:

- Codex research: `research/codex-harness-mining@3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- Goose research: `research/goose-harness-mining@ddb3ad9b5951fcbfe51420aac10df213200ccad5`
- Provider normalization: `research/provider-api-normalization@f33801a853b6e6952e07767c83947fd582a41f13`
- Architecture reconciliation tracker: issue #206
- Current Cerebro source used only for local constraints: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`
- Accepted Phase 0 characterization: `test/harness-v1-phase0-characterization@df542c53f587c8963ce84e8d83d731473ee7bd0d`

No new upstream mining was performed. Codex/Goose findings remain conceptual inspiration only; no upstream implementation code was copied or adapted.

## Deliverables

Completed:

- `RISK_REGISTER.md` — 22 full risk records with exact trigger sequence, incorrect state, severity, likelihood, detectability, current-design coverage, missing invariant, deterministic test, and Phase 1 disposition.
- `CRASH_CONSISTENCY.md` — durable crash-boundary model from wake admission through provider attempts, client-tool dispatch, terminal results and final product publication.
- `CONCURRENCY_AND_IDEMPOTENCY.md` — worker fencing, reducer races, stale attempts/snapshots, shared git/workspace mutation, cancellation, semantic retry, duplicate wakes, child execution and external-harness orphan behavior.
- `REQUIRED_INVARIANTS.md` — 26 minimum invariants for issue #206, with phase gates and required tests.
- `HANDOFF.md` — this resumable completion checkpoint.

Incremental research commits before this handoff completion update:

- `f654d1e8a81f6bed5df183cca5cd0121b5b628e2` — start audit handoff
- `a18733c9a0678b9db689ae2ae599eb61368f6a79` — full risk register
- `5e09f8faedf6bdc4bc102fb52809e6f9e2b145d3` — crash-consistency analysis
- `2b9085d8377cc600368c1b1605226468eba10bac` — concurrency/idempotency analysis
- `6e4eb8b675e7eea105c97c55c1fa106093401cc7` — required invariant set

## Main conclusion

The proposed Harness v1 direction is viable and the provider-normalization work already closes an important class of failures: finalized provider output, native call references and required opaque replay material must be durable before a client tool side effect becomes executable. The proposal also already says restart recovery should stop rather than guess when a side-effecting operation is indeterminate. Preserve both decisions.

The main unresolved problem is making that indeterminate state reconstructable and representable after dispatch:

```text
side effect may have happened
  > process dies / cancellation races / ownership changes
  > no durable terminal ToolResult exists
  > replacement worker cannot infer whether repeating the call is safe
```

For arbitrary non-idempotent external effects, generic exactly-once execution is impossible across this ambiguity window without executor-provided idempotency or reconciliation. The harness must therefore distinguish “not dispatched,” “may have executed/outcome unknown,” and “terminal result durable,” and must not blindly re-run the middle state.

## Phase 1 contract blockers

Issue #206 should not freeze Phase 1 canonical contracts without representing these facts:

1. **Stable inference-attempt identity before provider dispatch.** A missing local completion is not proof the provider never received the request.
2. **Replay safety separate from retryability.** `transient`/429/stream failure does not automatically authorize repeating semantic work.
3. **Completed ordered output plus provider replay/native call references.** `OutputItemCompleted` remains authoritative; deltas never execute tools.
4. **Post-dispatch uncertainty in the tool execution model.** Current candidate terminal statuses alone cannot truthfully encode a remote effect that may have committed before cancellation/crash/timeout.
5. **Executor recovery semantics.** Automatic repeat dispatch requires an explicit read-only/idempotent/idempotency-key/reconciliation guarantee.
6. **Monotonic terminal outcome/cancellation semantics.** Cancellation stops future work but cannot rewrite an already-completed or indeterminate side effect as “did not happen.”
7. **Provider/model continuation compatibility and abandonment.** Active opaque replay state cannot be translated across incompatible provider/model boundaries; late superseded-attempt events cannot become current.
8. **Version identities that allow later worker/attempt fencing.** Phase 1 types should not make stale-owner rejection impossible.

These are type/contract concerns even when the full durable execution/recovery implementation lands in later phases.

## Later-phase blockers that can wait only while the feature stays constrained

- `agent_turns`/`turn_events` executable transitions must be atomic/versioned before durable reducer recovery owns side effects.
- Worker ownership must be fenced before multi-worker/takeover recovery; current TTL leases have no fencing generation.
- Final shared `messages` publication and terminal `AgentTurn` state need one idempotent durable finalization before durable turn completion ships.
- Shared workspace/git mutation needs isolation or version/resource conflict enforcement before concurrent Harness-owned writers are enabled.
- Keep multiple tool calls sequential until resource-aware parallel safety exists.
- Child/delegated execution needs idempotent child admission and explicit descendant terminal policy before background delegation ships.
- External CLI/coding harnesses need crash/orphan/reconnect semantics before they participate in durable re-entry guarantees.
- Mixed-version workers must be drained/fenced before the first Harness schema migration that changes executable event/state semantics.
- Provider semaphores can remain process-local only if they are explicitly capacity controls rather than correctness/budget ownership.
- Usage persistence can remain best effort only while it is telemetry; hard budget/authorization facts need durable admission semantics.

## Current-source constraints confirmed

At `main@57e9c4...`:

- `cerebro/db.py` uses SQLite WAL plus a per-process single-writer queue and exposes explicit transactional `run_in_writer()` support.
- `db.migrate()` applies each SQL migration under `BEGIN IMMEDIATE` and records the schema version in the same transaction, so per-file migration crash atomicity is already good.
- `cerebro/api/app.py` migrates before starting its local `RuntimeService`, but it has no execution gate that fences another already-running old process after a semantic migration.
- `cerebro/migrations/003_add_leases.sql` stores holder/expiry but no monotonic fencing generation/token.
- `cerebro/api/leases.py` / `cerebro/store.py` provide useful TTL mutex coordination, not stale-owner fencing.
- `docs/LEASE_GUARD.md` explicitly documents the git commit guard as a workflow guard, not a security boundary.
- Phase 0 proves final agent chat rows are created only at completion and concurrent final replies are ordered by completion time. Harness v1 finalization must preserve that behavior while adding durable `AgentTurn` state.
- Current provider concurrency semaphores and TurnGuard state are process-local and cannot be treated as crash-recovery ownership.

## Highest-value adversarial tests

If #206 needs a short acceptance subset, start with:

1. kill after remote tool side effect but before ToolResult persistence; restart must not duplicate it;
2. stale worker resumes after lease expiry/takeover; every authoritative write/dispatch is fenced;
3. cancellation races remote success before/after result persistence; durable outcome remains truthful and no later work starts after terminal cancellation;
4. late native call ID/signature arrives after complete-looking tool arguments; tool cannot execute before replay checkpoint;
5. durable tool success followed by retryable provider error; recovery cannot rewind and rediscover/re-execute the tool;
6. compaction plan races extension of required replay scope; stale compaction cannot commit;
7. provider/model switch with active continuation plus late old-provider completion; no opaque-state leakage and no stale tool execution;
8. two agents mutate the same git worktree from one base; no mixed/unowned commit or stale verification success;
9. parent dies after child creation; recovery discovers exactly one child rather than starting another;
10. kill at every final message/AgentTurn finalization statement; after restart exactly one correct product outcome exists;
11. migrate while an old fixture worker remains alive; old worker cannot mutate incompatible executable state;
12. duplicate causal wake delivered concurrently/after restart; exactly one durable turn is admitted.

## Testing performed

No lint/test suite was run because this branch modifies documentation only. Root `AGENTS.md` explicitly permits skipping lint/tests for documentation-only changes.

## Resume point

No audit work remains on issue #208 unless #206 asks for a targeted follow-up or the seam inventory in #207 reveals a current-Cerebro constraint that materially changes one of these findings.

For reconciliation, consume this branch by exact final branch head, not by chat history or an unpinned branch tip.
