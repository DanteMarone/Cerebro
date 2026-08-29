# Harness v1 architecture review handoff

Issue: #209 — `Review: adversarial audit of frozen Harness v1 architecture`

Status: **review complete**

Recommendation: **PROCEED WITH CONTRACT CLARIFICATIONS**

Date: 2026-08-29

---

## Exact reviewed baseline

Reviewed at this immutable SHA, not at a moving branch tip:

`design/harness-v1-reconciliation@f0b792fd02b72b53375babd7c02a8b95bdeb1902`
(commit `Finalize Harness v1 design handoff`, 2026-08-29)

Documents read in full at that SHA:

- `docs/research/codex-harness/CEREBRO_HARNESS_V1.md` (892 lines) — cited as `ARCH §n`
- `docs/research/harness-v1/RECONCILIATION.md` (219 lines) — cited as `RECON §n`
- `docs/research/harness-v1/PHASE_1_CONTRACT.md` (1093 lines) — cited as `P1 §n`
- `docs/research/harness-v1/HANDOFF.md` (206 lines) — cited as `HANDOFF`

Also read: root `AGENTS.md`, issue #209 (full body), issue #206 (full body, closed).

Review branch: `review/harness-v1-architecture-audit`, branched from the frozen SHA.

## Source verifications performed

Archaeology was not repeated. Four targeted checks against the current working tree confirmed
specific frozen claims that findings depend on:

| Claim verified | Result | Used by |
| --- | --- | --- |
| What `RuntimeService.start()` does on process start | `cerebro/service.py:255` — runs `_sweep_orphaned_placeholders()` only, which deletes empty legacy `messages` rows. No enumeration of in-flight turns. | AR-01 |
| `run_in_writer` transaction semantics | `cerebro/db.py:242` — "Execute a callable atomically on the single-writer connection inside a transaction." Confirms `P1 §23` is achievable; `store.add_message` currently uses `_execute_write` instead. | AR-05 |
| Whether tool-protocol `Message.meta_json` is persisted | `cerebro/runtime.py` builds tool-call/tool-result `Message` objects into a local `transcript` list and never writes them. Persisted `meta_json` comes from `cerebro/transcript_import.py` (product/import metadata). | "no meta_json backfill" false positive |
| Whether `tool_calls` / `audit_events` are runtime state | No SQL in `cerebro/` reads or writes either table. | `ARCH §17` / `P1 §24` non-reuse claim confirmed |

## Deliverables on this branch

All four are documentation under `docs/research/harness-v1-architecture-review/`:

1. `REVIEW.md` — verdict, ranked findings table, detailed treatment of the top five, and an explicit
   statement of what the review declined to do.
2. `CONTRACT_GAPS.md` — full analysis of all twelve accepted findings (frozen citation, concrete
   failure sequence, why the current text does not prevent it, smallest correction,
   architecture-versus-contract, gated PR), plus fifteen investigated concerns recorded as
   `FALSE_POSITIVE / ALREADY_COVERED` with citations.
3. `IMPLEMENTATION_GATES.md` — finding-to-PR mapping, per-PR merge bars, the two corrections that
   must land before PR 1 opens, and the four new fixtures F-21 through F-24.
4. `HANDOFF.md` — this file.

No production code or tests were changed. This branch differs from the frozen SHA only by these
four new files.

## Findings summary

| Class | Count | IDs |
| --- | --- | --- |
| `BLOCKER` | 0 | — |
| `MUST_CLARIFY_BEFORE_PR` | 9 | AR-01 … AR-09 |
| `NON_BLOCKING` | 3 | AR-10, AR-11, AR-12 |
| `FALSE_POSITIVE / ALREADY_COVERED` | 15 | recorded in `CONTRACT_GAPS.md` |

Ranked, with the PR each gates:

1. **AR-01** — no component owns post-restart resumption of a durable `AgentTurn`; six mandatory
   fixtures assume a driver the architecture never names. → PR 2, PR 4
2. **AR-02** — an interrupted attempt's committed output items have no defined disposition, and
   `InferenceItem` carries no producing-attempt identity to express one. → PR 1, PR 2, PR 4
3. **AR-03** — `inference_items` is turn-owned but `ReplayRetentionScope.conversation` has no
   storage home; forces a re-key at PR 7. → PR 2
4. **AR-04** — `indeterminate_needs_attention` has no owner and no surface; a terminal
   `cancelled`/`failed` turn can silently bury an escaped side effect. → PR 4, PR 5
5. **AR-05** — finalization is called "idempotent" with no defined predicate; the two derivable
   predicates disagree, and one can make a PASS turn emit a message. → PR 5
6. **AR-06** — checkpoint atomicity boundary undefined; `stable_operation_key` required by
   `ARCH §15` and missing from `P1 §17`; F-07 has no restart to catch it. → PR 3, PR 5
7. **AR-07** — `CausalWakeKey` uniqueness can permanently wedge a wake and can silently suppress
   legitimate re-wakes; zero fixture coverage. → PR 2
8. **AR-08** — "exactly one execution authority per causal wake" is a safety invariant filed as an
   implementation-review question, with no fixture. → PR 3, PR 4
9. **AR-09** — F-05, F-07 and F-14 do not prove their invariants; four invariants have no fixture. → PR 5
10. **AR-10** — asymmetric format versioning on `inference_items`, `inference_attempts`,
    `tool_executions`. → PR 1, PR 2 (`NON_BLOCKING`)
11. **AR-11** — `reconcile_or_suspend` has no provider-side mechanism;
    `stateless_lossless_replay=false` has no defined behavior. → PR 7 (`NON_BLOCKING`)
12. **AR-12** — at-rest gates not bound to the PR that first creates the data. → PR 3 (`NON_BLOCKING`)

## Exact frozen-document clarifications to land before or with PR 1

The recommendation is `PROCEED WITH CONTRACT CLARIFICATIONS`. These are the clarifications, by
document and section. No architectural redesign is required and no frozen decision is reversed.

**Must be patched before PR 1 code begins** (they change canonical type definitions that PR 2's
schema will persist):

| # | Document / section | Clarification |
| --- | --- | --- |
| 1 | `P1 §6` (+ rule in `ARCH §21` / `P1 §12`) | AR-02: add producing-attempt identity to `InferenceItem`; add the rule that output items from an attempt which never reached `InferenceCompleted` and authorized no dispatched side effect are attempt-scoped, marked superseded on abandonment, excluded from the next request's history, and retained as audit evidence. |
| 2 | `P1 §2`, `§6`, `§11`, `§16` | AR-10: add `format_version` to `InferenceItem`, `InferenceAttempt`, `ToolExecution`. |

**Must be patched before or with the PR each gates:**

| # | Document / section | Clarification | With PR |
| --- | --- | --- | --- |
| 3 | `ARCH §4`, `P1 §30` | AR-01: give `TurnCoordinator` a startup scan over non-terminal `agent_turns` for the current `execution_epoch`; a turn Phase 1 cannot resume goes durably to `suspended` with a reason rather than staying `running`. | PR 2 |
| 4 | `P1 §6`, `§24` | AR-03: state the `inference_items` key — conversation-scoped with turn attribution (preferred), or turn-scoped with `ReplayRetentionScope.conversation` explicitly rejected by adapter validation. | PR 2 |
| 5 | `P1 §3` (+ `HANDOFF` question 4) | AR-07: duplicate-key load applies only to non-terminal, recoverable turns; a wake matching a terminal turn is admitted under a distinct `occurrence_id` or explicitly declined with a recorded reason, never silently dropped. Answer the per-path `CausalWakeKey` encoding before writing the constraint. | PR 2 |
| 6 | `P1 §17` | AR-06: add `stable_operation_key` to the checkpoint set (aligning with `ARCH §15`), and state which of A–L are atomic versus verified preconditions. | PR 3 |
| 7 | `ARCH §29`, `P1 §16`/`§19`, `P1 §31` | AR-08: promote "exactly one execution path may dispatch providers, dispatch tools, or insert collaboration rows for a given `CausalWakeKey`" to a frozen invariant; remove item 6 from `P1 §31`'s "not architecture ambiguity" list. | PR 3 |
| 8 | `P1 §4`, `§19` | AR-04: add an `AgentTurn` attention marker maintained in the same transaction as every `ToolExecution` transition; turn termination never implicitly resolves an outstanding `dispatch_may_have_escaped` execution; state the Phase 1 minimum surface. | PR 4 |
| 9 | `P1 §4`, `§23` | AR-05: name `product_outcome_kind` as the sole finalization discriminator; `final_message_id` is never a finalization predicate; any terminal lifecycle publishing a user-visible row — `failed` included — sets both in the finalization transaction. | PR 5 |
| 10 | `P1 §28`, `§30` | AR-09: restate F-05, F-07 and F-14; add F-21 through F-24; raise the Phase 1D exit bar to F-01 through F-24. | PR 5 |
| 11 | `P1 §8.2`, `§9`, `§12` | AR-11: Phase 1 admits only adapter/profile combinations whose required continuation state is expressible as durable ordered replay items and refs; note that `reconcile_or_suspend` degenerates to `suspend` for provider attempts. | PR 7 (note in PR 1) |
| 12 | `P1 §31` items 2, 3 | AR-12: bind item 3 to PR 3 and item 2 to PR 1 or the first PR whose adapter surfaces reasoning content. | PR 3 |

## What remains frozen

This review reopens nothing in `ARCH §29`, `HANDOFF` frozen decisions 1–29, or `RECON §8`'s rejected
migration shortcuts. In particular it does not weaken frozen decision 18: Cerebro does not promise
generic exactly-once external side effects, and automatic repeat dispatch after a side effect may
have escaped still requires executor proof of read-only behavior, idempotency, externally enforced
stable idempotency, or authoritative reconciliation. AR-04 and AR-06 reinforce that rule — AR-04 by
making an unresolvable effect visible instead of burying it under a terminal turn, AR-06 by ensuring
the durable operation key that makes a declared idempotent retry safe actually survives the crash it
exists to survive.

## Commit chain on this branch

Incremental, in order, from the frozen SHA:

- `f0b792fd02b72b53375babd7c02a8b95bdeb1902` — (frozen baseline; branch point)
- `f3f63175758020798cacdf21560468cbb2ec3d21` — Record Harness v1 architecture-review contract gaps
- `a32c89de86c441a557145d05667efe99b3cbe5eb` — Add Harness v1 architecture review verdict and ranked findings
- `a275b51a568d14e677a8a32f1848e745be994c88` — Map Harness v1 review findings to implementation PR gates
- final handoff commit follows `a275b51a` and is the branch ref recorded in the issue #209 completion comment

> A Git commit cannot contain its own final SHA without changing that SHA. The authoritative final
> branch head is therefore the ref after this handoff commit, recorded on issue #209. This file
> records the exact predecessor head and the complete commit chain so a fresh agent can verify the
> final ref without relying on chat history.

## Next action

Open the frozen-document clarification patch (items 1–2 above at minimum) against
`design/harness-v1-reconciliation`, then open implementation PR 1 —
*Harness v1 canonical contracts and compatibility adapters* — per `ARCH §26` and the `HANDOFF`
ordered PR sequence, with the merge bar in `IMPLEMENTATION_GATES.md`.

## Testing

No lint or test run is required for this branch: it changes documentation only, which root
`AGENTS.md` explicitly exempts. Production implementation PRs must restore the normal `flake8 .` and
`PYTHONPATH=. pytest -q` requirements and carry the Phase 0 plus Phase 1 acceptance coverage
appropriate to their slice.
