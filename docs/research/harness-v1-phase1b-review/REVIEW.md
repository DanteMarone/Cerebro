# Harness v1 Phase 1B independent review

Issue: #217 — `Review: adversarial audit of Harness v1 Phase 1B durable store`

Review branch: `review/harness-v1-phase1b`

Exact implementation reviewed: `implement/harness-v1-phase1b-durable-store@abd1d702741adb795f13024ba2e9f4bf38310ecb`

Exact base: `main@41100fca9a08e7c9209a4ad87d1fae8c1940beaf`

Authoritative contract inputs:

- clarified contract: `design/harness-v1-contract-clarifications@05fb8fa09c47598bbeed16c9be279f5dfe2a648b`
- failure audit: `research/harness-v1-failure-audit@ee7a8a37fc03d2538ee3ecc5007a48a79d8a4af4`
- seam inventory: `research/harness-v1-seam-inventory@3870a64baeb81e6d32b1ddd13bf0022db30961a0`
- merged Phase 1A/base: `main@41100fca9a08e7c9209a4ad87d1fae8c1940beaf`

## Verdict

**MERGEABLE AFTER FIXES**

The Phase 1B direction is sound and the transaction/CAS substrate is mostly strong, but six storage/recovery correctness defects need repair before merge. None requires a Harness redesign or Phase 1C/1D implementation.

Accepted findings:

| ID | Classification | Summary |
| --- | --- | --- |
| P1B-01 | MUST_FIX | Abandoned-attempt supersession can cross a durably possibly-escaped tool effect because durable `ToolExecution` protection is not derived by the store. |
| P1B-02 | MUST_FIX | One malformed/missing referenced record or stale recovery write can abort the entire recovery scan and leave later turns falsely running/queued. |
| P1B-03 | MUST_FIX | `(agent_turn_id, attempt_generation)` uniqueness makes generation turn-global and blocks a normal later step from starting again at generation 1. |
| P1B-04 | MUST_FIX | Snapshot/attempt/tool admission and dispatch lack terminal/current-projection gates, allowing post-terminal effects and step projection rewind through normal store APIs. |
| P1B-05 | MUST_FIX | `create_tool_execution()` can bind an execution for turn A to a `ToolCallItem` owned by turn B. |
| P1B-06 | MUST_FIX | Several restart/history queries filter on duplicated SQL columns before canonical payload validation, so divergence can silently hide durable truth instead of failing closed. |

Full failure sequences and minimum repairs are in `FINDINGS.md`. Missing deterministic coverage is in `TEST_GAPS.md`.

## Review method

This was a source-level, read-only review of exactly `41100fca...abd1d702`. I read root `AGENTS.md`, issue #217, the authoritative clarification/failure-audit/seam inputs, the full Phase 1B delta, and the Phase 1B store test module.

I did **not** rerun the implementation suite. This review branch changes documentation only, and root `AGENTS.md` permits skipping lint/tests for documentation-only changes. The implementation handoff's reported `610 passed, 3 skipped` and clean lint are treated as evidence; the tests themselves were inspected for whether the required adversarial sequences are present.

## Risk-area disposition

### 1. Migration 005 and DB enforcement

**Partially covered; P1B-03/P1B-04/P1B-06 require fixes.**

The migration is additive and does not repurpose product `messages`, `tasks`, legacy `tool_calls`, or `audit_events`. Migration statement splitting now uses `sqlite3.complete_statement()`, which is appropriate for preserving trigger bodies, and the migration test exercises 001–004 > 005 while preserving product data.

The schema's monotonic triggers are useful, but the turn-global attempt-generation unique index encodes an unjustified future execution assumption. Terminal `agent_turns` also protect lifecycle but not finalization columns at the SQL boundary. Query-critical duplicated columns are not always validated before they are used to exclude rows from recovery/history queries.

### 2. CAS / transaction correctness

**FALSE_POSITIVE / COVERED.**

Compound semantic writes consistently use `db.run_in_writer()` / `BEGIN IMMEDIATE`. AgentTurn, attempt, tool and history CAS checks are explicit. Failed compound tool-result persistence rolls back result/history/tool/attention state together. Sparse events are appended inside the same writer transaction as the projection they describe, so an exception rolls back both.

History version semantics are coherent: append batches advance once per appended item; supersession advances once per supersession batch.

### 3. Causal admission

**FALSE_POSITIVE / COVERED, with test gaps.**

The database uniquely constrains both exact serialized wake identity and its stable hash. Admission looks up by hash, verifies serialized equality, fails closed on mismatch, and lets SQLite remain authoritative for concurrent duplicate insertion. The canonical wake encoding distinguishes repeated occurrences.

The suite covers concurrent duplicate admission and distinct occurrence IDs. It does not directly exercise the deliberate hash-collision/mismatch branch.

### 4. AgentTurn lifecycle / projections

**P1B-04 MUST_FIX.**

Lifecycle rewind itself is blocked in Python and SQL. Post-terminal attention updates are structurally possible because the SQL trigger permits a same-lifecycle version increment, which is necessary for unresolved-effect truth. The problem is that the store applies the same permissiveness to new snapshot/attempt/tool effect admission and dispatch, and snapshot commit can lower `current_step_index`.

### 5. InferenceAttempt persistence

**Barrier/CAS covered; P1B-03/P1B-04 require fixes.**

Attempts are durably inserted as `admitted` before the dispatch barrier, row-version CAS is explicit, and pre/post-barrier truth round-trips correctly. Canonical validation and SQL trigger ordering agree for dispatch-state monotonicity.

The generation uniqueness scope and active/terminal admission gates are not safe as shipped.

### 6. Conversation-owned inference history

**Ordering/atomicity covered; P1B-01/P1B-06 require fixes.**

Conversation ownership, deterministic sequence assignment, append CAS and batch supersession are present. Provider-originated producing-attempt attribution is checked against the owning turn on append.

However, once a possibly escaped call exists without a committed ToolResult, `supersede_attempt_items()` depends on the caller to pass its call ID instead of deriving protection from the new durable ToolExecution table. That makes AR-02 unsafe after restart. The normal canonical-history read can also hide an SQL/payload supersession mismatch before validation.

### 7. ToolExecution / attention atomicity

**Core algorithm FALSE_POSITIVE / COVERED; P1B-04/P1B-05 require fixes.**

Tool dispatch/resolution is monotonic. Known result append + history advance + tool resolution + turn attention update is one transaction. Attention is recomputed with a query over *all* uncertain calls on the turn, including terminal indeterminate resolutions, so resolving one call does not logically clear a different uncertain call.

The implementation lacks deterministic multi-call and post-terminal attention tests, and admission/dispatch ownership/lifecycle gates need repair.

### 8. StepSnapshot Phase 1B seam

**FALSE_POSITIVE / COVERED except the projection gate in P1B-04.**

`StepSnapshotIdentity` is genuinely minimal: snapshot ID, format version, AgentTurn ID, step index, creating turn version and timestamp. No provider options, tool plan, binding, policy, workspace, environment or executable checkpoint semantics leaked into Phase 1B. SQL makes the stored identity immutable.

### 9. TurnRecoveryDriver

**P1B-02 MUST_FIX.**

The driver uses only the active execution epoch, has no provider/tool/external executor dependency, and only writes suspension control state. It never normalizes tool/provider uncertainty backward.

It is not failure-isolated: one malformed/missing referenced attempt/tool record or stale transition can terminate `scan()` before later turns receive a durable safe disposition.

### 10. Strict reload / corruption behavior

**Unknown versions covered; P1B-06 MUST_FIX.**

Canonical loaders fail closed on unknown persisted format versions and several duplicated SQL columns are cross-checked with canonical JSON. The remaining issue is query ordering: some SQL projections are used to filter rows *before* canonical comparison, which can turn corruption into silent omission.

### 11. Scope

**FALSE_POSITIVE / COVERED.**

The delta does not cut over ProviderAdapter selection, `RuntimeService`, `AgentRuntime`, tool execution, native providers, product finalization, external-agent recovery, raw-output policy, parallel execution, compaction, or multi-worker fencing. `cerebro.runtime.AgentRuntime` remains the live path.

## Merge disposition

No `BLOCKER` was found. All six accepted findings are bounded repairs in the Phase 1B schema/store/recovery layer and should be fixed, regression-tested, and independently repair-reviewed before merge.
