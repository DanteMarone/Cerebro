# Harness v1 Phase 1B repair-delta review

Issue: #218 — `Review: verify Phase 1B repair delta before merge`

Review branch: `review/harness-v1-phase1b-repair`

Exact repair delta reviewed:
`abd1d702741adb795f13024ba2e9f4bf38310ecb...178968213d0cf255c2e6fd91330717a340c4e0f9`

Independent review requiring repair:
`review/harness-v1-phase1b@2592b32d62c03d28edfc49f666ecfa967a919d0e`

## Verdict

**MERGEABLE**

No remaining `MUST_FIX` or `FOLLOW_UP` finding was identified in the repair delta. P1B-01 through P1B-06 are `FALSE_POSITIVE / COVERED` for this repair review.

This review did not re-review the original Phase 1B implementation. It checked only whether the accepted Phase 1B findings were repaired without regressions or Phase 1C scope creep.

## Required finding matrix

### P1B-01 — FALSE_POSITIVE / COVERED

`HarnessStore.supersede_attempt_items()` now enforces the repair at the persistence boundary:

- the target attempt is strict-loaded inside the writer transaction and must already be durably `abandoned`;
- the same transaction strict-loads canonical history plus durable `ToolExecution` rows;
- possibly escaped calls produced by the abandoned attempt are derived from persisted `ToolExecution.may_have_escaped` truth;
- caller-supplied `protected_call_ids` are unioned with the durable set, so caller protection can only add protection;
- AR-02 supersession is applied only after that durable protection set is known.

TG-01 exercises the required close/reopen sequence: provider output contains a causal prefix, ToolCall and trailing item; the ToolExecution is marked `dispatch_may_have_escaped`; pre-abandonment supersession is rejected with unchanged history/events; after reopen and durable abandonment, supersession without caller protection removes only the trailing unprotected output and preserves the prefix through the escaped ToolCall.

No path in the reviewed delta can silently supersede a newly evaluated call whose durable ToolExecution says the effect may have escaped.

### P1B-02 — FALSE_POSITIVE / COVERED

`TurnRecoveryDriver.scan()` now enumerates raw `agent_turns.id` values through `list_recovery_candidate_ids()` without lifecycle/epoch semantic filtering, then strict-loads each AgentTurn independently.

For a loadable AgentTurn whose active attempt or tool references are missing/corrupt, `_recover_turn()` converts the load failure into a conservative corruption reason and durably suspends that turn. TG-02 corrupts a referenced attempt while keeping the AgentTurn loadable and proves the turn is suspended with the corruption reason.

A malformed AgentTurn row that cannot strict-decode is isolated at the per-candidate `get_turn()` boundary. It is not reported as successfully recovered and is not guessed forward or rewritten through an unsafe partially decoded object; later candidate identities are still processed. TG-02 places such a malformed row before a later healthy candidate and proves the later turn is still suspended.

A stale recovery suspension CAS is reloaded and reclassified. TG-03 deterministically injects a competing suspension, proves the newer suspended truth is accepted as `already_suspended`, and proves the following candidate is still processed. Terminal truth is also accepted by `_recover_turn()` rather than overwritten.

The recovery driver accepts only `HarnessStore`; there is no provider adapter, executor or external-effect callback in this path.

### P1B-03 — FALSE_POSITIVE / COVERED

Migration 005 now creates unique index `idx_inference_attempts_snapshot_generation` on:

`(step_snapshot_id, attempt_generation)`

The old turn-global generation index is removed from the migration definition.

TG-04 proves both required sides of the constraint: generation 1 succeeds on snapshot S0 and is reused successfully on later snapshot S1 in the same AgentTurn, while a second generation 1 on S1 fails the database unique constraint.

### P1B-04 — FALSE_POSITIVE / COVERED

The repaired store gates every required new effect/admission path on non-terminal ownership:

- `commit_snapshot_identity()` rejects a terminal turn and rejects `step_index` rewind;
- `admit_inference_attempt()` rejects a terminal turn and requires the active snapshot;
- `create_tool_execution()` rejects a terminal turn;
- provider dispatch marking rejects a terminal turn and additionally requires both the active attempt and active StepSnapshot;
- tool dispatch marking rejects a terminal turn.

The dispatch gates are intentionally narrower than all attempt/tool transitions. Resolution/reconciliation of an already admitted uncertain ToolExecution is therefore still allowed after terminalization. TG-08 and TG-14 prove that this legitimate post-terminal reconciliation updates attention without authorizing new dispatch.

`trg_agent_turns_version_and_lifecycle` now freezes terminal product/failure finalization identity in both duplicated columns and canonical JSON while still allowing versioned attention projection changes. TG-08 performs a raw SQL terminal-finalization rewrite and gets an SQLite abort, then successfully resolves an already uncertain effect after terminalization with product finalization unchanged.

TG-05 proves new snapshot, attempt, ToolExecution, provider-dispatch and tool-dispatch operations all fail after terminalization with baseline turn/attempt/tool/event state preserved. TG-06 separately proves stale attempt/current-snapshot provider dispatch is rejected without row/event mutation. TG-07 proves current step projection cannot rewind.

### P1B-05 — FALSE_POSITIVE / COVERED

`create_tool_execution()` strict-loads the authorizing InferenceItem and checks `item.agent_turn_id == execution.agent_turn_id` before inserting any ToolExecution row or appending `tool.call_admitted`.

That ownership check occurs before the first mutation in the transaction. A mismatch therefore cannot create a ToolExecution row, advance any version, or append an event.

TG-09 uses a ToolCallItem persisted only for turn B to attempt ToolExecution admission for turn A. It receives `HarnessStateError`, leaves no ToolExecution row, and leaves turn A's event stream unchanged.

### P1B-06 — FALSE_POSITIVE / COVERED

The repaired discovery/list paths no longer apply filter-critical semantic SQL predicates before canonical validation:

- `list_non_terminal_turns()` loads all AgentTurn rows, strict-decodes and checks duplicated columns, then filters epoch/lifecycle in Python;
- recovery candidate enumeration selects only raw IDs and strict-loads candidates individually;
- `list_turns_needing_attention()` strict-decodes all AgentTurns before attention filtering;
- `list_inference_items()` selects conversation ownership/order only, strict-validates supersession columns against canonical payload, then applies supersession/turn filters;
- `list_unresolved_tool_executions()` selects only by owning AgentTurn, strict-validates dispatch/resolution duplicated fields, then applies unresolved-effect semantics.

TG-10 proves lifecycle and attention SQL/canonical divergence is surfaced rather than hidden. TG-11 proves SQL-only supersession cannot remove an item from canonical history before validation. TG-12 proves SQL dispatch/resolution divergence cannot hide an uncertain ToolExecution.

## TG-01 through TG-19 adversarial test inspection

All nineteen requested test gaps are present as concrete state-transition or raw-SQL adversarial tests rather than name-only/helper-only assertions:

- TG-01: close/reopen escaped-call supersession, including rejection before durable abandonment.
- TG-02: loadable missing reference plus a strict-undecodable AgentTurn before a later healthy candidate; later recovery continues.
- TG-03: deterministic stale-CAS injection with acceptance of newer suspended truth and continued processing.
- TG-04: snapshot-scoped generation reuse and same-snapshot duplicate rejection.
- TG-05: terminal snapshot/attempt/tool admission and provider/tool dispatch rejection with rollback evidence.
- TG-06: provider dispatch fencing to the current attempt/snapshot.
- TG-07: step-index rewind rejection.
- TG-08: raw SQL terminal-finalization trigger abort plus legitimate post-terminal uncertain-effect resolution.
- TG-09: cross-turn ToolCallItem authorization rejection before durable admission.
- TG-10: AgentTurn lifecycle/attention duplicated-column corruption cannot be filtered away.
- TG-11: SQL-only InferenceItem supersession cannot hide canonical history.
- TG-12: ToolExecution dispatch/resolution corruption cannot be filtered away.
- TG-13: two uncertain calls preserve aggregate attention when one becomes known and the other becomes indeterminate.
- TG-14: terminal multi-call reconciliation leaves the remaining uncertain call discoverable.
- TG-15: every migration-005 monotonic/immutability trigger is exercised with raw SQL writes.
- TG-16: a real 001-004 database is upgraded to 005 before trigger execution tests; migration splitting is also checked for complete trigger bodies.
- TG-17: causal hash/text mismatch raises `DuplicateHarnessIdentity` on admission and lookup.
- TG-18: two AgentTurns share one conversation history, interleave globally, reject stale history CAS, and preserve order/attribution across reopen.
- TG-19: unknown durable format versions fail closed on AgentTurn, InferenceAttempt, InferenceItem, ToolExecution, StepSnapshot and TurnEvent read/discovery paths.

## Regression and scope review

The exact repair delta contains eight modified files:

- `README.md`
- `cerebro/harness/recovery.py`
- `cerebro/harness/store.py`
- `cerebro/migrations/005_harness_durable_store.sql`
- `docs/harness_v1_contracts.md`
- `docs/research/harness-v1/PHASE_1B_IMPLEMENTATION_HANDOFF.md`
- `docs/user_guide.md`
- `tests/test_harness_store.py`

No `RuntimeService`, `AgentRuntime`, provider implementation, tool executor, dependency manifest, product-finalization cutover, external-agent recovery, or multi-worker fencing code changed in the reviewed delta. The StepSnapshot remains an identity-only Phase 1B storage seam; there is no executable Phase 1C snapshot/tool plan, reducer/effect loop, native-provider work, provider selection, or raw-output policy implementation.

The implementation handoff records verification at repair code/test head `5ee6d3c9c23d311552ceda48dc840c4e645351ee`:

- focused migration/store suite: `41 passed`;
- full suite: `630 passed, 3 skipped`;
- `flake8 .`: clean;
- `git diff --check`: clean.

Those results were treated as supporting evidence, not proof. This review independently inspected the repaired source, migration and TG-01 through TG-19 definitions. The suite was not independently executed in this review environment. The review deliverable itself is documentation-only, so root `AGENTS.md` permits skipping lint/tests for this commit.

## Final classification

- `MUST_FIX`: none.
- `FOLLOW_UP`: none.
- `FALSE_POSITIVE / COVERED`: P1B-01, P1B-02, P1B-03, P1B-04, P1B-05, P1B-06.

Final verdict: **MERGEABLE**.
