# Harness v1 frozen-contract gaps

Issue: #209 — `Review: adversarial audit of frozen Harness v1 architecture`

Reviewed baseline: `design/harness-v1-reconciliation@f0b792fd02b72b53375babd7c02a8b95bdeb1902`

Reviewed documents at that exact SHA:

- `docs/research/codex-harness/CEREBRO_HARNESS_V1.md` (cited below as `ARCH §n`)
- `docs/research/harness-v1/RECONCILIATION.md` (cited as `RECON §n`)
- `docs/research/harness-v1/PHASE_1_CONTRACT.md` (cited as `P1 §n`)
- `docs/research/harness-v1/HANDOFF.md` (cited as `HANDOFF §n`)

This file holds the full analysis for each accepted finding. `REVIEW.md` holds the ranked verdict;
`IMPLEMENTATION_GATES.md` maps findings to PRs.

Each accepted finding states: the exact frozen section/type/invariant, a concrete failure or
ambiguity, why the current text does not prevent it, the smallest correction, whether the
correction changes architecture or only tightens the contract, and the PR it gates.

---

## AR-01 — No component owns post-restart resumption of a durable `AgentTurn`

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `ARCH §4` component list: `TurnCoordinator` "admits/loads durable AgentTurn".
- `ARCH §21` "Recovery always resumes from the latest authoritative durable semantic boundary."
- `P1 §3` "Phase 1 does not make `ChannelPoller` delivery itself restart-durable."
- `P1 §4` `AgentTurnLifecycle = queued | running | suspended | completed | cancelled | failed`.
- `P1 §28` fixtures F-03, F-05, F-06, F-08, F-09 and F-17 all assert behavior "after restart".

**Concrete failure sequence**

1. A channel wake admits `AgentTurn` T with `lifecycle=running`, `state_version=4`.
2. An `InferenceAttempt` reaches `dispatch_may_have_escaped` (`P1 §11`), or a `ToolExecution`
   reaches `dispatch_may_have_escaped` (`P1 §16`).
3. The process dies.
4. On restart, `RuntimeService.start()` runs (current source: `cerebro/service.py:255`) and
   performs exactly one recovery action — `_sweep_orphaned_placeholders()`, which deletes empty
   legacy `messages` rows. It does not enumerate non-terminal `agent_turns`.
5. `ChannelPoller` is explicitly not restart-durable (`P1 §3`), so no wake regenerates T.
6. T stays `running` forever. Its `dispatch_may_have_escaped` records are never reconciled and
   never resolved to `indeterminate_needs_attention`.

**Why the frozen text does not prevent it**

`ARCH §21` states recovery *rules* (what may and may not be replayed) but never names the
component that *initiates* recovery, and `ARCH §4` gives `TurnCoordinator` a load-on-admission
responsibility only. `ARCH §2` and `ARCH §20` deliberately keep `RuntimeService` and
`ChannelPoller` above the harness and state that harness durability "does not automatically make
poller backoff/cursor state restart-durable". The result is a defined recovery *policy* with no
defined recovery *driver*. Six Phase 1 fixtures assume a driver exists, so the acceptance suite
cannot be written against the frozen text as it stands.

This is the most consequential gap in the review because it is the difference between "durable
state" and "recoverable state" — the stated purpose of Harness v1 (`RECON §6`: "durable enough to
know when replay is unsafe").

**Smallest required correction**

Add a `TurnCoordinator` startup/recovery responsibility to `ARCH §4` and a Phase 1 scope item to
`P1 §30` (Phase 1B or 1D):

> On process start, and before admitting new wakes for an agent, the `TurnCoordinator` scans
> `agent_turns` for non-terminal lifecycles (`queued`, `running`) belonging to the current
> `execution_epoch` and drives each through the `ARCH §21` recovery rules to a terminal,
> `suspended`, or resumed state. A non-terminal turn whose owning process is gone is never left
> unattended; where Phase 1 cannot resume it (external-agent path, `P1 §29`), it is durably moved
> to `suspended` with an explicit `suspension_reason` rather than left `running`.

**Architecture or contract?**

Adds one component responsibility and one Phase 1 scope item. It does not change any canonical
type, invariant, or frozen decision. Treat as a scope/contract correction, not a redesign.

**Gates:** PR 2 (durable store — the sweep needs the non-terminal index) and PR 4 (reducer cutover).

---

## AR-02 — An interrupted attempt's already-committed output items have no defined disposition, and `InferenceItem` carries no producing-attempt identity

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `P1 §6`, `§6.1`–`§6.5` canonical `InferenceItem` field lists. No item type carries an
  `attempt_id`; the only near-field is `Provenance(source_kind, source_id, ...)` in `P1 §5`,
  which is not required to carry attempt identity.
- `P1 §10` `OutputItemCompleted` is authoritative; `P1 §25` event `inference.output_checkpointed`.
- `P1 §17.C` "all finalized preceding `OutputItemCompleted` items are persisted in order".
- `ARCH §21` rule 1: "committed `InferenceItem`s and tool resolutions are never silently removed
  to retry an earlier semantic step"; rule 3: "a new semantic retry is a new `InferenceAttemptId`
  from the current checkpoint".
- `P1 §12` `SemanticRecoveryDisposition.fresh_attempt_from_current_checkpoint`.

**Concrete failure sequence**

1. Attempt A streams. It finalizes an assistant `MessageItem` ("Let me check the log file…") and a
   `required_for_correctness` `ProviderOpaqueItem`. Both are checkpointed into `inference_items`
   per `P1 §17.C` / `P1 §25`.
2. The connection drops before `InferenceCompleted`, or the process dies.
3. No tool was dispatched, so no external effect exists.
4. Recovery applies `fresh_attempt_from_current_checkpoint`. "Current checkpoint" now includes A's
   partial assistant turn, because `ARCH §21` rule 1 forbids removing committed items.
5. Attempt B's request therefore ends with a truncated assistant message. Against
   `/v1/chat/completions` — the Phase 1 target (`P1 §1`) — this either produces two consecutive
   assistant messages or an assistant-prefill continuation, neither of which is the intended
   semantics, and the truncated text is now permanently in canonical history.
6. If instead the implementer decides to discard A's items, they have no durable way to identify
   *which* items belonged to A: no `InferenceItem` field records the producing attempt.

**Why the frozen text does not prevent it**

`ARCH §21` rule 1's stated justification is committed *effects* (`HANDOFF` decision 21: "Recovery
never silently rewinds across committed tool effects/results"; `RECON §6`: "Never rewind committed
tool effects/history to ask the model to rediscover them"). Partial assistant output with no
dispatched effect is a materially different case, and the frozen text draws no line between
"committed because the semantic step completed" and "committed mid-attempt, then orphaned".
`P1 §11`'s fencing rule ("late events may affect current turn semantics only if their attempt is
still the active admitted attempt") governs *ingest* of late events; it says nothing about items
already committed by an attempt that later becomes non-active. F-10 tests late-event rejection,
not this case.

The missing `attempt_id` on `InferenceItem` is the harder half: even after the rule is decided, it
cannot be implemented without the field, and adding it after `inference_items` ships in PR 2 is a
schema migration plus a backfill of rows whose attribution is unrecoverable.

**Smallest required correction**

1. Add producing-attempt identity to committed items — either a required `producing_attempt_id`
   on `InferenceItem` or a mandatory `Provenance.source_kind='inference_attempt'` +
   `source_id=attempt_id` for every provider-originated item — and state it in `P1 §6`.
2. Add a rule to `ARCH §21` / `P1 §12`:

   > Monotonicity protects committed tool effects, committed tool resolutions, and completed
   > semantic steps. Output items committed by an attempt that never reached `InferenceCompleted`
   > and never authorized a dispatched side effect are attempt-scoped: on abandonment they are
   > durably marked superseded and excluded from the next request's history. They are retained as
   > audit evidence, never silently deleted.

**Architecture or contract?**

One additive field on a canonical type plus one recovery rule. No frozen decision is reversed.
Because the field lands in the PR 1 type definitions and the PR 2 schema, this must be patched into
the frozen docs **before** PR 1 code, not merely resolved during it.

**Gates:** PR 1 (canonical types), PR 2 (schema), PR 4 (recovery behavior).

---

## AR-03 — `inference_items` is turn-owned, but `ReplayRetentionScope.conversation` requires conversation-scoped required replay state

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `P1 §6`: "Each **turn** owns an append-only logical history ordered by `(sequence_no, item_id)`."
- `P1 §6.5` / `ARCH §7.1`: `ReplayRetentionScope = current_tool_cycle | current_turn |
  conversation | provider_defined`, and `required_for_correctness` items are "durable and
  non-trimmable/reorderable".
- `ARCH §19`: cross-turn history is projected by `ContextManager` from collaboration/product state
  (`StoreAdapter.history`), i.e. from `messages`.
- `P1 §28` F-01: canonical projection is built from workspace/channel `Message` history.
- `ARCH §26` PR 7 requires a materially non-OpenAI provider to pass opaque-replay fixtures through
  unchanged generic runner code.

**Concrete ambiguity and downstream failure**

A `ProviderOpaqueItem` with `replay_requirement=required_for_correctness` and
`retention_scope=conversation` has no defined home. It cannot live only in turn N's
`inference_items`, because by `P1 §6` that history is owned by turn N; and it cannot be recovered
by turn N+1's history construction, because that path is the `messages` projection (`ARCH §19`,
F-01), which by frozen decision (`RECON §8` shortcut 2) must not carry provider replay state.

The failure surfaces at PR 7, not PR 1: a provider whose continuation requires conversation-scoped
material (multi-turn signed reasoning, or provider-side handles that are correctness-bearing rather
than optimization-only) cannot be served, and the fix is to re-key `inference_items` from turn to
conversation — exactly the class of "Phase 1 decision that forces a breaking redesign later" this
review exists to catch. `RECON §3` accepts the retention-scope taxonomy wholesale, so the contract
advertises a capability its storage model cannot hold.

**Why the frozen text does not prevent it**

`P1 §24` lists `inference_items` as a Phase 1 table with no stated key, and `P1 §6` supplies the
only ownership statement — turn-owned. Nothing reconciles that with the `conversation` scope value.
`ARCH §19` says compaction is deferred but "active provider replay scopes and history versions are
represented now so future compaction cannot delete/reorder required replay state", which asserts
the scope is meaningful without giving `conversation` a storage location.

**Smallest required correction**

Choose one, in `P1 §6` and `P1 §24`:

- **(a) Preferred.** Key `inference_items` by a durable conversation/thread identity with a
  required turn-attribution column, and state that turn-scoped reads are a filter over it. This
  costs one indexed column in Phase 1 and removes the PR 7 migration.
- **(b) Acceptable.** Explicitly declare `ReplayRetentionScope.conversation` out of Phase 1 storage
  scope: adapters may not emit `required_for_correctness` + `conversation` items until a named
  later issue defines conversation-scoped replay storage, and Phase 1 adapter validation rejects
  that combination.

**Architecture or contract?**

Option (a) is a storage-key decision — contract tightening only. Option (b) is a scope restriction.
Either way no canonical type or invariant changes.

**Gates:** PR 2 (store schema). Blocking for PR 7 if unresolved.

---

## AR-04 — `indeterminate_needs_attention` has no owner and no surface; a terminal `cancelled`/`failed` turn can silently bury an escaped side effect

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `P1 §16` `ToolResolution = known(status) | indeterminate_needs_attention`; "a truthful terminal
  harness resolution when effect truth cannot be recovered".
- `P1 §18`: "otherwise resolve `indeterminate_needs_attention` … and suspend/fail according to
  policy".
- `P1 §19`: "after dispatch may have escaped, cancellation stops waiting/future autonomous work but
  does not prove failure/no-effect"; "an unresolved dispatched effect remains unknown".
- `P1 §4` `AgentTurn` fields: `suspension_reason` exists only alongside `lifecycle=suspended`;
  `cancelled` and `failed` carry no attention field.
- `ARCH §18` Phase 0 contract: "cancellation emits terminal UI/runtime cleanup and leaves no partial
  collaboration row."
- `P1 §25` durable event `tool.indeterminate` exists; `P1 §26` Hub is transient and lossy.

**Concrete failure sequence**

1. A side-effecting tool with `recovery_capability.repeat_semantics = never_automatic_repeat`
   (an outbound send, post, or commit) reaches `dispatch_may_have_escaped`.
2. The user cancels the turn. Per `P1 §19` the harness stops waiting; the effect's truth is unknown
   and must not be fabricated as failure.
3. Per `P1 §4` the turn becomes `lifecycle=cancelled`. `cancelled` is terminal and carries no
   `suspension_reason` and no attention marker.
4. Per `ARCH §18` cancellation leaves no collaboration row, so nothing is user-visible.
5. The durable `tool.indeterminate` event exists in `turn_events`, but `turn_events` is a sparse
   audit log with no defined reader, no product projection, and no operator queue.
6. Net result: the effect may have happened; the user is told nothing; no component is responsible
   for telling anyone. The state name promises attention that the design never delivers.

The same hole exists for `lifecycle=failed`: `P1 §16` permits a `ToolExecution` to remain
`dispatch_may_have_escaped` (non-terminal) while its owning turn reaches a terminal lifecycle, and
no frozen rule requires outstanding executions to be resolved before turn termination.

**Why the frozen text does not prevent it**

The contract is scrupulously correct about *not lying* — it forbids fabricating success, failure or
cancellation. It is silent about *telling*. `P1 §18`'s "suspend/fail according to policy" names a
policy that `P1 §22` (`CompletionPolicy`) does not define: `CompletionDecision` covers
`allow / continue_with_feedback / fail / suspend` for provider-completed output, not a cancellation
path that never reaches completion policy at all. F-09 asserts "uncertain external effect is never
fabricated as failure" — a negative property — and asserts nothing about visibility.

**Smallest required correction**

1. Add to `P1 §4` an `AgentTurn` field such as `unresolved_effect_count: int` (or
   `needs_attention: bool` plus reason), maintained in the same transaction as every
   `ToolExecution` transition, and state that any terminal lifecycle with a non-zero count is
   durably flagged.
2. Add to `P1 §19`: turn termination never implicitly resolves an outstanding
   `dispatch_may_have_escaped` execution; the execution stays unresolved and the turn records the
   attention marker.
3. State the Phase 1 minimum surface explicitly. Given `ARCH §18`'s zero-partial-row rule, the
   honest minimum is a durable flag plus the existing `tool.indeterminate` event plus an agent-log
   entry, with user-facing notification named as a deliberate later product decision. Making that
   choice explicit is what matters; leaving it unstated is the defect.
4. Add an F-09 arm asserting the flag is set and readable after restart.

**Architecture or contract?**

One additive `AgentTurn` field plus two rules and a fixture arm. No frozen decision is reversed, and
it does not weaken the "no generic exactly-once" position — it makes that position legible to the
operator instead of silent.

**Gates:** PR 4 (cancellation/resolution semantics), PR 5 (fixtures).

---

## AR-05 — The finalization transaction is called "idempotent" without a defined idempotency predicate, and the `AgentTurn` model supplies two predicates that disagree

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `P1 §23`: "one **idempotent** SQLite transaction commits: insert exactly one final collaboration
  `messages` row + set `product_outcome_kind` + `final_message_id` + terminal
  `lifecycle`/`state_version`/`completed_at` + record matching durable finalization event".
- `P1 §4`: "`completed` requires an explicit product outcome. For `final_message`/
  `fail_closed_error`, `final_message_id` exists. For topic PASS/silent stop, its absence is
  intentional." `ProductOutcomeKind = final_message | topic_pass | topic_silent_stop |
  fail_closed_error`. `AgentTurnLifecycle` separately includes `failed`.
- `ARCH §18`: "A valid topic silent/PASS result is a terminal `AgentTurn` product outcome whose
  `final_message_id` is intentionally absent. Recovery distinguishes that from a lost final
  message."
- `P1 §28` F-17 finalization crash matrix.

**Concrete failure sequence**

"Idempotent" only means something once a re-entry predicate is named. Two predicates are derivable
from `P1 §4`, and they disagree:

- **Predicate A — "terminal lifecycle ⇒ finalized."** Correct for `topic_pass`/`topic_silent_stop`.
  But `P1 §4` allows `lifecycle=failed` with `failure_kind` and says nothing about whether a
  `failed` turn also carries `product_outcome_kind`/`final_message_id`. `ARCH §18` requires
  provider/tool failures to keep "current fail-closed user-visible behavior" — an error row *is*
  written. So a `failed` turn can own a user-visible row with no durable link to it.
- **Predicate B — "`final_message_id` present ⇒ finalized."** Correct for `final_message` and
  `fail_closed_error`. Catastrophically wrong for `topic_pass`/`topic_silent_stop`, where absence is
  intentional — `ARCH §18` warns about exactly this confusion. A recovery pass using Predicate B
  re-runs finalization on a completed PASS turn. If the reducer re-evaluates `CompletionPolicy` on
  re-entry, the PASS turn can emit the message it was required to suppress: a direct violation of
  Phase 0 behavior 5 (`P1 §27.5`) and `RECON §8` shortcut 12.

Combined with AR-01 (no recovery driver), this is currently untestable in either direction.

**Why the frozen text does not prevent it**

`ARCH §18` identifies the hazard ("Recovery distinguishes that from a lost final message") but
states it as a requirement on recovery, not as a rule with a named discriminator. `P1 §23` asserts
idempotency as a property of the transaction without saying what re-entry checks. F-17 asserts the
outcome set — one row + terminal turn, or zero rows + PASS terminal, or one fail-closed row +
terminal turn — but never says which durable field the restart logic consults. An implementation
using Predicate B passes every crash-during-finalization arm of F-17 and still fails on a
post-finalization recovery sweep.

**Smallest required correction**

In `P1 §4` and `P1 §23`, name the discriminator and close the `failed` case:

> `product_outcome_kind` is the sole finalization discriminator. It is `NULL` until the
> finalization transaction commits and non-`NULL` after. Recovery treats a turn as finalized if and
> only if `product_outcome_kind` is non-`NULL`; `final_message_id` is never used as a finalization
> predicate. Any terminal lifecycle that publishes a user-visible collaboration row — including
> `failed` — sets `product_outcome_kind=fail_closed_error` and `final_message_id` in the same
> transaction. `lifecycle=failed` without `product_outcome_kind` is reserved for turns that
> published nothing.

**Architecture or contract?**

Contract tightening only; no new field, no new type.

Implementation note: `store.add_message` currently uses `_execute_write` (single-statement enqueue)
rather than `run_in_writer` (`cerebro/db.py:242`, which runs a callable inside one transaction), so
PR 5 must route the final insert through a writer callable to make `P1 §23` literally achievable.
That is an implementation task, not a contract defect.

**Gates:** PR 5 (finalization and recovery hardening).

---

## AR-06 — The pre-side-effect checkpoint's transaction boundary is undefined, and `stable_operation_key` is required by `ARCH §15` but absent from the `P1 §17` checkpoint set

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `ARCH §15` "The pre-side-effect executable barrier", whose required set includes "tool
  recovery/idempotency capability **and operation key when applicable**".
- `P1 §17` "Pre-side-effect checkpoint transaction", items A–L. Item J reads "ToolExecution binds
  exact ToolBinding generation/recovery capability". **No item names `stable_operation_key`.**
- `P1 §16` `ToolExecution.stable_operation_key?`.
- `P1 §15` "`stable_idempotency_key` requires reusing the same durable operation key across retry".
- `P1 §17` prose: "The **transaction** uses current SQLite writer discipline".
- `P1 §28` F-05: "Inject process failure after each of A-K in section 17."
- `P1 §28` F-07: idempotency-key retry fixture — response loss only, **no restart**.

**Two defects in one section**

**(i) Atomicity boundary.** `P1 §17` reads as a single transaction ("*the* transaction"), but item C
— "all finalized preceding `OutputItemCompleted` items are persisted in order" — necessarily
accumulates during streaming, and `P1 §25` defines a separate `inference.output_checkpointed` event
for it. So A–L is a *precondition set*, partly built earlier and partly committed at the barrier,
and the contract never says which subset must be atomic. F-05 then asks for a crash injected "after
each of A-K", which presupposes eleven durable intermediate states — the opposite reading. An
implementer optimising for F-05 literality would write eleven separate commits and destroy the
atomicity `P1 §25`'s executable-transition rule requires ("A crash cannot leave two plausible next
effects").

The safety property survives either reading — dispatch requires the whole set plus the separate
`dispatch_may_have_escaped` mark — so this is an implementation-divergence and fixture-validity
defect, not an unsafe design.

**(ii) Missing operation key.** `ARCH §15` puts the operation key inside the barrier; `P1 §17` drops
it. This is a direct contradiction between two frozen documents, on the one field that makes
`stable_idempotency_key` mean anything.

Concrete failure: a tool declares `repeat_semantics=stable_idempotency_key`. The implementation
follows `P1 §17` literally, generates the operation key at dispatch time and persists it with the
result. The process dies after dispatch. On restart, `ToolExecution` is `dispatch_may_have_escaped`
with `stable_operation_key = NULL`. The declared capability authorises a retry (`P1 §15`), but the
key that made retry safe is gone. The harness either retries with a fresh key — producing the
duplicate external mutation the whole design exists to prevent — or silently downgrades to
`indeterminate`, voiding the capability. F-07 cannot catch this because it contains no restart.

**Smallest required correction**

1. Add to `P1 §17`: `E2. stable_operation_key is assigned and persisted when the frozen binding
   declares stable_idempotency_key` — aligning `P1 §17` with `ARCH §15`.
2. Add to `P1 §17` an explicit atomicity statement, for example: "Items D, E, E2, I, J, K and L
   commit in one transaction. Items A, B, C, F, G and H may have committed in earlier transactions;
   the barrier transaction verifies their presence and fails closed if any is missing."
3. Restate F-05 as crash injection at the **defined durable boundaries** (pre-barrier, post-barrier,
   post-`dispatch_may_have_escaped`, post-executor-invoke, post-result-commit) rather than "after
   each of A-K", and assert the atomic set is all-or-nothing.
4. Add a restart arm to F-07: kill the process between the dispatch mark and the retry; assert the
   retry reuses the durably persisted key and the fake executor records exactly one mutation.

**Architecture or contract?**

Contract tightening and fixture correction. `ARCH §15` already carries the correct rule; `P1 §17`
must be brought into line with it.

**Gates:** PR 3 (snapshot + checkpoint barrier), PR 5 (crash fixtures).

---

## AR-07 — `CausalWakeKey` uniqueness can permanently wedge a wake, and no fixture covers causal admission at all

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `P1 §3`: "The serialized key or a stable hash has a **uniqueness constraint** in the Harness
  turn-admission store. A duplicate delivery returns/loads the existing `AgentTurn`; it does not
  create another execution." `occurrence_id?` is "required for intentionally recurring wakes".
- `ARCH §6`: "`causal_wake_key` makes admission idempotent."
- `HANDOFF` remaining question 4: exact encoding per current path is an open question.
- `P1 §27` Phase 0 behaviors 16 (TurnGuard ceilings/freeze) and 26 (fail-closed provider/tool
  failure).
- `P1 §28`: **no fixture** exercises causal admission. `P1 §30` Phase 1B lists "causal admission
  uniqueness" as delivered work with no acceptance coverage.

**Concrete failure sequences**

*Wedge (compounds AR-01).* A turn admitted under key K crashes mid-execution and stays `running`
(AR-01). The user retries the same trigger, or the poller re-delivers. The uniqueness constraint
matches K, "returns/loads the existing `AgentTurn`" — a permanently `running` turn — and admits no
new execution. The agent is now permanently unresponsive to that wake, with no error surfaced. A
durable uniqueness constraint without a durable recovery driver converts a transient crash into a
permanent wedge.

*Suppression.* Today a turn that fails (provider error, TurnGuard freeze) can be re-driven by a
later poll against the same latest message. Under `P1 §3`, if the poll path's key omits an
`occurrence_id`, the second wake loads the terminal failed turn and does nothing — a silent
behavior regression against Phase 0 behaviors 16 and 26. `P1 §3` requires `occurrence_id` "for
intentionally recurring wakes" but never classifies which of the current
`RuntimeService`/`ChannelPoller` paths are recurring, and `HANDOFF` question 4 leaves the encoding
open.

**Why the frozen text does not prevent it**

`P1 §3`'s rule is unconditional — duplicate key ⇒ load existing turn — with no dependence on the
loaded turn's lifecycle. The `occurrence_id` escape hatch exists but its applicability is deferred
to implementation review, so the default reading (omit it) is the dangerous one. With zero fixtures
on causal admission, neither the wedge nor the suppression is detectable by the Phase 1 acceptance
suite.

**Smallest required correction**

1. Add to `P1 §3`: "Loading an existing turn on duplicate key applies only while that turn is
   non-terminal and recoverable. A wake whose key matches a terminal turn either produces a new turn
   under a distinct `occurrence_id` or is explicitly declined with a recorded reason; it is never
   silently dropped."
2. Require `HANDOFF` question 4 to be answered *before* PR 2 rather than during it, and to state,
   per current path (immediate DM, channel poll, explicit turn), whether `occurrence_id`
   participates.
3. Add fixture **F-21 — causal admission** (see AR-09).

**Architecture or contract?**

Contract tightening plus one new fixture. No type changes.

**Gates:** PR 2 (causal admission uniqueness).

---

## AR-08 — "Exactly one execution authority per causal wake" is a rollout safety invariant but is filed as an implementation-review question, with no fixture

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen sections involved**

- `P1 §31` item 6: "whether Phase 1 reducer cutover is feature-flagged/shadowed during rollout and
  how mixed old/new single-process paths are prevented from executing the same wake" — under the
  heading "These are **implementation-review questions, not architecture ambiguity**".
- `HANDOFF` remaining question 6: "ensure old and new paths cannot both execute the same causal
  wake. A shadow must not perform external side effects."
- `ARCH §29` frozen decisions list: **contains no single-authority rule**.
- `ARCH §26` PR ordering: PR 3 delivers "provider finalized-item persistence and pre-side-effect
  checkpoint" while PR 4 delivers the "reducer/effect direct-provider cutover".

**Concrete ambiguity**

PR 3 introduces the checkpoint barrier and tool-plan projection while `AgentRuntime._generate` /
`_run_tool` still own execution. The frozen text never says whether PR 3's barrier is *inserted
into* the legacy path (one executor, safe) or runs as a *shadow alongside* it (two paths observing
one wake). Both readings are consistent with `ARCH §26`. Under the shadow reading, a side-effecting
tool can be dispatched twice for one causal wake — the exact class of duplicate external effect the
entire failure-audit line of work (`RECON §6`) exists to prevent — and the duplicate is invisible to
`CerebroCallId` monotonicity, because the two paths mint independent call identities.

**Why the frozen text does not prevent it**

The rule *is* stated once, in `HANDOFF`'s remaining-questions list — the weakest normative surface in
the frozen set, explicitly framed as "implementation choices inside the frozen architecture". `P1
§31` reinforces that framing. But "at most one component may execute effects for a given
`CausalWakeKey`" is a durable-state invariant of the same kind as `P1 §16`'s monotonicity, not a
deployment preference. No fixture in F-01…F-20 exercises a mixed old/new path, so the acceptance
suite cannot detect the most dangerous rollout failure available in Phase 1.

**Smallest required correction**

1. Promote to `ARCH §29` and `P1 §16`/`§19` as a frozen invariant:

   > For any `CausalWakeKey`, exactly one execution path may dispatch provider requests, dispatch
   > tools, or insert collaboration rows. A shadow or comparison path performs no provider dispatch,
   > no tool dispatch and no `messages` insert, and its durable writes are marked non-authoritative.
2. Remove item 6 from `P1 §31`'s "not architecture ambiguity" list.
3. Add fixture **F-22 — rollout single authority** (see AR-09).

**Architecture or contract?**

Promotion of an existing sentence to invariant status, plus one fixture. Nothing is redesigned.

**Gates:** PR 3 and PR 4 — whichever first runs harness and legacy code in one process.

---

## AR-09 — Fixture set F-01…F-20: three fixtures do not prove their stated invariant, and four invariants have no fixture

**Classification:** `MUST_CLARIFY_BEFORE_PR`

**Frozen section involved:** `P1 §28`, headed "New **deterministic** Phase 1 acceptance fixtures",
"mandatory before the direct-provider reducer path is considered complete".

**Fixtures that do not prove what they claim**

- **F-05 (replay checkpoint crash matrix).** "Inject process failure after each of A-K in section
  17" presupposes eleven durable intermediate states, contradicting `P1 §17`'s single-transaction
  framing and `P1 §25`'s atomic executable-transition rule. See AR-06(i). As written the fixture
  either cannot be built or forces a non-atomic implementation.
- **F-07 (stable idempotency key retry).** Contains no process restart: the executor "loses first
  response, then accepts retry with the same key" entirely in-process. The invariant at risk is
  durability of the key across process death (AR-06(ii)), so an implementation that never persists
  the key passes this fixture.
- **F-14 (stale tool binding generation).** "Call from old snapshot invokes G1 **if still
  addressable** or resolves stale/unavailable" is a disjunctive assertion under a heading that
  promises determinism. A test accepting either of two outcomes proves neither. The relevant MCP
  case — a reconnected server re-exposing the same tool name with no protocol-level generation
  marker — is precisely where the two branches are indistinguishable without the binding-generation
  mechanism that `HANDOFF` question 5 leaves open.

**Invariants with no fixture**

- **F-21 — causal admission (AR-07).** Same `CausalWakeKey` delivered twice ⇒ one `AgentTurn`, one
  execution. Same key delivered after the first turn reached a terminal lifecycle ⇒ a defined,
  non-silent outcome. Same key matching a non-terminal turn left by a crash ⇒ recovery, not a wedge.
- **F-22 — rollout single authority (AR-08).** With legacy and harness paths both loaded, one causal
  wake produces at most one provider dispatch, at most one tool dispatch per logical call, and
  exactly one collaboration row.
- **F-23 — orphaned in-flight attempt recovery (AR-01, AR-02).** Kill the process with an attempt at
  `dispatch_may_have_escaped` holding committed partial output items and no dispatched tool. Assert:
  the turn is driven to a defined state on restart; the next request's history contains no truncated
  assistant turn; superseded items are retained as audit evidence.
- **F-24 — indeterminate visibility (AR-04).** Cancel a turn while a `never_automatic_repeat` tool
  sits at `dispatch_may_have_escaped`. Assert: no second dispatch; the execution is not resolved to a
  false status; the terminal turn carries a durable, readable attention marker after restart.

**Smallest required correction**

Restate F-05, F-07 and F-14 as above; add F-21…F-24 to `P1 §28`; extend the PR 5 gate (`P1 §30`
Phase 1D) from "F-01 through F-20 acceptance suite green" to F-01 through F-24.

**Architecture or contract?** Fixture specification only.

**Gates:** PR 5 (acceptance suite).

---

## AR-10 — Format versioning is asymmetric: the objects most likely to be read back after a code upgrade carry no version

**Classification:** `NON_BLOCKING`

**Frozen sections involved**

- `P1 §2` required monotonic versions: `AgentTurn.state_version`, `execution_epoch`,
  `InferenceHistory.version`, `ProviderReplay.version`, `ToolCatalog.version`,
  `PermissionPolicy.version`, `SecurityRevocation.epoch`, `StepSnapshot.format_version`,
  `HarnessSchema.epoch`.
- `P1 §25`: "Events carry event-format version".
- `P1 §6.1`–`§6.5`, `§11`, `§16`: the `InferenceItem`, `InferenceAttempt` and `ToolExecution` field
  lists contain **no** format version.

**Why it matters**

`AgentTurn` and `StepSnapshot` carry `format_version`; `turn_events` carries an event-format
version. `inference_items` does not — yet it is the longest-lived serialized family, is read back to
construct every subsequent request, and (via `ProviderOpaqueItem`) holds adapter-owned payloads
whose encoding will move when PR 7 adds a second wire family. `ToolExecution` similarly holds a
serialized `recovery_capability` that `P1 §15` may extend. A suspended turn spanning a deploy is
decoded by newer code with no per-row discriminator.

`HarnessSchema.epoch` is a table-wide version and cannot distinguish rows written before and after
an in-place upgrade, so it does not close the gap.

**Smallest required correction**

Add `format_version: int` to `InferenceItem` (or to the `inference_items` row envelope),
`InferenceAttempt` and `ToolExecution` in `P1 §2`/`§6`/`§11`/`§16`.

**Architecture or contract?** Additive field on three persisted types; contract tightening.

**Gates:** PR 1 (types), PR 2 (schema). Cheap now; a migration later.

---

## AR-11 — `SemanticRecoveryDisposition.reconcile_or_suspend` has no provider-side mechanism, and `stateless_lossless_replay=false` has no defined behavior

**Classification:** `NON_BLOCKING`

**Frozen sections involved**

- `P1 §12` `SemanticRecoveryDisposition` includes `reconcile_or_suspend`.
- `P1 §9` `ProviderAdapter` = `prepare` / `stream` / `classify_error` / `close`. No reconcile
  operation. By contrast `ExternalAgentAdapter` has `reconcile_orphan(execution_id)`, and
  `ToolRecoveryCapability` has `reconciliation_binding?`.
- `P1 §8.2` `ModelProfile.stateless_lossless_replay`; `P1 §8.3` "`cache_hints` are not correctness
  state"; `P1 §28` F-12 tests only the `true` branch ("an adapter/profile advertising
  `stateless_lossless_replay=true`").

**Observations**

(i) For an inference attempt stuck at `dispatch_may_have_escaped` with unknown outcome,
`reconcile_or_suspend` can only ever mean "suspend": no adapter operation can ask a provider what
happened. For Phase 1's stateless chat-completions target this is harmless — the worst case is a
duplicate billed sample, and `P1 §26` keeps usage as telemetry. It becomes material at PR 7 for
providers whose call advances server-side conversation state.

(ii) `stateless_lossless_replay=false` has no defined consequence anywhere in the frozen set.
`P1 §8.3` asserts that cache hints are never correctness state and that required replay lives in
ordered history — which together mean replay is lossless *by construction*, leaving the `false`
value with no meaning and no rule. F-12's hedge between "adapter/profile" reflects the same
unresolved ownership: statelessness is a property of adapter + dialect + the continuation mode the
step actually used, not of the model alone, and `StepSnapshot` records no effective replay mode.

**Smallest required correction**

State in `P1 §8.2`/`§12` that Phase 1 admits only adapter/profile combinations whose required
continuation state is fully expressible as durable ordered replay items and refs; a profile
declaring `stateless_lossless_replay=false` maps continuation-state loss to `not_replay_safe` and
suspends. Note in `P1 §9` that provider-side reconciliation is deliberately absent and that
`reconcile_or_suspend` degenerates to `suspend` for provider attempts until an adapter operation is
added.

**Architecture or contract?** Contract tightening; the eventual adapter operation is a PR 7 concern.

**Gates:** PR 7 (second native provider). Worth a one-line note during PR 1.

---

## AR-12 — At-rest gates for sensitive replay material and raw tool output are not bound to the PR that first creates the data

**Classification:** `NON_BLOCKING`

**Frozen sections involved**

- `P1 §31` items 2 and 3, under "Review blockers **before Phase 1 production code merges**": at-rest
  storage/encryption/retention for sensitive `ProviderOpaqueItem` payloads "before any adapter
  actually emits them", and raw-output inline threshold/backend/retention.
- `P1 §28` F-13 (raw/model split) is Phase 1C work per `P1 §30`.
- `ARCH §24`: sensitive payloads and full tool output excluded from generic logs/Hub by default.

**Observation**

Both gates are correctly identified; only their binding is loose. Two ordering notes:

- Raw tool output becomes durable in PR 3 (F-13). That is a genuinely new at-rest data class for
  Cerebro: today tool results exist only in the in-memory transcript (verified — `cerebro/runtime.py`
  builds tool-protocol `Message` objects into a local `transcript` list and never persists them).
  Command output and file reads become durable rows or artifacts, so the retention/redaction
  decision cannot slip past PR 3.
- The sensitive-replay gate is self-triggering ("before any adapter actually emits them") and is easy
  to read as "not Phase 1". It may fire in Phase 1: LM Studio's OpenAI-compatible surface can return
  reasoning content for local reasoning models, which forces the classification decision
  (`ReasoningSummaryItem` versus `hidden_reasoning` `ProviderOpaqueItem`) inside PR 1/PR 4.

**Smallest required correction**

Bind `P1 §31` item 3 to PR 3, and item 2 to "PR 1, or the first PR whose adapter surfaces reasoning
content, whichever is earlier".

**Architecture or contract?** Gate-binding wording only.

**Gates:** PR 3 (raw output), PR 1/PR 4 (reasoning classification).

---

# False positives / already covered

These were investigated adversarially and are handled by the frozen contract. They are recorded so a
later reviewer does not re-litigate them.

| Suspected issue | Disposition | Where the frozen design covers it |
| --- | --- | --- |
| Streaming deltas could execute a tool once arguments "look complete" | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §15` ("Streaming deltas are never sufficient authority, even if arguments appear complete"), `P1 §10`, `P1 §17.C/D`, fixture F-04, `RECON §8` shortcut 7 |
| Signed/encrypted reasoning must precede the tool call on replay; ordering not modeled | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §7.1` (ordered, non-reorderable `required_for_correctness` items), `P1 §17.G` ("all preceding required `ProviderOpaqueItem`s"), F-04 (delayed signature), F-11 |
| A 429 / timeout / 5xx could authorize repeating a side-effecting call | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §11` ("A 429, timeout or transient stream failure does not authorize rewinding over committed semantic/tool effects"), `P1 §12` rule, `P1 §6.3` timeout note, `RECON §8` shortcut 8 |
| A restarted process resets per-provider semaphores and could double-admit effects | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §22` (semaphores are capacity, not ownership), F-20's explicit second clause |
| Lost or duplicated Hub events could corrupt recovery | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §20`/`§24`, `P1 §26`, F-18 |
| Migrating off `Message.meta_json` needs a backfill of existing rows | `FALSE_POSITIVE / ALREADY_COVERED` | Current tool-protocol `meta_json` is built in an in-memory transcript and never persisted (verified in `cerebro/runtime.py`); persisted `meta_json` is import/product metadata (`cerebro/transcript_import.py`), which `P1 §24` explicitly preserves |
| `tool_calls` / `audit_events` will be silently repurposed | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §17`, `P1 §24` non-reuse decisions, `RECON §8` shortcuts 4–5. Verified: no runtime SQL in `cerebro/` reads or writes either table |
| CLI/external harness semantics leak into `ProviderAdapter` | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §8.1`, `P1 §9` Phase 1 rule, `RECON §2`/`§7.5`, `RECON §8` shortcut 3 |
| OpenAI-compatible-first bakes OpenAI semantics into canonical types | `FALSE_POSITIVE / ALREADY_COVERED` (residual tracked as AR-11) | Canonical history is ordered items rather than chat messages (`ARCH §7`); `RECON §1` explicitly **rejects** a Responses-shaped generic contract; `ARCH §9` intersects dialect capability with `ModelProfile` and states an OpenAI-compatible endpoint "is a wire family, not proof of semantic capability"; `ProviderCallRef` is separated from `CerebroCallId` (`ARCH §7.2`). The only residual is `stateless_lossless_replay` ownership |
| Deferring compaction risks losing required replay state | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §19`, `P1 §21`, `RECON §3` (replay scopes pinned now, compaction later). AR-03 constrains where the `conversation` scope lives |
| Deferring multi-worker fencing is unsafe | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §22`, `P1 §2` (epoch present from the first schema), `P1 §29` explicit non-claims, `RECON §6` (TTL leases rejected as fencing). Phase 1 is single-process |
| Deferring subagents forces a later identity break | `FALSE_POSITIVE / ALREADY_COVERED` | `root_agent_turn_id`/`parent_agent_turn_id` reserved in `P1 §4`; `RECON §2`/`§9` gate |
| Deferring workspace concurrency is unsafe | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §12` ("Mutable workspace contents are not made immutable merely by snapshotting a path"), `RECON §6`, sequential execution preserved (F-16) |
| Snapshot immutability could force execution under a revoked grant | `FALSE_POSITIVE / ALREADY_COVERED` | `ARCH §12` plus `RECON §7.2` (security revocation epoch checked at dispatch), F-15 |
| Deferring external-harness recovery is unsafe | `PARTIALLY COVERED` — see AR-01 | `P1 §9`/`§29` correctly decline the reconnect claim and current CLI behavior is unchanged, so there is no regression. The residual risk is a durable `AgentTurn` left `running` after a CLI-path crash, which AR-01 and AR-07 cover |
