# Phase 1A adversarial test gaps

Reviewed implementation: `d000ba85c316e146943a2d181da03098e0daebcd`

This file maps the important review invariants to existing coverage and the deterministic cases still required before merge or before later Harness activation.

## Merge-required tests

### TG-01 — cancellation midway through assistant text

**Finding:** P1A-01

Current adapter coverage proves normal text finalization, but there is no cancellation case.

Required fixture:

1. Fake transport yields a first text fragment.
2. Consumer observes the resulting `AssistantTextDelta` and cancels the token before the next fragment is processed.
3. Transport yields another fragment so the adapter observes cancellation.
4. Assert zero `OutputItemCompleted` after cancellation and zero normal `InferenceCompleted`.
5. Assert any accumulated text remains delta-only and cannot enter semantic history.

This must fail against the reviewed implementation, which breaks the loop and then runs normal finalization.

### TG-02 — cancellation midway through tool JSON

**Finding:** P1A-01

Required fixture:

1. Fake transport yields `ToolCallDelta(id="call_1", name="fs_read", args_fragment='{"path":')`.
2. Cancel before the remainder arrives.
3. Assert no `ToolCallItem` is finalized and no `InferenceCompleted(status="tool_calls_pending")` is emitted.

Repeat with a first fragment that happens to be syntactically valid JSON. Cancellation, not parseability, controls authority.

### TG-03 — complete `InferenceAttempt` stable-state matrix

**Finding:** P1A-02

Existing tests cover transition happy paths and one barrier/cancellation prohibition. They do not prove deserialized state validity.

Table-drive both direct model construction and `load_attempt()` across at least:

| Dispatch | Barrier | Semantic | Expected |
| --- | --- | --- | --- |
| admitted | false | active | valid |
| dispatch_may_have_escaped | true | active | valid |
| terminal | false | cancelled_before_dispatch | valid |
| terminal | false | failed | valid when error present |
| terminal | true | failed | valid when error present |
| terminal | false | abandoned | valid |
| terminal | true | abandoned | valid |
| terminal | true | completed | valid with completion status |
| admitted | true | active | reject |
| terminal | false | completed | reject |
| terminal | true/false | active | reject |
| admitted/dispatch_may_have_escaped | any | terminal semantic state | reject |
| dispatch_may_have_escaped | false | active | reject |
| terminal | true | cancelled_before_dispatch | reject |

Also retain transition tests proving pre-barrier and post-barrier failure are distinct and monotonic.

### TG-04 — AR-02 multiple calls with partial protection

**Finding:** P1A-03

Existing coverage has one protected call. Required multi-call fixtures:

1. Attempt A produces preamble, call 1, result 1, intermediate text, call 2, result 2, trailing text.
2. Protect only call 1: retain the causal prefix through result 1; permit later unprotected attempt output to supersede only when doing so cannot orphan result 2. If result 2 is committed, its call must remain too.
3. Protect call 2: retain the full causal prefix through call/result 2.
4. Omit a committed call from `protected_call_ids`: the helper must infer protection from the active committed result or fail closed, never leave the result without its call.
5. Interleave unrelated projected conversation items and assert none are superseded.

Invariant assertion after every case: every active `ToolResultItem` has an active causal `ToolCallItem` with the same `CerebroCallId`.

### TG-05 — sensitive opaque validation failures

**Finding:** P1A-05

Existing redaction tests cover valid object `repr`, `str`, log projection, ordinary logging and durable serialization. They do not cover errors.

Use an unmistakable payload sentinel and force validation failures through:

- direct `ProviderOpaqueItem` construction;
- `load_item()` discriminated-union validation;
- a nested `InferenceRequest` carrying an invalid opaque item;
- an event validation path carrying an invalid opaque item where applicable.

For each, assert the sentinel is absent from:

- `str(exc)`;
- `repr(exc)`;
- formatted traceback text;
- logger output if the exception is logged.

The durable `dump_item()` success path should continue to preserve the exact payload intentionally.

### TG-06 — external cancellation without `track()`

**Finding:** P1A-04

The current cancellation test proves only the concrete helper path because it manually invokes `track()`.

Required fixture:

1. Create a hanging fake CLI provider whose stream blocks after signalling it started.
2. Call only `ExternalAgentAdapter` protocol methods: `start_or_resume`, drive `stream_events`, then `cancel(execution_id)`.
3. Never call `track()` or another concrete-adapter-only helper.
4. Assert the task driving the stream receives `CancelledError` and the provider's cancellation cleanup path is reached.
5. Exercise a pre-cancelled / subsequently cancelled `CancelToken` once the clarified parameter is restored.

This is the test that makes cancellation ownership part of the public contract rather than caller folklore.

## Important follow-up tests

### TG-07 — missing provider-native call id is not promoted to `ProviderCallRef`

**Finding:** P1A-06

Unknown wire tool names are already covered and correctly become unresolved canonical keys. Missing provider-native call-id provenance is not covered.

Feed the real OpenAI-compatible SSE transport a tool call with no `id`, then pass its deltas through the Harness adapter. Before adapter activation, assert a locally synthesized transport fallback cannot silently become `ProviderCallRef.native_call_id` as though the provider issued it.

Malformed argument JSON is already covered: it remains representable as `TextToolInput` rather than being repaired.

### TG-08 — import-boundary policy catches equivalent reverse dependencies

**Finding:** P1A-07

The current AST guard catches only `from cerebro.models import Message`.

Exercise the boundary policy against representative forbidden forms:

- `import cerebro.models` + `cerebro.models.Message`;
- `from cerebro import models` + `models.Message`;
- a generic canonical module importing `cerebro.harness.adapters.openai_dialect`;
- a generic canonical module importing the legacy OpenAI transport.

Also assert the explicit compatibility edges remain allowed.

### TG-09 — prepare attempt identity is semantically inert

**Disposition:** currently covered by code inspection; recommended regression.

Prepare the same `InferenceRequest` twice with distinct `InferenceAttemptId`s. Assert:

- prepared attempt ids differ;
- wire payloads are identical;
- `request_semantic_hash` values are identical;
- no attempt id appears recursively in the payload.

This directly pins the intended control-metadata role of `attempt_id`.

## Existing coverage that materially helps

The reviewed suite already proves:

- provider-native and Cerebro tool-call identities stay distinct on valid fresh calls;
- replay requires provider refs and refuses to borrow a `CerebroCallId`;
- unknown wire tool names remain representable as unresolved canonical keys;
- malformed tool arguments remain truthful text rather than repaired JSON;
- normal deltas are emitted before normal completion finalization;
- stale/superseded attempt events are fenced by attempt/snapshot identity;
- basic AR-02 supersession retains audit evidence and excludes unprotected partial output;
- one explicitly protected call retains its causal prefix;
- format versions round-trip and future/missing versions fail explicitly;
- direct opaque-item repr/log projection is redacted while durable serialization preserves exact replay bytes;
- external and direct-provider adapters are structurally distinct;
- OpenAI chat/tool wire shapes are exercised at the dialect edge.

Those tests are useful but do not substitute for the adversarial cases above.

## Merge test gate

Before Phase 1A merges, P1A-01 through P1A-05 should each have at least one deterministic regression that fails on `d000ba85c316e146943a2d181da03098e0daebcd` for the concrete reason documented in `FINDINGS.md` and passes only after the narrow correction.
