# Harness v1 Phase 1A review handoff

Issue: #213 — `Review: Phase 1A Harness contracts and adapter implementation`

Status: **review complete**

Verdict: **MERGEABLE AFTER FIXES**

Date: 2026-08-29

## Exact reviewed baseline

The implementation was reviewed at the immutable SHA requested by issue #213:

`implement/harness-v1-phase1a-contracts@d000ba85c316e146943a2d181da03098e0daebcd`

Against:

- base `main@920ff0fe325f6c5cbd337d2217aa97d90a6a62eb`
- clarified contract `design/harness-v1-contract-clarifications@05fb8fa09c47598bbeed16c9be279f5dfe2a648b`
- architecture audit `review/harness-v1-architecture-audit@46865080a74a20f7406df506d7c6668ffdafc283`

The review branch `review/harness-v1-phase1a` began exactly at the reviewed implementation SHA. The implementation compare is four commits / 40 changed files ahead of the stated base.

Root `AGENTS.md` and issue #213 were read before implementation review.

## Accepted findings

| ID | Class | Required disposition |
| --- | --- | --- |
| P1A-01 | `MUST_FIX` | Cancellation must not finalize accumulated text/tool deltas or emit normal completion. |
| P1A-02 | `MUST_FIX` | `InferenceAttempt` must reject the full matrix of impossible dispatch/barrier/semantic combinations, including on deserialize. |
| P1A-03 | `MUST_FIX` | AR-02 supersession must never remove a causal tool call while retaining its committed result. |
| P1A-04 | `MUST_FIX` | External-agent cancellation must work through the public lifecycle without an extra `track()` call, and the clarified cancel token must be restored. |
| P1A-05 | `MUST_FIX` | Sensitive opaque replay payload must be absent from validation/error observability, including discriminated/nested validation. |
| P1A-06 | `FOLLOW_UP` | Preserve/refuse missing provider-native call-id provenance before Harness adapter activation. |
| P1A-07 | `FOLLOW_UP` | Strengthen the import-boundary regression guard beyond one exact import syntax. |

No `BLOCKER` was found. The five merge-required defects are narrow implementation/contract mismatches and do not require redesigning the frozen Harness architecture.

Full failure sequences, smallest corrections and test requirements are in `FINDINGS.md`. The adversarial test matrix is in `TEST_GAPS.md`.

## Important covered areas

The review found the following adequately handled in the reviewed SHA:

- OpenAI-specific roles, `tool_calls`, `tool_call_id`, wire tool naming and finish-reason handling remain at adapter/dialect or legacy transport boundaries.
- Valid fresh provider-native call ids become `ProviderCallRef`; independently minted `CerebroCallId` remains the canonical execution identity.
- Replayed OpenAI tool history requires a provider ref and does not substitute `CerebroCallId` for a native call id.
- `attempt_id` on `prepare()` remains execution/control metadata: it is not part of `InferenceRequest`, the provider payload or the request semantic hash.
- `InferenceItem`, `InferenceAttempt` and `ToolExecution` each carry their required `format_version`; unknown/missing persisted versions fail explicitly.
- The OpenAI transport extraction into `stream_payload()` preserves current `stream()` payload construction/parser behavior; `ProviderError.status_code` is additive and does not change the existing error message.
- The external-agent contract is structurally separate from `ProviderAdapter`; restart recovery remains explicitly unsupported rather than fabricated.
- No SQL migration, Harness persistence store, recovery driver, reducer/effect cutover, provider-selection cutover, new SDK or external paid-agent invocation was introduced.
- `cerebro/runtime.py::AgentRuntime` remains the live production path.
- The listed edits to existing runtime/test files are only trailing EOF blank-line cleanup.

## What the implementation branch should change

Keep the repair set narrow:

1. Correct cancellation finalization in `OpenAICompatibleAdapter.stream()` and add mid-text / mid-tool-fragment regressions.
2. Tighten the `InferenceAttempt` model validator and table-test valid/invalid persisted states, preserving pre- versus post-barrier failure/abandonment distinction.
3. Make AR-02 protection fail closed around committed tool results and add multiple-call/partial-protection tests.
4. Make CLI external cancellation usable from the declared protocol lifecycle and restore the clarified cancel token, without adding restart recovery.
5. Hide sensitive opaque input values from direct, discriminated and nested validation errors while retaining exact durable serialization.

Do not expand those fixes into PR 2 persistence, PR 3 checkpoint/tool-plan work, reducer/effect cutover or provider-selection migration.

## Test posture

The implementation reports `flake8 .` clean and `PYTHONPATH=. pytest -q` -> 566 passed, 3 skipped. No GitHub Actions workflow run is attached to the reviewed SHA.

This review did not rely on the pass count as proof of the safety properties. It mapped tests to invariants and found the missing adversarial cases above.

The review branch itself changes documentation only, so root `AGENTS.md` permits skipping lint/tests for the review commits.

## Review branch commit chain

From the immutable implementation SHA:

- `d000ba85c316e146943a2d181da03098e0daebcd` — reviewed implementation / review branch point
- `5f87ec7f36a648cc504768a413b20edbe9fd24fa` — Record Phase 1A implementation review verdict
- `d4bf7fc8544899abb72af0a0368b89fdf1ef5c68` — Document Phase 1A review findings
- `26fce258c8c0fede46a6b23388d9f1247d1bf31c` — Map Phase 1A adversarial test gaps
- final handoff commit follows `26fce258c8c0fede46a6b23388d9f1247d1bf31c`

A Git commit cannot contain its own SHA without changing it. The authoritative final review head is therefore the branch ref after this handoff commit and is recorded verbatim in the issue #213 completion comment.

## Durable deliverables

All review output is documentation under `docs/research/harness-v1-phase1a-review/`:

- `REVIEW.md` — verdict, merge bar, covered areas and scope assessment
- `FINDINGS.md` — accepted findings with exact symbols, failure sequences, contract violations, smallest fixes and deterministic tests
- `TEST_GAPS.md` — adversarial coverage matrix
- `HANDOFF.md` — this resumption record

No production or test code was modified on the review branch.
