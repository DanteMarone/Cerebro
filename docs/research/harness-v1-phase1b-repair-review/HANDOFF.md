# Harness v1 Phase 1B repair-review handoff

Issue: #218 — `Review: verify Phase 1B repair delta before merge`

Status: **complete**

Verdict: **MERGEABLE**

## Exact reviewed inputs

- repair baseline: `abd1d702741adb795f13024ba2e9f4bf38310ecb`
- repaired head: `178968213d0cf255c2e6fd91330717a340c4e0f9`
- exact delta: `abd1d702741adb795f13024ba2e9f4bf38310ecb...178968213d0cf255c2e6fd91330717a340c4e0f9`
- independent review requiring repair: `review/harness-v1-phase1b@2592b32d62c03d28edfc49f666ecfa967a919d0e`
- review branch: `review/harness-v1-phase1b-repair`

Root `AGENTS.md`, issue #218, and the prior Phase 1B `FINDINGS.md`, `TEST_GAPS.md`, and `HANDOFF.md` were read before dispositioning the repair.

## Disposition

All six accepted findings are `FALSE_POSITIVE / COVERED` in the repaired delta:

1. P1B-01: supersession requires durable abandonment and derives persisted possibly-escaped ToolExecution protection in the same writer transaction; caller protection is additive.
2. P1B-02: recovery enumerates raw candidate identities, isolates strict-decode/reference damage per candidate, suspends loadable corrupt-reference turns, reloads stale CAS races, and continues later candidates without provider/tool side effects.
3. P1B-03: attempt-generation uniqueness is scoped to `(step_snapshot_id, attempt_generation)` and TG-04 proves both permitted reuse and prohibited duplication.
4. P1B-04: terminal/current projection gates cover new snapshot/attempt/tool admission plus provider/tool dispatch, current provider attempt/snapshot fencing and step monotonicity; terminal finalization identity is SQL-frozen while existing uncertain effects remain reconcilable after terminalization.
5. P1B-05: a cross-turn ToolCallItem is rejected before ToolExecution row/event mutation.
6. P1B-06: recovery/history/attention/unresolved discovery validates canonical payload/duplicated columns before applying filter-critical semantics.

No `MUST_FIX` or `FOLLOW_UP` remains.

## Adversarial test review

TG-01 through TG-19 were inspected as implementations, not accepted by name alone. The required sequences are present, including:

- close/reopen escaped-call causal-prefix preservation;
- loadable missing-reference recovery plus a strict-undecodable AgentTurn before a later candidate;
- deterministic stale-CAS injection;
- terminal effect admission/dispatch rollback;
- raw SQL terminal-finalization mutation rejection;
- post-terminal multi-call attention reconciliation;
- trigger execution after an actual 001-004 > 005 upgrade;
- causal hash/text mismatch;
- two AgentTurns interleaving one conversation-owned history with CAS and reopen;
- unknown format versions through direct and discovery/list paths.

The implementation handoff records `41 passed` for the focused migration/store run, `630 passed, 3 skipped` for the full suite, clean `flake8 .`, and clean `git diff --check` at repair code/test head `5ee6d3c9c23d311552ceda48dc840c4e645351ee`. These were treated as evidence; this review independently inspected the source/migration/tests but did not independently execute the suite in the review environment.

## Scope check

The reviewed delta modifies only the Harness store/recovery/migration, their tests, and documentation. It adds no executable Phase 1C StepSnapshot/tool plan, reducer/effect execution, RuntimeService/AgentRuntime cutover, provider selection, native provider implementation, raw-output policy, product finalization cutover, external-agent recovery, or multi-worker fencing.

## Deliverables

Only these review documents were added:

- `docs/research/harness-v1-phase1b-repair-review/REVIEW.md`
- `docs/research/harness-v1-phase1b-repair-review/HANDOFF.md`

No production or test code was modified by the review. No PR was opened or merged.

Review documentation commit chain:

- `9dce6ae06872f62f8e220f97d122f582e4f76b0e` — record Phase 1B repair delta review
- this handoff-finalization commit follows

A Git commit cannot contain its own SHA without changing it. The exact final review SHA is therefore posted to issue #218.
