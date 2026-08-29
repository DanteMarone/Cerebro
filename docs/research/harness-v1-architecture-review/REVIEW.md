# Harness v1 architecture review — verdict and ranked findings

Issue: #209 — `Review: adversarial audit of frozen Harness v1 architecture`

Review branch: `review/harness-v1-architecture-audit`

Frozen baseline reviewed: `design/harness-v1-reconciliation@f0b792fd02b72b53375babd7c02a8b95bdeb1902`

Date: 2026-08-29

Companion documents: [`CONTRACT_GAPS.md`](CONTRACT_GAPS.md) (full per-finding analysis),
[`IMPLEMENTATION_GATES.md`](IMPLEMENTATION_GATES.md) (finding → PR mapping),
[`HANDOFF.md`](HANDOFF.md) (reviewed SHA, branch head, recommendation).

Citation shorthand used throughout: `ARCH` = `docs/research/codex-harness/CEREBRO_HARNESS_V1.md`,
`P1` = `docs/research/harness-v1/PHASE_1_CONTRACT.md`,
`RECON` = `docs/research/harness-v1/RECONCILIATION.md`,
`HANDOFF` = `docs/research/harness-v1/HANDOFF.md`, all at the frozen SHA.

---

## Verdict

**PROCEED WITH CONTRACT CLARIFICATIONS.**

No frozen architectural decision is wrong. The failure-audit line of reasoning is the strongest part
of the design: the separation of provider retryability from semantic replay safety, the
`dispatch_may_have_escaped` conservatism, the refusal to promise generic exactly-once external
effects, and the pre-side-effect executable barrier are all correct and mutually consistent. Nothing
in this review asks to reopen them, and nothing here weakens the rule that once a side effect may
have escaped, repetition requires executor proof of read-only behavior, idempotency, externally
enforced stable idempotency, or authoritative reconciliation.

What the review found is a design that is durable but not yet **recoverable**, in a specific and
fixable sense. The contract defines recovery *rules* thoroughly and never names a recovery *driver*
(AR-01). Around that centre sit a cluster of gaps that share one root cause: the frozen text is
precise about which durable facts must exist, and comparatively quiet about **who reads them back,
under what predicate, and what they are then obliged to do**.

Nine findings must be resolved in the frozen documents before or with the PR each one gates. Three
are useful later improvements. Fifteen further concerns were investigated and are already covered by
the frozen contract; they are recorded in `CONTRACT_GAPS.md` so they are not re-litigated.

Estimated cost of every correction combined: two additive fields on canonical types, one additive
field on `AgentTurn`, one storage-key decision, six rule clarifications, three fixture restatements
and four new fixtures. No component is redesigned. PR 1 can open as soon as the AR-02 and AR-10 type
corrections are patched into `P1 §6`.

---

## Ranked findings

| # | ID | Finding | Class | Gates |
| --- | --- | --- | --- | --- |
| 1 | AR-01 | No component owns post-restart resumption of a durable `AgentTurn`; six fixtures assume a driver that the architecture never names | `MUST_CLARIFY_BEFORE_PR` | PR 2, PR 4 |
| 2 | AR-02 | An interrupted attempt's committed output items have no defined disposition, and `InferenceItem` carries no producing-attempt identity to express one | `MUST_CLARIFY_BEFORE_PR` | PR 1, PR 2, PR 4 |
| 3 | AR-03 | `inference_items` is turn-owned but `ReplayRetentionScope.conversation` requires conversation-scoped replay state — no defined home; forces a re-key at PR 7 | `MUST_CLARIFY_BEFORE_PR` | PR 2 |
| 4 | AR-04 | `indeterminate_needs_attention` has no owner and no surface; a terminal `cancelled`/`failed` turn can silently bury an escaped side effect | `MUST_CLARIFY_BEFORE_PR` | PR 4, PR 5 |
| 5 | AR-05 | Finalization is called "idempotent" with no defined predicate; the two derivable predicates disagree, and one of them can make a PASS turn emit a message | `MUST_CLARIFY_BEFORE_PR` | PR 5 |
| 6 | AR-06 | Checkpoint atomicity boundary undefined; `stable_operation_key` is required by `ARCH §15` and missing from `P1 §17`, and F-07 has no restart to catch it | `MUST_CLARIFY_BEFORE_PR` | PR 3, PR 5 |
| 7 | AR-07 | `CausalWakeKey` uniqueness can permanently wedge a wake after a crash, and can silently suppress legitimate re-wakes; zero fixture coverage | `MUST_CLARIFY_BEFORE_PR` | PR 2 |
| 8 | AR-08 | "Exactly one execution authority per causal wake" is a safety invariant filed as an implementation-review question, with no fixture | `MUST_CLARIFY_BEFORE_PR` | PR 3, PR 4 |
| 9 | AR-09 | F-05, F-07 and F-14 do not prove their invariants; four invariants have no fixture (F-21…F-24 proposed) | `MUST_CLARIFY_BEFORE_PR` | PR 5 |
| 10 | AR-10 | Format versioning is asymmetric — `inference_items`, `inference_attempts` and `tool_executions` carry no format version | `NON_BLOCKING` | PR 1, PR 2 |
| 11 | AR-11 | `reconcile_or_suspend` has no provider-side mechanism; `stateless_lossless_replay=false` has no defined behavior | `NON_BLOCKING` | PR 7 |
| 12 | AR-12 | At-rest gates for sensitive replay material and raw tool output are not bound to the PR that first creates the data | `NON_BLOCKING` | PR 3 |

---

## The five that matter most

### 1. AR-01 — durable, but not recoverable

`ARCH §21` gives eight precise recovery rules. `ARCH §4` gives `TurnCoordinator` a
load-on-admission responsibility. Neither names what happens at process start. `ChannelPoller` is
explicitly not restart-durable (`P1 §3`), and current `RuntimeService.start()`
(`cerebro/service.py:255`) does exactly one recovery action today: it deletes empty legacy `messages`
rows.

So after a crash, a turn sitting at `dispatch_may_have_escaped` is never re-examined. It stays
`running` forever, its uncertain external effect never reconciled and never resolved to
`indeterminate_needs_attention`. Meanwhile F-03, F-05, F-06, F-08, F-09 and F-17 all assert
post-restart behavior — six mandatory fixtures written against a driver the architecture does not
have.

The correction is one paragraph: give `TurnCoordinator` a startup scan over non-terminal
`agent_turns` for the current `execution_epoch`, and require that a turn Phase 1 cannot resume goes
durably to `suspended` with a reason rather than being left `running`.

### 2. AR-02 — the partial assistant turn nobody may delete

`P1 §17.C` and `P1 §25` commit finalized `OutputItemCompleted` items as they arrive. `ARCH §21`
rule 1 forbids removing committed items. Put those together and an attempt that dies mid-stream —
after finalizing an assistant text item, before any tool dispatch — leaves a truncated assistant
turn permanently in canonical history. The next attempt's request ends with it, which against
`/v1/chat/completions` is an assistant-prefill continuation nobody asked for.

Rule 1's stated justification is committed *effects*. Partial output with no dispatched effect is a
different case, and the frozen text never separates them. Worse, an implementer who wants to
separate them cannot: no `InferenceItem` type carries the producing `attempt_id`, so there is no
durable way to identify which items belonged to the dead attempt.

This is the one finding that must land in the frozen docs **before PR 1 code**, because it is an
additive field on a canonical type and a column in the PR 2 schema. Retrofitting it after
`inference_items` ships means a migration plus a backfill of rows whose attribution is gone.

### 3. AR-03 — a retention scope with nowhere to live

`P1 §6` says each **turn** owns its inference history. `P1 §6.5` offers
`ReplayRetentionScope.conversation` for required replay material. Cross-turn history is built from
the `messages` projection (`ARCH §19`, F-01), which by frozen decision must not carry provider
replay state (`RECON §8` shortcut 2).

So a `required_for_correctness` + `conversation` item has no home. Phase 1's stateless
chat-completions target never produces one, which is exactly why this will not be noticed until
PR 7 — the PR whose entire purpose is to prove the abstraction on a materially different wire
family. The fix then is to re-key `inference_items` from turn to conversation: a schema break in the
central table, caused by a Phase 1 decision. The fix now is one indexed column, or an explicit
statement that the `conversation` scope is out of Phase 1 storage scope.

### 4. AR-04 — truthful, and silent

The contract is scrupulous about not lying. It forbids fabricating success, failure or cancellation
for an effect that may have escaped, and it names the honest state
`indeterminate_needs_attention`. It never says whose attention, or how they get it.

Cancel a turn while a `never_automatic_repeat` tool sits at `dispatch_may_have_escaped`. Per
`P1 §19` the harness stops waiting and must not fabricate a failure. Per `P1 §4` the turn becomes
`cancelled` — terminal, with no `suspension_reason` field and no attention marker. Per `ARCH §18`
cancellation leaves no collaboration row. The `tool.indeterminate` event lands in `turn_events`, a
sparse audit log with no defined reader.

The outbound action may have happened. Nobody is told, and no component is responsible for telling
them. The correction is an `AgentTurn` attention marker written in the same transaction as the
execution transition, a rule that turn termination never implicitly resolves an outstanding
execution, and an explicit statement of the Phase 1 minimum surface.

### 5. AR-05 — "idempotent" without a predicate

`P1 §23` commits the final `messages` row and the terminal turn in one idempotent transaction. The
word is doing load-bearing work with nothing behind it: the contract never says what a re-entering
recovery pass checks.

`P1 §4` supplies two candidate predicates and they disagree. "Terminal lifecycle ⇒ finalized" breaks
on `lifecycle=failed`, which `ARCH §18` requires to publish a user-visible error row but which
`P1 §4` never obliges to record `product_outcome_kind` or `final_message_id`. "`final_message_id`
present ⇒ finalized" breaks on `topic_pass` and `topic_silent_stop`, where absence is intentional —
`ARCH §18` warns about precisely this confusion. A recovery pass using the second predicate re-runs
finalization on a completed PASS turn, and if the reducer re-evaluates `CompletionPolicy` on
re-entry, the PASS turn emits the message it was required to suppress. That is a direct Phase 0
regression (`P1 §27.5`) and a violation of `RECON §8` shortcut 12.

F-17 cannot catch it: the fixture asserts the outcome set but never names the field restart logic
consults, so an implementation using the wrong predicate passes every arm.

The correction is one sentence naming `product_outcome_kind` as the sole discriminator, plus closing
the `failed` case.

---

## What the review deliberately did not do

- No alternative architecture is proposed. Every accepted finding takes the frozen model as given
  and asks only whether it is complete enough to implement unambiguously.
- No Codex, Goose or provider archaeology was repeated. Four source checks were run against current
  `main` to verify specific frozen claims: startup recovery behavior (`cerebro/service.py:255`),
  `run_in_writer` transaction semantics (`cerebro/db.py:242`), whether tool-protocol `meta_json` is
  persisted (`cerebro/runtime.py`), and whether any runtime SQL touches `tool_calls`/`audit_events`
  (none does). Each verification is cited at the finding that depends on it.
- No Phase 1 scope was expanded for theoretical completeness. AR-01 adds a startup scan because six
  mandatory fixtures already presuppose it, not because recovery is desirable in the abstract.
  Deferred multi-worker fencing, compaction, parallel tools, subagents, workspace concurrency and
  external-harness reconnect were each attacked and each found genuinely safe to defer; they are
  recorded as already covered in `CONTRACT_GAPS.md`.
- No production code or tests were modified. This branch adds four documents under
  `docs/research/harness-v1-architecture-review/` and nothing else.

---

## Standing rule preserved

Nothing in this review weakens the frozen position that Cerebro does not promise generic
exactly-once external side effects. AR-04 and AR-06 both push in the opposite direction: AR-04 asks
that an unresolvable effect be made *visible* rather than quietly buried under a terminal turn, and
AR-06 asks that the durable operation key which makes a declared idempotent retry safe actually
survive the crash it exists to survive. Neither authorises a repeat dispatch that the frozen
executor-capability rules would forbid.
