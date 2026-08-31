# Harness v1 Phase 1A repair-delta review

Issue: #215 — `Review: verify Phase 1A repair delta before merge`

Implementation PR: #214

Review branch: `review/harness-v1-phase1a-repair`

Reviewed delta:

`d000ba85c316e146943a2d181da03098e0daebcd`
through
`9c8638f725a31443ebf6a50f381c9bf1ffa0e75c`

Prior independent review:

`review/harness-v1-phase1a@853d3217ae1e2cb454ceb14a58bbc2f7c167f2aa`

## Verdict

**MERGEABLE**

No `MUST_FIX` finding remains in the repair delta. P1A-01 through P1A-05 are resolved, and the repair does not introduce a new merge-blocking defect or Phase 1B scope.

P1A-06 and P1A-07 remain the prior review's nonblocking `FOLLOW_UP` findings and were not reopened.

## Finding dispositions

| ID | Classification | Repair-delta conclusion |
| --- | --- | --- |
| P1A-01 | `FALSE_POSITIVE / COVERED` | Cancellation exits before any semantic finalization, emits no normal completion, and closes the provider iterator on the token-cancellation path. |
| P1A-02 | `FALSE_POSITIVE / COVERED` | Construction/deserialization enforce the required dispatch/barrier/semantic-state matrix, and transition methods validate the complete target state atomically. |
| P1A-03 | `FALSE_POSITIVE / COVERED` | Active committed tool results derive protection for their causal calls; caller protection still covers unresolved escaped calls; supersession remains attempt-scoped and suffix-only. |
| P1A-04 | `FALSE_POSITIVE / COVERED` | The declared external-agent lifecycle owns cancellation without `track()`: the stream task self-registers, is removed in `finally`, and `cancel()` reaches existing CLI subprocess cleanup. |
| P1A-05 | `FALSE_POSITIVE / COVERED` | Sensitive opaque payload input is hidden across direct, union, request and event validation errors and their string/traceback/log surfaces while durable serialization stays exact. |
| P1A-06 | `FOLLOW_UP` | Unchanged from review #213; not worsened by this repair. |
| P1A-07 | `FOLLOW_UP` | Unchanged from review #213; not worsened by this repair. |

## P1A-01 — cancellation

`cerebro/harness/adapters/openai_compatible.py::OpenAICompatibleAdapter.stream()` now keeps the provider iterator in a local `stream`, checks the cancellation token before processing each received delta and again after stream exhaustion, and returns immediately when cancellation is observed. The text, reasoning, tool-call, provider-metadata and `InferenceCompleted` finalization block is below that return and therefore cannot run after token cancellation.

The cancellation `finally` calls `aclose()` on the underlying iterator when available. The new text and tool-fragment tests use a transport whose async generator records its `finally`, cancel after the first emitted semantic delta, and assert:

- only the pre-cancellation delta is observed;
- zero `OutputItemCompleted` events are emitted;
- zero `InferenceCompleted` events are emitted;
- the provider iterator is closed.

Reasoning accumulation uses the same cancellation exit before the common finalization block, so partial reasoning cannot become a completed `ReasoningSummaryItem` after cancellation either.

## P1A-02 — `InferenceAttempt` state matrix

`cerebro/harness/attempts.py::InferenceAttempt._consistent_terminal_state()` now enforces the stable-state invariants required by the prior review:

- `admitted` means active and pre-barrier;
- `dispatch_may_have_escaped` means active and post-barrier;
- terminal dispatch requires a terminal semantic state;
- a terminal semantic state requires terminal dispatch;
- `completed` requires a committed barrier and completion status;
- `cancelled_before_dispatch` cannot have a committed barrier;
- `failed` requires an `InferenceError`.

The table-driven tests exercise both direct model validation and `load_attempt()`. They reject admitted+barrier, admitted+terminal semantic, escaped-without-barrier, escaped+terminal semantic, terminal+active, completed-without-barrier, and terminal semantic+nonterminal dispatch. They also explicitly accept `failed` and `abandoned` on both sides of the dispatch barrier.

Transitions now go through `_validated_update()`, which validates a complete prospective state before applying its fields. Dispatch remains monotonic, terminal attempts cannot transition again, completion still requires the barrier, and failed/abandoned transitions preserve the pre- versus post-barrier distinction.

## P1A-03 — AR-02 causal history

`cerebro/harness/history.py::InferenceHistory.supersede_abandoned_attempt()` now derives `committed_result_calls` from active `ToolResultItem`s whose call ids belong to active calls from the abandoned attempt, and unions those ids with caller-supplied `protected_call_ids`.

That has the required effects:

- an active committed result automatically protects its causal `ToolCallItem`, even if the caller omitted that id;
- caller-supplied ids still protect unresolved calls that may have escaped but have no committed result;
- the boundary is the last protected attempt-produced call, preserving the necessary causal prefix;
- only active items produced by the abandoned attempt after that boundary are superseded;
- unrelated conversation/context items and harness-local tool results are not rewritten.

The repair tests cover committed-result protection with no caller protection, multiple calls with a protected first effect and safe trailing supersession, a protected later call/result preserving the full prefix, an interleaved unrelated user item, and the invariant that every active tool result has an active causal call.

## P1A-04 — external-agent cancellation

`cerebro/harness/adapters/cli_external.py` and `cerebro/harness/external_agent.py` restore the cancellation token to the declared lifecycle and remove the concrete-only `track()` helper.

`stream_events()` registers `asyncio.current_task()` in `_live` before provider dispatch, checks a pre-cancelled token before creating the provider stream, checks the token while consuming provider deltas, closes the stream in `finally`, and removes only its own task mapping. `cancel(execution_id)` removes and cancels the registered task.

The public-lifecycle regression uses only `start_or_resume()`, `stream_events()` and `cancel()`. A hanging fake provider observes `CancelledError`, proving cancellation reaches the task that owns the provider stream; the test also proves cleanup and `_live` removal. Separate cases prove a token cancelled before streaming and a token cancelled after `start_or_resume()` but before streaming prevent provider dispatch.

The unchanged `cerebro/providers/cli_agent.py::CliAgentProvider.stream()` catches `CancelledError`, calls `_terminate(proc)`, and re-raises, so task cancellation continues to reach the existing child-process kill path.

No violating registration/removal race was found in the requested lifecycle: once `stream_events()` is active, task registration precedes provider dispatch, and the identity check in `finally` prevents an older stream from deleting a different task's mapping.

Restart/reconnect/orphan recovery remains explicitly unsupported: the recovery capability still claims no reconnect/resume/orphan reconciliation, and `reconcile_orphan()` still returns `suspend`.

## P1A-05 — sensitive replay validation errors

The repair sets Pydantic `hide_input_in_errors=True` on the inference-item envelope, `InferenceRequest`, and attempt-scoped inference-event base, and also configures the discriminated-union `TypeAdapter`s for items and events to hide inputs.

The sentinel regression forces an invalid `ProviderOpaqueItem` through:

- direct `ProviderOpaqueItem` construction;
- `load_item()` union validation;
- nested `InferenceRequest` validation via `load_request()`;
- nested output-item event validation via `load_event()`.

For every path it asserts the sentinel is absent from `str(exc)`, `repr(exc)`, formatted traceback text and logged exception output. The existing durable-path assertion still verifies `dump_item()` preserves the exact sentinel payload.

## Regression and scope check

The exact repair compare is six commits touching 15 files, with 552 additions and 111 deletions. The changed paths are limited to the five repair areas, their tests, and Harness documentation. The delta contains no SQL/migration or Harness persistence file, no `TurnRecoveryDriver`, no StepSnapshot persistence, no tool checkpoint transaction, no reducer/effect cutover, no provider-selection cutover, no native Anthropic/Gemini provider, and no external-agent restart recovery.

`cerebro/runtime.py` has the identical blob SHA `3d55bbc3b7a020e68ad53d213a45e170d616d071` at both ends of the reviewed delta. `AgentRuntime` therefore remains the active execution path; this repair did not cut over runtime execution.

## Test posture

The implementation handoff and PR #214 report at repaired head:

- focused Harness repair suite: **138 passed**;
- `flake8 .`: clean;
- `PYTHONPATH=. pytest -q`: **593 passed, 3 skipped**.

No GitHub Actions workflow run is attached to `9c8638f725a31443ebf6a50f381c9bf1ffa0e75c`, so this review does not present those counts as independently witnessed CI results. The required adversarial regressions were verified directly in the immutable repaired source and test files.

This review changes documentation only. Per root `AGENTS.md`, lint and tests may be skipped for documentation-only changes.
