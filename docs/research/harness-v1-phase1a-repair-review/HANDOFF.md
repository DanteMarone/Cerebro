# Harness v1 Phase 1A repair review handoff

Issue: #215 — `Review: verify Phase 1A repair delta before merge`

Status: **review complete**

Verdict: **MERGEABLE**

Date: 2026-08-30

## Exact reviewed delta

This review examined only the repair requested by issue #215:

`d000ba85c316e146943a2d181da03098e0daebcd`
through
`9c8638f725a31443ebf6a50f381c9bf1ffa0e75c`

Implementation PR: #214

Prior independent review baseline:

`review/harness-v1-phase1a@853d3217ae1e2cb454ceb14a58bbc2f7c167f2aa`

The review branch `review/harness-v1-phase1a-repair` began exactly at the repaired implementation head `9c8638f725a31443ebf6a50f381c9bf1ffa0e75c`.

## Result

There are no remaining `MUST_FIX` findings in this repair delta.

- P1A-01 — `FALSE_POSITIVE / COVERED`: cancellation cannot promote partial text, reasoning or tool-call fragments into completed semantic output; no normal completion is emitted; the token-cancellation path closes the provider iterator.
- P1A-02 — `FALSE_POSITIVE / COVERED`: direct construction and `load_attempt()` enforce the required dispatch/barrier/semantic matrix, including valid failed/abandoned states on either side of the barrier; transitions validate atomically.
- P1A-03 — `FALSE_POSITIVE / COVERED`: committed tool results infer protection for causal calls, caller protection still covers unresolved escaped calls, the causal prefix is retained, and unrelated items are untouched.
- P1A-04 — `FALSE_POSITIVE / COVERED`: public lifecycle cancellation works without `track()`; streaming task registration/removal is automatic; task cancellation reaches unchanged `CliAgentProvider` child cleanup; restart recovery remains unsupported.
- P1A-05 — `FALSE_POSITIVE / COVERED`: the opaque replay sentinel is absent from direct, union and nested validation error strings, reprs, tracebacks and logged exceptions; durable `dump_item()` remains exact.

P1A-06 and P1A-07 remain `FOLLOW_UP` findings from review #213. The repair did not materially worsen either one.

Full evidence is in `REVIEW.md` in this directory.

## Scope result

The exact compare is six commits / 15 changed files / 552 additions / 111 deletions. It does not add:

- SQL or Harness persistence;
- `TurnRecoveryDriver`;
- StepSnapshot persistence;
- tool checkpoint transactions;
- reducer/effect cutover;
- provider-selection cutover;
- native Anthropic or Gemini providers;
- external-agent restart recovery.

`cerebro/runtime.py` has the same blob SHA at both ends of the repair delta, so `AgentRuntime` remains the active runtime path.

## Test posture

The implementation reports 138 focused Harness tests passing, `flake8 .` clean, and the full suite at 593 passed / 3 skipped. No GitHub Actions workflow run is attached to the repaired head. This review verified the repair tests and their target code directly from immutable GitHub source rather than treating the reported counts as independent CI evidence.

The review branch itself changes only documentation under `docs/research/harness-v1-phase1a-repair-review/`; root `AGENTS.md` therefore permits skipping lint/tests for the review commit.

## Durable completion

Required review output:

- `docs/research/harness-v1-phase1a-repair-review/REVIEW.md`
- `docs/research/harness-v1-phase1a-repair-review/HANDOFF.md`

No production or test code is modified by this review.

A Git commit cannot include its own SHA without changing that SHA. The authoritative final review commit is therefore recorded in the issue #215 completion comment after this handoff is committed and pushed.

PR #214 is not merged by this review.
