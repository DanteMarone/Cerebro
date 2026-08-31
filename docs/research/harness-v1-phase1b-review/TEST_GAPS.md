# Phase 1B adversarial test gaps

Review target: `41100fca9a08e7c9209a4ad87d1fae8c1940beaf...abd1d702741adb795f13024ba2e9f4bf38310ecb`

The implementation handoff reports `610 passed, 3 skipped`. That is useful regression evidence, but `tests/test_harness_store.py` does not exercise several failure sequences required by issue #217.

## Required regression tests for accepted findings

### TG-01 — escaped-call causal prefix survives abandonment after reopen

**Finding:** P1B-01

Sequence:

1. admit turn/snapshot/attempt;
2. persist provider ToolCallItem C;
3. admit ToolExecution C and mark `dispatch_may_have_escaped`;
4. close/reopen database;
5. durably abandon the attempt;
6. supersede attempt output without caller-supplied `protected_call_ids`;
7. assert C and its required causal prefix remain active canonical history while later unprotected attempt output may be superseded.

Also assert supersession is rejected unless the attempt is durably abandoned.

Current `test_attempt_item_supersession_is_durable_audit_metadata` has no ToolExecution/effect boundary, so it does not cover AR-02 restart protection.

### TG-02 — recovery continues after one missing/corrupt reference

**Finding:** P1B-02

Create at least two active-epoch non-terminal turns in deterministic order. Make the first turn's active attempt reference missing/corrupt while keeping the second healthy. Run `TurnRecoveryDriver.scan()` and assert the second turn is still durably suspended. The damaged turn should receive a fail-closed disposition where its AgentTurn remains loadable.

Current recovery tests use only healthy records.

### TG-03 — recovery stale CAS does not abort unrelated turns

**Finding:** P1B-02

Inject a deterministic transition between recovery read and suspension CAS for turn A, then include turn B after it. Recovery should reload/reclassify A conservatively and still process B. Assert no provider/tool/external side-effect callback exists or runs.

### TG-04 — attempt generation is reusable on a later StepSnapshot

**Finding:** P1B-03

Within one AgentTurn:

- commit S0; admit generation 1;
- move to S1; admit generation 1 and assert success;
- attempt another generation 1 on S1 and assert uniqueness rejection.

No current test creates two snapshots/semantic steps on the same turn.

### TG-05 — terminal turns reject new snapshot/attempt/tool effect admission

**Finding:** P1B-04

Prepare a turn with an admitted attempt and admitted ToolExecution, terminalize it, then assert all of the following fail atomically:

- a new snapshot identity commit;
- a new inference-attempt admission;
- dispatch mark on the pre-existing active attempt;
- a new ToolExecution admission;
- dispatch mark on the pre-existing ToolExecution.

Assert AgentTurn/attempt/tool row versions and events do not change after each rejected operation.

### TG-06 — stale attempt/current-snapshot dispatch is rejected

**Finding:** P1B-04

Create attempt A on snapshot S0, then make S1/new attempt B current. Attempt to mark A dispatched using the current turn version. Assert rejection and no row/event changes. This tests active-attempt/snapshot fencing separately from terminal lifecycle.

### TG-07 — current step cannot rewind

**Finding:** P1B-04

Commit a step-1 snapshot, then offer a new snapshot with step index 0 at the current turn version. Assert rejection and that `current_step_index` / `active_step_snapshot_id` remain unchanged.

### TG-08 — terminal finalization fields are SQL-immutable while attention may still update

**Finding:** P1B-04

Use direct SQL to attempt a versioned rewrite of `product_outcome_kind`, `final_message_id`, or terminal failure identity on a terminal row and assert the migration trigger aborts. Separately resolve/reconcile an already-admitted uncertain tool effect after terminalization and assert the legitimate attention-only projection update succeeds without changing product outcome.

### TG-09 — cross-turn ToolCallItem cannot authorize ToolExecution

**Finding:** P1B-05

Persist ToolCallItem C for turn B. Attempt to create a ToolExecution for turn A using C's item ID/call ID/tool key. Assert `HarnessStateError`, zero ToolExecution rows for that call, and no `tool.call_admitted` event on A.

### TG-10 — filtered AgentTurn corruption fails closed

**Finding:** P1B-06

Inject disagreement between a canonical AgentTurn payload and a duplicated SQL column used by recovery/attention filtering. Call the corresponding discovery API and assert explicit corruption failure rather than an empty/incomplete result.

### TG-11 — SQL-only supersession cannot silently remove canonical history

**Finding:** P1B-06

Persist an active InferenceItem, mutate only SQL supersession columns, then call `list_inference_items(include_superseded=False)`. Assert strict failure. Do not accept silent omission.

### TG-12 — filtered ToolExecution corruption fails closed

**Finding:** P1B-06

Inject SQL/payload disagreement in dispatch/resolution fields such that the SQL WHERE clause would otherwise exclude an uncertain tool. `list_unresolved_tool_executions()` must fail closed rather than report no unresolved effect.

## Important non-finding test gaps

These do not identify a demonstrated implementation defect, but issue #217 explicitly asks for the adversarial sequences and they should be added during the repair pass.

### TG-13 — two uncertain tool calls preserve aggregate attention

On one turn admit C1/C2 and mark both `dispatch_may_have_escaped`. Assert `unresolved_effect_count == 2`. Resolve C1 known; assert count remains 1 and `needs_attention` remains true because C2 is still uncertain. Resolve C2 indeterminate; assert count remains 1 because terminal indeterminacy still contributes attention.

The implementation's aggregate COUNT query appears correct, but the current suite tests only one call at a time.

### TG-14 — terminal turn keeps unresolved multi-call attention

With two uncertain calls, terminalize/cancel/fail the turn. Resolve one known afterward and assert the other keeps the turn discoverable through `list_turns_needing_attention()`. This proves terminal lifecycle cannot hide remaining effect truth while allowing reconciliation.

### TG-15 — migration trigger enforcement, not just trigger creation

After migration 005, execute raw SQL attempts to:

- update a StepSnapshot;
- rewind attempt dispatch state;
- update a terminal attempt;
- rewind tool dispatch state;
- update a resolved tool;
- update AgentTurn without `state_version + 1`;
- change terminal AgentTurn lifecycle.

Assert SQLite aborts each write. Fresh-schema/migration tests currently prove tables/indexes exist and trigger-containing SQL parses, but not that each claimed invariant is enforced.

### TG-16 — migration splitter remains compatible with 001–004 and trigger bodies

The existing 001–004 > 005 migration test is useful indirect coverage. Add an explicit assertion that every migration-005 trigger exists and fires after migrating an old database so a future change to `_split_sql_statements()` cannot silently create only part of a trigger body.

### TG-17 — causal stable-hash collision/mismatch fails closed

Create controlled stored causal wake columns where the lookup hash matches a new wake but serialized text differs. Admission and `get_turn_for_wake()` must raise `DuplicateHarnessIdentity`. Concurrent duplicate and intentional recurrence are already covered; the collision branch is not.

### TG-18 — multi-turn conversation-owned ordering/CAS

Use two AgentTurns sharing one `ConversationTurnId`. Append items from both turns in interleaved commits and assert one deterministic global sequence, correct turn attribution, stale history CAS rejection, and correct close/reopen ordering.

### TG-19 — strict format failures across all persisted families

The current Phase 1B suite corrupts only an InferenceAttempt format version. Add AgentTurn, InferenceItem, ToolExecution, StepSnapshot identity and TurnEvent cases, especially on discovery/list paths rather than only direct `get_*` paths.

## Existing tests that materially support the review

`tests/test_harness_store.py` already provides useful evidence for:

- fresh additive schema/index creation;
- concurrent duplicate causal admission;
- distinct causal occurrence admission;
- AgentTurn stale CAS and terminal lifecycle rewind rejection;
- compound history append rollback;
- ordered conversation history close/reopen;
- provider dispatch-barrier truth close/reopen;
- basic durable attempt-item supersession metadata;
- attempt stale CAS;
- pre/post-dispatch cancellation distinction;
- one indeterminate ToolExecution + attention close/reopen;
- one known tool resolution with atomic history/attention update;
- rollback of a failed known-result compound write;
- healthy active-epoch recovery suspension;
- already-suspended recovery stability;
- one unknown attempt format failure;
- migration from 001–004 while preserving product messages/tasks/tool_calls/audit_events.

Those tests support the covered portions of the implementation but do not invalidate the gaps above.
