# Phase 1B review findings

Review target: `41100fca9a08e7c9209a4ad87d1fae8c1940beaf...abd1d702741adb795f13024ba2e9f4bf38310ecb`

Classification is restricted to issue #217's vocabulary.

## P1B-01 — MUST_FIX — supersession is not anchored to durable escaped-effect truth

**Exact file / symbol**

- `cerebro/harness/store.py::HarnessStore.supersede_attempt_items`
- `cerebro/harness/history.py::InferenceHistory.supersede_abandoned_attempt`
- durable source that is currently not consulted: `tool_executions`

**Concrete failure sequence**

1. Attempt A produces finalized `ToolCallItem` C and C is appended to canonical history.
2. A `ToolExecution` for C is admitted and durably advanced to `dispatch_may_have_escaped`.
3. The process dies before a known `ToolResultItem` is committed.
4. After reopen, A is abandoned.
5. The caller invokes `supersede_attempt_items(..., protected_call_ids=())`, which is the API default.
6. The store reconstructs `InferenceHistory` and lets `supersede_abandoned_attempt()` derive protection only from committed ToolResultItems plus caller-supplied call IDs.
7. Because C has no result and the caller did not reconstruct/pass C, the provider output through C can be marked superseded even though durable `tool_executions` still says C may already have mutated the outside world.
8. Canonical request history can therefore omit the causal prefix for an effect that may have escaped while the ToolExecution/attention tables truthfully retain that effect.

The store also does not require the loaded attempt to have `semantic_state == "abandoned"` before applying this operation, so the persistence boundary itself does not enforce that supersession is an abandonment transition.

**Violated contract / invariant**

- Clarified AR-02: abandoned incomplete-attempt output may leave request history only when it did not authorize a dispatched effect; committed/possibly escaped effect history remains monotonic.
- `PHASE_1_CONTRACT.md` section 20: provider/model switch requires old active attempt to be durably abandoned before building fresh portable history.
- Failure-audit I-06: durable semantic progress is monotonic across recovery.
- Phase 1A repair explicitly states that caller protection is necessary for unresolved possibly-escaped calls. Phase 1B now owns the durable table from which that protection must be reconstructed after restart.

**Smallest fix**

Inside the same writer transaction used by `supersede_attempt_items()`:

1. require the target `InferenceAttempt` to be durably `abandoned`;
2. derive protected call IDs from durable `ToolExecution` rows associated with ToolCallItems produced by that attempt whenever the call may have escaped and lacks a canonical causal result that already protects it;
3. union that durable set with any caller-provided extra protection; callers may add protection but may not subtract persisted protection;
4. apply supersession only after that set is known in the same transaction.

Do not move executor/reconciliation behavior into Phase 1B.

**Deterministic regression test**

Persist attempt A > ToolCall C > ToolExecution C > `dispatch_may_have_escaped`; close/reopen; abandon A; call `supersede_attempt_items()` without `protected_call_ids`; assert the canonical prefix through C remains active while trailing unprotected attempt output may be superseded. Separately assert superseding an active/non-abandoned attempt is rejected atomically.

**Merge disposition**

Must be fixed before merge. The current API can make restart history contradict durable escaped-effect truth.

---

## P1B-02 — MUST_FIX — one bad recovery candidate aborts the whole startup scan

**Exact file / symbol**

- `cerebro/harness/recovery.py::TurnRecoveryDriver.scan`
- `cerebro/harness/store.py::HarnessStore.list_non_terminal_turns`
- `cerebro/harness/store.py::HarnessStore.get_inference_attempt`
- `cerebro/harness/store.py::HarnessStore.list_unresolved_tool_executions`
- `cerebro/harness/store.py::HarnessStore.transition_turn`

**Concrete failure sequence**

1. Active epoch contains turn A and later turn B, both durably non-terminal.
2. A has a malformed/missing `active_inference_attempt_id`, a corrupt referenced ToolExecution, or races another authoritative transition so the recovery suspension CAS becomes stale.
3. `scan()` reaches A first.
4. `get_inference_attempt()`, strict ToolExecution reload, or `transition_turn()` raises `HarnessRecordNotFound`, `HarnessStateError`, `UnsupportedFormatVersion`, or `StaleHarnessWrite`.
5. There is no per-turn isolation/reclassification path, so the exception exits `scan()`.
6. B is never classified and remains durably `running`/`queued` after this startup recovery pass.

A malformed AgentTurn row can fail even earlier while `list_non_terminal_turns()` materializes the candidate list.

**Violated contract / invariant**

- Issue #216 frozen storage decision 8: startup scans active-epoch non-terminal turns and work that cannot safely resume becomes durably suspended rather than left running or guessed forward.
- Clarified AR-01: unsafe/unrecoverable active-epoch turns become durably suspended with a reason.
- Issue #217 explicitly requires assessment of whether one malformed/missing referenced record can abort the entire scan and leave other turns falsely running.

**Smallest fix**

Make recovery failure-isolated per durable turn:

- enumerate candidate identities in a way that lets one malformed row be isolated rather than aborting decoding of every candidate;
- for a valid AgentTurn whose referenced attempt/tool record is missing or corrupt, durably suspend that turn with a fail-closed corruption/missing-reference reason when possible, then continue;
- on `StaleHarnessWrite`, reload/reclassify that turn. If it is now terminal/suspended, accept the newer truth; otherwise make a conservative retry/disposition. Do not let the race abort unrelated turns;
- collect/return decisions only from durable outcomes actually committed.

No provider/tool side effect is needed.

**Deterministic regression test**

Create ordered active turns A and B. Corrupt/delete A's active referenced attempt in a controlled fixture while keeping A loadable. Run recovery and assert B is still durably suspended. Add a deterministic stale-CAS injection for A and assert B still receives a safe disposition. Also exercise a malformed candidate row so later candidates are not skipped.

**Merge disposition**

Must be fixed before merge. A restart primitive that stops at the first damaged turn cannot establish conservative startup truth for the rest of the active epoch.

---

## P1B-03 — MUST_FIX — attempt-generation uniqueness is scoped to the whole turn

**Exact file / symbol**

- `cerebro/migrations/005_harness_durable_store.sql::idx_inference_attempts_turn_generation`
- `cerebro/harness/store.py::HarnessStore.admit_inference_attempt`
- canonical field: `cerebro/harness/attempts.py::InferenceAttempt.attempt_generation`

**Concrete failure sequence**

1. Turn T commits step snapshot S0.
2. Its first inference attempt A0 uses the canonical default `attempt_generation=1` and is persisted.
3. T advances to a later semantic step and commits distinct snapshot S1.
4. The first provider attempt for S1, A1, also starts at generation 1.
5. The unique index on `(agent_turn_id, attempt_generation)` rejects A1 because T already used generation 1 on S0.

Nothing in the clarified Phase 1 contract defines `attempt_generation` as a turn-global ordinal. The canonical attempt identity is explicitly bound to a StepSnapshot, and the Pydantic type only requires generation to start at 1. The database therefore freezes a Phase 1C execution assumption that is stronger than the contract and incompatible with the obvious multi-step interpretation.

**Violated contract / invariant**

- Issue #217 requires assessing whether `(agent_turn_id, attempt_generation)` is the correct scope for future multi-step turns and forbids constraints that accidentally encode a Phase 1C assumption.
- `PHASE_1_CONTRACT.md` section 11 binds each InferenceAttempt to one StepSnapshot and does not define turn-global generation semantics.

**Smallest fix**

Do not ship turn-global generation uniqueness. The conservative storage fix is to scope generation to the immutable step identity, e.g. unique `(step_snapshot_id, attempt_generation)`, so generation can mean retry/attempt generation within one semantic step without redefining later steps. If generation semantics are intentionally meant to be turn-global, that must first be made an explicit canonical contract; Phase 1B should not infer it in SQL.

**Deterministic regression test**

Within one AgentTurn, commit S0 and admit generation 1; advance to S1 and admit generation 1 successfully. Then attempt a second generation 1 for the same S1 and assert the database/store rejects it.

**Merge disposition**

Must be fixed before merge because migration 005 would otherwise encode a future execution constraint that blocks legitimate multi-step persistence.

---

## P1B-04 — MUST_FIX — effect/projection admission is allowed after terminalization and step state can rewind

**Exact file / symbol**

- `cerebro/harness/store.py::HarnessStore.commit_snapshot_identity`
- `cerebro/harness/store.py::HarnessStore.admit_inference_attempt`
- `cerebro/harness/store.py::HarnessStore._transition_attempt`
- `cerebro/harness/store.py::HarnessStore.create_tool_execution`
- `cerebro/harness/store.py::HarnessStore._transition_tool`
- `cerebro/migrations/005_harness_durable_store.sql::trg_agent_turns_version_and_lifecycle`

**Concrete failure sequence A — provider dispatch after terminal turn**

1. Running turn T has an active admitted attempt A.
2. T is transitioned to `completed`, `cancelled`, or `failed` with a new state version.
3. The caller invokes `mark_attempt_dispatch_may_have_escaped(A, expected_turn_version=<terminal version>)`.
4. `_transition_attempt()` checks only row/turn CAS. It does not require a non-terminal lifecycle, active attempt identity, or active snapshot identity.
5. The attempt advances to the dispatch barrier and T's state version advances while its lifecycle stays terminal.
6. A future effect executor using this primitive would now have durable authorization to send a provider request after the turn was terminal. Recovery does not scan terminal turns.

**Concrete failure sequence B — tool dispatch after terminal turn**

1. A ToolExecution C is admitted while T is running.
2. T becomes terminal before C's dispatch mark.
3. `mark_tool_dispatch_may_have_escaped(C, expected_turn_version=<terminal version>)` succeeds and records new unresolved effect truth after terminal control state.

**Concrete failure sequence C — step projection rewind**

1. T has already committed a snapshot for step 1, so `current_step_index == 1`.
2. A caller constructs a fresh snapshot identity with `step_index == 0` and the current turn version.
3. `commit_snapshot_identity()` accepts it and writes `current_step_index=0` / a new active snapshot, rewinding the durable current-step projection through a normal store API.

The SQL terminal trigger also protects only lifecycle. A direct writer can advance `state_version` while rewriting terminal `product_outcome_kind`/`final_message_id`/`failure_kind` consistently in columns/payload, and the trigger accepts it. Post-terminal attention updates need to remain possible, but finalization identity does not need to remain mutable.

**Violated contract / invariant**

- Failure-audit I-06: durable semantic progress is monotonic across recovery.
- Failure-audit I-13 / `PHASE_1_CONTRACT.md` section 19: after terminal cancellation/control state, no new provider attempt or tool dispatch may be admitted; late evidence cannot restart autonomous work.
- Issue #217: active snapshot/attempt references must not create misleading restart truth; terminal attention updates must remain possible without rewriting product finalization truth.

**Smallest fix**

At the store boundary:

- reject snapshot commit, attempt admission, ToolExecution admission, and provider/tool dispatch marks when the owning turn is terminal;
- before provider dispatch transition, require the attempt to equal `turn.active_inference_attempt_id` and its snapshot to equal `turn.active_step_snapshot_id`;
- reject snapshot `step_index < turn.current_step_index` (leave richer Phase 1C step semantics deferred);
- harden the SQL terminal trigger so terminal product-finalization discriminator/message/failure columns cannot change while still permitting versioned attention/unresolved-effect projection updates and timestamps.

Do not add reducer/tool-plan logic.

**Deterministic regression test**

Terminalize a turn with an admitted attempt and an admitted ToolExecution. Assert attempt dispatch mark, tool dispatch mark, new snapshot commit, and new attempt/tool admission all fail atomically with versions/rows unchanged. Separately commit step 1 then attempt step 0 and assert rejection. Add a raw SQL trigger test proving terminal product finalization fields cannot be rewritten while a legitimate post-terminal attention-only update remains allowed.

**Merge disposition**

Must be fixed before merge. These persistence primitives are explicitly the later reducer/effect safety boundary and currently permit effects after terminal control state.

---

## P1B-05 — MUST_FIX — ToolExecution can bind to another turn's ToolCallItem

**Exact file / symbol**

- `cerebro/harness/store.py::HarnessStore.create_tool_execution`

**Concrete failure sequence**

1. Turn A has active snapshot SA.
2. Turn B has a durable `ToolCallItem` CB with call ID X and tool key K.
3. Construct `ToolExecution` E naming `agent_turn_id=A`, `step_snapshot_id=SA`, `tool_call_item_id=CB.item_id`, call ID X and tool key K.
4. `create_tool_execution()` verifies SA belongs to A and verifies CB is a ToolCallItem whose call ID/key match E.
5. It never verifies `CB.agent_turn_id == A`.
6. E is inserted successfully, so A's durable effect record is causally attributed to provider output owned by B.
7. A later result transition can append a ToolResult into A's conversation/history even though its authorizing ToolCall lives in B's history.

The SQL foreign keys independently prove that the turn, snapshot and item exist but do not enforce that those identities belong to one causal chain.

**Violated contract / invariant**

- Issue #217 conversation-history attribution requirement.
- `PHASE_1_CONTRACT.md` pre-side-effect checkpoint: the durable ToolCallItem, CerebroCallId, ToolExecution and AgentTurn checkpoint are one causal admission set.
- Failure-audit I-11: effect admission must be bound to the exact durable turn/version that authorized it.

**Smallest fix**

In the existing `create_tool_execution()` transaction, require the decoded ToolCallItem's `agent_turn_id` to equal the owning AgentTurn ID before insertion. Keep richer active-snapshot/tool-plan executability rules in Phase 1C unless separately required by P1B-04.

**Deterministic regression test**

Create turns A/B; persist a ToolCallItem only for B; try to admit a ToolExecution for A using B's item. Assert `HarnessStateError`, no `tool_executions` row, and no `tool.call_admitted` event.

**Merge disposition**

Must be fixed before merge. The current store permits cross-turn causal attribution at the exact row that will authorize tool execution later.

---

## P1B-06 — MUST_FIX — SQL filters can hide canonical-column divergence before strict reload

**Exact file / symbol**

- `cerebro/harness/store.py::HarnessStore.list_non_terminal_turns`
- `cerebro/harness/store.py::HarnessStore.list_turns_needing_attention`
- `cerebro/harness/store.py::HarnessStore.list_unresolved_tool_executions`
- `cerebro/harness/store.py::HarnessStore.list_inference_items`
- `cerebro/harness/store.py::_item_from_row`

**Concrete failure sequence A — recovery truth hidden**

1. Canonical AgentTurn payload says T is `running` in the active execution epoch.
2. A buggy/mixed-version/direct writer changes only duplicated SQL lifecycle/epoch columns so the row no longer matches the `list_non_terminal_turns()` WHERE clause while leaving canonical JSON unchanged.
3. The list query excludes T before `_turn_from_row()` gets a chance to compare columns with canonical JSON.
4. Recovery silently sees no T instead of failing closed on the disagreement.

**Concrete failure sequence B — history rewind hidden**

1. Canonical InferenceItem I has no supersession metadata.
2. SQL `superseded_at` is changed without the canonical payload being changed; the current SQL trigger permits the NULL > non-NULL direction.
3. `list_inference_items(include_superseded=False)` filters I out before `_item_from_row()` runs.
4. `_item_from_row()` also does not compare SQL supersession columns to canonical supersession fields.
5. The next request can silently receive a history with I missing instead of surfacing corruption.

The same shape exists for attention/unresolved ToolExecution discovery: raw query columns decide whether a row is selected before canonical validation can detect disagreement.

**Violated contract / invariant**

- Issue #217 strict reload/corruption requirement: query-critical duplicated SQL columns must agree with canonical JSON and divergence that can mislead restart/recovery must be detected.
- Failure-audit I-06: durable semantic progress cannot silently disappear on recovery.
- Implementation handoff claim that reads reject disagreement between query-critical SQL columns and canonical JSON.

**Smallest fix**

For recovery/history/attention discovery, do not use unvalidated duplicated semantic columns to exclude rows before canonical validation. At Phase 1 scale the conservative approach is:

- query a broader immutable identity/owner scope;
- strict-decode and compare every filter-critical duplicated column;
- apply semantic filtering from the validated canonical object afterward.

Add missing item checks for `superseded_at`, `superseded_reason`, and `superseding_attempt_id`. Apply the same principle to lifecycle/epoch and tool attention filters. A SQL trigger/check approach is also valid if it guarantees payload/column agreement at write time, but it must cover every filter-critical field.

**Deterministic regression test**

Inject SQL/payload disagreement for an otherwise valid AgentTurn lifecycle/attention field and assert recovery/attention discovery raises fail-closed rather than returning an incomplete set. Inject SQL-only `superseded_at` on an active history item and assert canonical history read raises instead of omitting the item. Add the analogous ToolExecution dispatch/resolution mismatch case.

**Merge disposition**

Must be fixed before merge. The current strict loaders are bypassed in exactly the cases where corrupted query columns can hide the row from restart logic.

---

## FALSE_POSITIVE / COVERED checks

### P1B-C01 — transaction/CAS rollback

**FALSE_POSITIVE / COVERED.** Compound semantic mutations use `db.run_in_writer()`; stale turn/attempt/tool/history versions fail explicitly; rollback covers event/projection and result/history/tool/attention writes together.

### P1B-C02 — multi-call attention algorithm

**FALSE_POSITIVE / COVERED in implementation, test gap remains.** `_transition_tool()` recomputes unresolved count across every ToolExecution for the turn where dispatch may have escaped or resolution is indeterminate. Resolving one call cannot mathematically clear a second uncertain call. Add deterministic coverage in `TEST_GAPS.md`.

### P1B-C03 — terminal attention projection

**FALSE_POSITIVE / COVERED in the core update path, test gap remains.** The AgentTurn SQL trigger permits a version increment that keeps the same terminal lifecycle, and `_transition_tool()` carries existing finalization fields through unchanged while recomputing attention. This supports post-terminal effect reconciliation. P1B-04 is specifically about preventing *new effect admission/dispatch* and finalization rewrite, not forbidding legitimate attention updates.

### P1B-C04 — causal admission authority

**FALSE_POSITIVE / COVERED.** Serialized wake and stable hash are both unique in SQLite; hash lookup verifies serialized equality and fails closed on mismatch; explicit occurrence identity permits intentional recurrence.

### P1B-C05 — StepSnapshot storage seam

**FALSE_POSITIVE / COVERED.** The Phase 1B envelope is minimal and immutable and contains no executable tool plan, binding, provider configuration, policy, workspace or environment state.

### P1B-C06 — additive/scope discipline

**FALSE_POSITIVE / COVERED.** Migration 005 is additive. No ProviderAdapter selection, RuntimeService/AgentRuntime cutover, native-provider rollout, tool execution, raw-output policy, finalization redesign, multi-worker fencing, or external-agent recovery is introduced by the reviewed delta.
