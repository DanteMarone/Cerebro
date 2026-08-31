# Harness v1 Phase 1B implementation handoff

Issue: #216 — `Implement: Harness v1 additive durable store and recovery admission`

Branch: `implement/harness-v1-phase1b-durable-store`

Status: implementation complete; final verification and push recorded below.

## Immutable inputs

- exact implementation base: `main@41100fca9a08e7c9209a4ad87d1fae8c1940beaf`
- exact clarified contract: `design/harness-v1-contract-clarifications@05fb8fa09c47598bbeed16c9be279f5dfe2a648b`
- seam inventory: `research/harness-v1-seam-inventory@3870a64baeb81e6d32b1ddd13bf0022db30961a0`
- failure audit: `research/harness-v1-failure-audit@ee7a8a37fc03d2538ee3ecc5007a48a79d8a4af4`
- merged Phase 1A implementation: `main@41100fca9a08e7c9209a4ad87d1fae8c1940beaf`

Issue #216 and the clarified contract agree. No affected implementation piece was stopped for an
ambiguity.

## Schema choices

Migration `005_harness_durable_store.sql` is additive. It introduces:

- `harness_metadata`: singleton schema epoch, storage format version and active execution epoch;
- `agent_turns`: explicit turn identity, causal wake, lifecycle, state version, active
  snapshot/attempt, finalization discriminator and attention projection plus canonical JSON;
- `turn_events`: sparse versioned transition evidence ordered uniquely within each turn;
- `step_snapshots`: immutable Phase 1B identity envelope only;
- `inference_histories`: conversation owner, history CAS version and next sequence;
- `inference_items`: conversation-owned ordered canonical items with required turn attribution,
  producing-attempt attribution and supersession metadata;
- `inference_attempts`: canonical attempt plus storage row version, dispatch barrier and semantic
  state columns;
- `tool_executions`: canonical execution plus storage row version, dispatch uncertainty,
  resolution, operation key and queryable attention fields.

Indexes introduced:

- `idx_agent_turns_recovery`
- `idx_agent_turns_attention`
- `idx_turn_events_turn_sequence`
- `idx_inference_items_conversation_order`
- `idx_inference_items_turn_order`
- `idx_inference_items_attempt`
- unique `idx_inference_attempts_turn_generation`
- `idx_tool_executions_turn_state`

Primary keys, unique causal serialized/hash columns, conversation sequence uniqueness, checks,
foreign keys and monotonic/immutable triggers provide database enforcement in addition to Python
validation.

## Serialization and storage envelopes

`AgentTurn`, `InferenceItem`, `InferenceAttempt` and `ToolExecution` use the Phase 1A Pydantic
models and versioned serializers. `dump_turn()` / `load_turn()` complete the same strict serializer
family for `AgentTurn`; nested `CausalWakeKey.key_version` is also checked. Reads reject unknown
row or payload versions and reject disagreement between query-critical SQL columns and canonical
JSON.

`StepSnapshotIdentity` is the only new storage envelope. It contains snapshot ID, format version,
turn ID, step index, creating turn version and timestamp. It accepts no provider options, tool plan,
binding, policy, workspace or environment payload. Phase 1C owns the executable immutable snapshot.

## Transactions and compare-and-set strategy

All compound writes use the existing `db.run_in_writer()` single-writer queue and its
`BEGIN IMMEDIATE` transaction. The migration reader now uses `sqlite3.complete_statement()` so
trigger bodies are not split on internal semicolons while retaining per-migration atomicity.

- `AgentTurn.state_version` advances exactly once per authoritative turn/projection transition.
- inference-attempt and tool-execution storage `row_version` values provide explicit CAS without
  changing their Phase 1A canonical DTOs.
- conversation history version advances once per appended item and once per supersession batch.
- stale expected versions raise `StaleHarnessWrite`; no stale update is treated as success.
- terminal lifecycle/attempt/tool rewinds and StepSnapshot identity mutation are rejected by SQL
  triggers as well as model/store checks.
- result projection, history advance, tool resolution and turn attention update can commit as one
  transaction; an injected item conflict proves the entire compound write rolls back.

## Causal wake uniqueness

The database uniquely stores both exact `CausalWakeKey.serialized()` text and
`CausalWakeKey.stable_hash()`. The Phase 1A encoding is deterministic canonical JSON over version,
wake kind, target agent, channel and occurrence. DM/poll occurrence uses `trigger_message_id`;
explicit/manual or message-less recurring wakes require `occurrence_id`. Duplicate admission loads
the existing turn even under concurrent single-process delivery. A distinct occurrence identity
produces a distinct key and turn. A hash/text mismatch fails as an explicit collision.

## TurnRecoveryDriver ownership and wiring

`TurnRecoveryDriver` lives in the Harness turn-coordinator layer as a standalone primitive. It
scans non-terminal turns only in `harness_metadata.active_execution_epoch`. Existing suspended work
stays unchanged. Queued/running work becomes durably `suspended` with a reason distinguishing
unresolved tool truth, possibly escaped provider dispatch, pre-dispatch reducer absence, or general
future-reducer ownership.

It is intentionally not called from `RuntimeService.start()`. Wiring it there before the durable
reducer exists would imply execution cutover or alter Phase 0 behavior. The driver accepts only a
`HarnessStore`; it has no provider adapter, tool executor or external-effect callback. Recovery in
this PR therefore produces zero provider/tool side effects and never interprets missing completion
as proof that dispatch did not occur.

## Verification

Pre-documentation implementation checkpoint:

- `flake8 .` — clean, exit 0
- `PYTHONPATH=. pytest -q` — **609 passed, 3 skipped**, exit 0

The suite includes fresh migration, migration from a genuine 001–004 database while preserving
product messages/tasks, concurrent duplicate admission, intentional recurrence, stale CAS,
terminal rewind, compound rollback, ordered close/reopen history, attempt barrier close/reopen,
durable supersession, indeterminate attention close/reopen, active-epoch recovery suspension, and
unknown canonical format rejection.

Final post-documentation verification from the repository root:

- focused migration/store/Phase 1A/Phase 0 suite — **149 passed**, exit 0;
- `flake8 .` — clean, exit 0;
- `PYTHONPATH=. pytest -q` — **610 passed, 3 skipped**, exit 0;
- `git diff --check` — clean, exit 0.

The adversarial verification pass also confirmed that `cerebro/runtime.py`,
`cerebro/service.py`, provider implementations and dependency manifests have no Phase 1B diff;
existing tests were not deleted, loosened or skipped.

## Intentionally deferred to Phase 1C and later

- executable immutable StepSnapshot contents;
- CoreTools/MCP canonical bindings and binding-generation semantics;
- finalized provider output/replay pre-tool barrier and stable executable checkpoint;
- actual Harness provider or tool dispatch and reducer/effect loop;
- raw/full tool-output storage policy and artifacts;
- production provider selection/RuntimeService cutover;
- product finalization redesign;
- native Anthropic/Gemini support, external-agent recovery, compaction, parallel tools,
  multi-worker fencing and hard budget admission.

`cerebro.runtime.AgentRuntime` remains the only active production execution path.

## Commits and final branch identity

- `26d852b6e526809e248e83405d39a806370b4705` — Add durable Harness execution store
- `92c5c9a44c963b3b5294069ea41541e7421c95ab` — Document Harness durable recovery substrate
- this handoff-finalization commit follows

A Git commit cannot contain its own SHA without changing that SHA. The exact pushed final branch
SHA is therefore reported in the issue/completion response; this handoff records the complete
incremental chain and exact final predecessor available when written.
