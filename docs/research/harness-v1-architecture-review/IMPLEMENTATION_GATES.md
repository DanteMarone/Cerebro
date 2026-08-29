# Harness v1 implementation gates

Issue: #209 — `Review: adversarial audit of frozen Harness v1 architecture`

Frozen baseline: `design/harness-v1-reconciliation@f0b792fd02b72b53375babd7c02a8b95bdeb1902`

This file maps each accepted review finding to the exact implementation PR that must resolve it, and
states what "resolved" means for that PR. Findings and their full analysis live in
[`CONTRACT_GAPS.md`](CONTRACT_GAPS.md); the verdict lives in [`REVIEW.md`](REVIEW.md).

PR numbering follows `ARCH §26` and the `HANDOFF` "Ordered implementation / PR sequence", which match
each other:

| PR | Frozen name | Phase 1 slice |
| --- | --- | --- |
| PR 1 | Harness v1 canonical contracts and compatibility adapters | Phase 1A |
| PR 2 | Harness v1 additive durable store | Phase 1B |
| PR 3 | Harness v1 `StepSnapshot` and pre-tool checkpoint | Phase 1C |
| PR 4 | Harness v1 durable reducer direct-provider cutover | Phase 1D |
| PR 5 | Harness v1 product finalization and crash hardening | Phase 1D |
| PR 6 | `ContextManager` projection and model-aware budgeting | post-Phase 1 |
| PR 7 | First materially non-OpenAI native provider | post-Phase 1 |

---

## Corrections that must land in the frozen documents before PR 1 opens

Two findings change canonical type definitions. Patching them after PR 1 means editing types that
PR 2's schema already persists, so they are cheapest now and expensive later.

| Finding | Frozen doc to patch | Correction |
| --- | --- | --- |
| **AR-02** | `P1 §6` (and `ARCH §21` / `P1 §12` for the rule) | Add producing-attempt identity to `InferenceItem` (a required `producing_attempt_id`, or mandatory `Provenance.source_kind='inference_attempt'` + `source_id`). Add the rule distinguishing attempt-scoped uncommitted-step output from committed effects. |
| **AR-10** | `P1 §2`, `§6`, `§11`, `§16` | Add `format_version` to `InferenceItem`, `InferenceAttempt` and `ToolExecution` (or to their row envelopes). |

Everything else may be patched into the frozen documents alongside the PR it gates, as scheduled
below.

---

## PR 1 — canonical contracts and compatibility adapters

**Gated by:** AR-02 (primary), AR-10, AR-11 (note only), AR-12 (partial).

| Finding | What PR 1 must do |
| --- | --- |
| AR-02 | Implement `InferenceItem` with producing-attempt identity. The abandonment rule itself is PR 4 behavior, but the type must carry the field from the first definition. |
| AR-10 | Include `format_version` on the three persisted families. |
| AR-11 | Record in the adapter docstring/contract that `ProviderAdapter` has no reconcile operation and that `reconcile_or_suspend` degenerates to `suspend` for provider attempts in Phase 1. No code is required. |
| AR-12 | If the LM Studio / OpenAI-compatible adapter surfaces reasoning content, decide and document the classification (`ReasoningSummaryItem` versus `hidden_reasoning` `ProviderOpaqueItem`) in this PR. If it surfaces none, state that explicitly so the `P1 §31` item-2 gate stays armed. |

**Not gated:** PR 1 introduces no durable store, no dispatch and no finalization, so AR-01, AR-03,
AR-04, AR-05, AR-06, AR-07 and AR-08 do not block it.

---

## PR 2 — additive durable Harness store

**Gated by:** AR-01, AR-03, AR-07, AR-10, AR-02 (schema half).

| Finding | What PR 2 must do |
| --- | --- |
| AR-01 | Provide the index over non-terminal `agent_turns` (`queued`, `running`) by `execution_epoch` that the startup scan requires, and implement the scan or land it in PR 4 with the index in place. A non-terminal turn must never be unreachable. |
| AR-03 | Decide and implement the `inference_items` key: conversation-scoped with turn attribution (preferred), or turn-scoped with `ReplayRetentionScope.conversation` explicitly rejected by adapter validation. This decision is effectively irreversible after PR 2 merges. |
| AR-07 | Implement the causal-admission uniqueness constraint with the lifecycle qualification: duplicate-key load applies only to non-terminal, recoverable turns. Answer `HANDOFF` question 4 — the exact `CausalWakeKey` encoding for immediate-DM, channel-poll and explicit-turn paths, including whether `occurrence_id` participates — **before** writing the constraint, not after. |
| AR-02 | Persist the producing-attempt column and a superseded marker on `inference_items`. |
| AR-10 | Persist the format-version columns. |

**Merge bar:** fixture F-21 (causal admission, per AR-09) passes, including the crash-then-retry arm
that proves a wake is not permanently wedged.

---

## PR 3 — `StepSnapshot` and pre-tool checkpoint

**Gated by:** AR-06, AR-08, AR-12.

| Finding | What PR 3 must do |
| --- | --- |
| AR-06(ii) | Assign and persist `stable_operation_key` inside the checkpoint transaction whenever the frozen binding declares `stable_idempotency_key`. Align `P1 §17` with `ARCH §15` in the frozen doc as part of this PR. |
| AR-06(i) | State and implement the atomic subset of `P1 §17` A–L explicitly. The recommended split is: D, E, E2, I, J, K, L in one transaction; A, B, C, F, G, H verified as preconditions with a fail-closed check. Document the decision in `P1 §17`. |
| AR-08 | If the checkpoint barrier runs while `AgentRuntime._run_tool` still owns execution, prove there is exactly one dispatcher. A shadow path performs no tool dispatch, no provider dispatch and no `messages` insert. Promote the single-authority invariant into `ARCH §29` as part of this PR. |
| AR-12 | Decide raw-output inline threshold, artifact backend, retention and redaction before F-13 lands. This is the PR that first makes tool output durable at rest. |

**Merge bar:** F-04, F-13, F-14 (restated per AR-09), F-15, F-16 pass; F-22 (rollout single
authority) passes if any legacy/harness overlap exists in this slice.

---

## PR 4 — durable reducer direct-provider cutover

**Gated by:** AR-01, AR-02, AR-04, AR-08.

| Finding | What PR 4 must do |
| --- | --- |
| AR-01 | Implement the `TurnCoordinator` startup/recovery scan. Every non-terminal turn reaches a terminal, `suspended`, or resumed state. Turns Phase 1 cannot resume — notably the external-agent path — go to `suspended` with an explicit `suspension_reason`. |
| AR-02 | Implement the abandonment rule: output items from an attempt that never reached `InferenceCompleted` and authorized no dispatched side effect are marked superseded and excluded from the next request's history, and retained as audit evidence. |
| AR-04 | Maintain the `AgentTurn` attention marker in the same transaction as every `ToolExecution` transition. Turn termination never implicitly resolves an outstanding `dispatch_may_have_escaped` execution. |
| AR-08 | Complete the cutover such that legacy and reducer paths cannot both execute one causal wake. If a flag or shadow ships, its non-side-effecting property must be enforced in code, not by convention. |

**Merge bar:** F-03, F-06, F-08, F-09 (with the AR-04 arm), F-10, F-11, F-12, F-20, F-23 and F-24
pass, alongside the full Phase 0 suite.

---

## PR 5 — product finalization and crash hardening

**Gated by:** AR-05, AR-06, AR-09, and the acceptance closure of AR-01 through AR-04.

| Finding | What PR 5 must do |
| --- | --- |
| AR-05 | Implement `product_outcome_kind` as the sole finalization discriminator; never use `final_message_id` as a finalization predicate. Any terminal lifecycle publishing a user-visible row — `failed` included — sets both fields in the finalization transaction. Route the final `messages` insert through a `run_in_writer` callable so the transaction in `P1 §23` is literally achievable (`store.add_message` currently uses `_execute_write`). |
| AR-06 | Land the restated F-05 crash matrix at defined durable boundaries, and the F-07 restart arm proving the operation key survives process death. |
| AR-09 | Restate F-05, F-07 and F-14; add F-21 through F-24. The Phase 1D exit bar becomes **F-01 through F-24 green**, not F-01 through F-20. |

**Merge bar:** F-01 through F-24 green plus the complete Phase 0 characterization suite
(`P1 §27` items 1–28).

---

## PR 7 — first materially non-OpenAI native provider

**Gated by:** AR-03 (if deferred), AR-11.

| Finding | What PR 7 must do |
| --- | --- |
| AR-03 | If PR 2 chose the turn-scoped key with `conversation` scope rejected, this PR must either avoid conversation-scoped required replay or perform the re-key migration first. This is the finding whose cost grows most between now and PR 7. |
| AR-11 | Decide whether `ProviderAdapter` gains a reconciliation operation for escaped attempts against providers whose call advances server-side state, and define the behavior of `stateless_lossless_replay=false`. |

---

## New fixtures introduced by this review

| Fixture | Proves | Owning PR |
| --- | --- | --- |
| F-21 — causal admission | Duplicate wake ⇒ one turn, one execution; wake matching a terminal turn ⇒ defined non-silent outcome; wake matching a crash-orphaned turn ⇒ recovery, not a wedge (AR-07, AR-01) | PR 2 |
| F-22 — rollout single authority | One causal wake ⇒ at most one provider dispatch, at most one tool dispatch per logical call, exactly one collaboration row, with both paths loaded (AR-08) | PR 3 or PR 4 |
| F-23 — orphaned in-flight attempt recovery | Restart with an attempt at `dispatch_may_have_escaped` holding committed partial output ⇒ defined turn state, no truncated assistant turn in the next request, superseded items retained (AR-01, AR-02) | PR 4 |
| F-24 — indeterminate visibility | Cancel during `dispatch_may_have_escaped` on a `never_automatic_repeat` tool ⇒ no second dispatch, no false status, durable readable attention marker after restart (AR-04) | PR 4 |

---

## Findings with no implementation gate

None. Every accepted finding, including the three `NON_BLOCKING` ones, is attached to a PR above so
that nothing is carried forward as an untracked assumption.
