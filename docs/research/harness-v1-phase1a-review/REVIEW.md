# Harness v1 Phase 1A implementation review

Issue: #213 — `Review: Phase 1A Harness contracts and adapter implementation`

Date: 2026-08-29

Verdict: **MERGEABLE AFTER FIXES**

## Immutable review inputs

Reviewed implementation only at:

- `implement/harness-v1-phase1a-contracts@d000ba85c316e146943a2d181da03098e0daebcd`
- base `main@920ff0fe325f6c5cbd337d2217aa97d90a6a62eb`
- clarified contract `design/harness-v1-contract-clarifications@05fb8fa09c47598bbeed16c9be279f5dfe2a648b`
- architecture audit `review/harness-v1-architecture-audit@46865080a74a20f7406df506d7c6668ffdafc283`

The review branch began exactly at the implementation SHA. GitHub compare reports the implementation is four commits / 40 files ahead of the stated base.

Root `AGENTS.md` and issue #213 were read first as required.

## Verdict basis

Phase 1A is structurally close to the clarified architecture and remains a non-cutover foundation. Provider-neutral canonical types, the OpenAI dialect edge, the external-agent boundary, per-family format versions, provider/canonical call identity separation, and the current-runtime compatibility split are mostly implemented as intended.

It is not safe to merge unchanged because five concrete contract defects remain:

1. `OpenAICompatibleAdapter.stream()` turns accumulated deltas into authoritative completed items and a normal `InferenceCompleted` after cancellation.
2. `InferenceAttempt` accepts impossible persisted state combinations even though its transition methods normally avoid them.
3. `InferenceHistory.supersede_abandoned_attempt()` can remove a provider tool call while retaining its committed harness-local result unless the caller supplies a perfect protection set.
4. `ExternalAgentAdapter` dropped the clarified `cancel_token`, while `CliExternalAgentAdapter.cancel()` is a no-op for the normal `start_or_resume()` / `stream_events()` lifecycle unless a caller uses the extra, non-protocol `track()` method.
5. `ProviderOpaqueItem` redacts `repr`/logging projections but Pydantic validation errors can still include `exact_payload`, including through the durable `load_item()` path.

All five are narrow enough to correct on the implementation branch without reopening architecture.

A sixth provider-call-identity concern is recorded as follow-up/test-gate rather than a merge blocker: the legacy transport synthesizes `call_{index}` when an OpenAI-compatible server omits a native call id. The new adapter cannot distinguish that fallback from a provider-issued id and therefore may label it `ProviderCallRef.native_call_id`. Before the adapter becomes active, the Harness path should preserve/refuse missing-id provenance instead of silently treating a fabricated transport fallback as provider-owned.

## Findings summary

| ID | Class | Area | Merge disposition |
| --- | --- | --- | --- |
| P1A-01 | `MUST_FIX` | OpenAI adapter cancellation | Fix before merge |
| P1A-02 | `MUST_FIX` | `InferenceAttempt` invariant matrix | Fix before merge |
| P1A-03 | `MUST_FIX` | AR-02 supersession / committed result causality | Fix before merge |
| P1A-04 | `MUST_FIX` | External-agent cancellation ownership | Fix before merge |
| P1A-05 | `MUST_FIX` | Sensitive opaque validation/error leakage | Fix before merge |
| P1A-06 | `FOLLOW_UP` | Missing provider-native call-id provenance | Gate before Harness adapter activation |
| P1A-07 | `FOLLOW_UP` | Import-boundary guard strength | Strengthen regression guard |

Detailed sequences, corrections and deterministic tests are in `FINDINGS.md`. Coverage gaps are in `TEST_GAPS.md`.

## Contract fidelity that is covered

### Provider/canonical call identity

For valid OpenAI-compatible tool calls, the adapter does the important split correctly:

- fresh streamed calls mint `CerebroCallId.generate()`;
- the wire id is retained separately as `ProviderCallRef.native_call_id`;
- replay serialization obtains `tool_call_id` from `ProviderCallRef`, not from `CerebroCallId`;
- a replayed call with no provider ref fails explicitly instead of borrowing the Cerebro id.

The remaining missing-id fallback concern is P1A-06, not an identity conflation in the normal path.

### `attempt_id` on `prepare()`

The keyword-only attempt identity is control/execution metadata as required:

- it is stored on `PreparedProviderRequest`;
- it is not added to the OpenAI wire payload;
- `request_semantic_hash()` hashes `InferenceRequest`, which contains no attempt id;
- preparing the request therefore does not make attempt identity part of model semantics.

A direct regression test comparing two prepares of the same request under different attempt ids would still be useful, but the implementation itself is correct.

### OpenAI dialect isolation

OpenAI chat roles, `tool_calls`, `tool_call_id`, wire function names and finish-reason mapping are confined to `cerebro/harness/adapters/openai_dialect.py`, `cerebro/harness/adapters/openai_compatible.py`, or the pre-existing `cerebro/providers/openai_compatible.py` transport. Canonical item/tool/request models do not carry those wire shapes.

`cerebro/harness/projection.py` is an explicit compatibility edge for collaboration `Message` rows and deliberately refuses to reconstruct tool rounds from `Message.meta_json`.

### Format/version serialization

The clarified persisted families are versioned:

- `InferenceItem.format_version`
- `InferenceAttempt.format_version`
- `ToolExecution.format_version`

`load_item`, `load_attempt` and `load_tool_execution` reject missing/future versions before validation. `InferenceItem` uses a discriminated union, so an unknown item variant is not silently coerced into another type. Canonical JSON uses sorted keys and compact separators.

The state-validity defect in P1A-02 is separate: a known version can currently contain an impossible combination that the model validator accepts.

### Existing transport modification

The `OpenAICompatibleProvider.stream_payload()` extraction preserves the pre-existing `stream()` payload construction and SSE parser. `stream()` now builds the same payload and delegates to `stream_payload()`. `ProviderError.status_code` is additive; the current user-visible error string is unchanged. No current `AgentRuntime` selection path was changed.

### Scope discipline

The exact compare contains no:

- SQL migration;
- Harness persistence store;
- `TurnRecoveryDriver`;
- reducer/effect cutover;
- `RuntimeService._provider_for` cutover;
- new provider SDK;
- external paid-agent invocation;
- production Harness selection path.

`cerebro/runtime.py::AgentRuntime` remains active. The only runtime-file diff is removal of the final blank line.

### Whitespace edits

The exact GitHub compare shows the listed old files only lose EOF blank lines:

- `cerebro/runtime.py`
- `tests/test_agents_loader.py`
- `tests/test_cli_agent_provider.py`
- `tests/test_context.py`
- `tests/test_service.py`

There is no semantic change in those hunks.

## Test assessment

The implementation adds substantial contract coverage, including ordered history, the dispatch barrier happy path, stale-attempt fencing, valid provider/canonical call identity, OpenAI wire projection, unknown wire tools, malformed tool JSON preservation, redacted direct `repr`/logging, external-adapter structural separation, and unknown format versions.

That coverage does not prove the adversarial cases that fail this review. In particular, there are no deterministic tests for cancellation after partial text/tool JSON, invalid attempt-state deserialization, partial AR-02 protection across multiple calls, validation-error redaction, or external cancellation without `track()`.

No GitHub Actions run is attached to the reviewed SHA. The implementer reports `flake8 .` clean and `PYTHONPATH=. pytest -q` as 566 passed / 3 skipped; this review does not use that report as evidence for the missing invariants above.

## Merge bar

`MERGEABLE AFTER FIXES` means the implementation branch should correct P1A-01 through P1A-05 and add the deterministic tests specified in `FINDINGS.md` / `TEST_GAPS.md`. The corrections do not require SQL, persistence, reducer work, provider-selection cutover or architecture changes.
