# Phase 1A findings

Reviewed implementation: `d000ba85c316e146943a2d181da03098e0daebcd`

Contract: `design/harness-v1-contract-clarifications@05fb8fa09c47598bbeed16c9be279f5dfe2a648b`

Only high-confidence defects and material follow-ups are recorded here.

## P1A-01 — `MUST_FIX` — cancellation finalizes partial provider deltas

**File / symbol**

`cerebro/harness/adapters/openai_compatible.py::OpenAICompatibleAdapter.stream`

**Concrete failure sequence**

1. The adapter receives `TextDelta("Hel")`, or tool fragments such as `{"path":`.
2. Those fragments are accumulated in `text_parts` / `calls` and emitted only as non-authoritative delta events.
3. `cancel_token.cancelled` becomes true.
4. On the next transport delta, the loop executes `break`.
5. Execution continues into the normal finalization block.
6. Accumulated text becomes a provider-originated `MessageItem` inside `OutputItemCompleted`; accumulated tool fragments become `ToolCallItem`s via `_finalize_call()`; `ProviderMetadata` and a normal `InferenceCompleted` are emitted.

For a partial tool call, `_finalize_call()` may additionally turn truncated JSON into a finalized `TextToolInput`, converting an interrupted fragment into semantic authority.

**Violated contract**

`PHASE_1_CONTRACT.md` §10: `OutputItemCompleted` is authoritative and no delta may enter durable semantic history, authorize a tool or satisfy completion policy. Cancellation must not promote an incomplete delta stream into completed semantic output.

**Smallest correction**

When cancellation is observed, terminate the adapter stream without running normal item/completion finalization. Do not emit `OutputItemCompleted` or normal `InferenceCompleted` from accumulated fragments. The caller/attempt state machine should record cancellation/abandonment separately. Ensure the underlying async stream is closed promptly on this path.

**Deterministic test required**

Two tests:

- cancel after the first of two text deltas; assert the first `AssistantTextDelta` may have been observed, but zero `OutputItemCompleted` and zero normal `InferenceCompleted` follow cancellation;
- cancel after the first fragment of tool JSON; assert zero finalized `ToolCallItem`, even if the fragment is syntactically valid or becomes representable as text.

**Merge disposition**

Fix before merge.

---

## P1A-02 — `MUST_FIX` — `InferenceAttempt` accepts impossible persisted combinations

**File / symbol**

`cerebro/harness/attempts.py::InferenceAttempt._consistent_terminal_state`

**Concrete failure sequences / states**

The transition methods normally produce sensible states, but model construction/deserialization accepts combinations the state machine can never legitimately reach, including:

- `dispatch_state="admitted"`, `dispatch_barrier_committed=True`, `semantic_state="active"`: recovery reads `may_have_reached_provider=True`, but the persisted dispatch enum still says admitted/undispatched;
- `dispatch_state="terminal"`, `semantic_state="active"`: the dispatch half is terminal while semantic work is still active;
- `semantic_state="completed"`, `completion_status="end_turn"`, `dispatch_state="terminal"`, `dispatch_barrier_committed=False`: a completed provider attempt represented as definitely pre-dispatch;
- terminal semantic states such as `failed` / `abandoned` with non-terminal `dispatch_state` supplied through deserialization.

The validator currently rejects only `dispatch_may_have_escaped` without the barrier and `cancelled_before_dispatch` with the barrier. `load_attempt()` therefore accepts other impossible known-version states.

Failures before and after the barrier are otherwise representable correctly by the transition API: `mark_failed()` can terminate with the barrier false or true, preserving the distinction. Monotonic transition methods also refuse a second semantic terminal transition.

**Violated contract**

`PHASE_1_CONTRACT.md` §11 dispatch barrier semantics: once the barrier commits, the attempt must never be representable as definitely undispatched; completion cannot occur without the barrier; persisted state must preserve conservative recovery truth.

**Smallest correction**

Make the model validator enforce the complete stable-state matrix, not only two pairwise checks. At minimum:

- `admitted` implies barrier false and semantic state active;
- `dispatch_may_have_escaped` implies barrier true and semantic state active;
- semantic terminal implies `dispatch_state="terminal"`;
- `dispatch_state="terminal"` implies semantic terminal;
- `completed` implies barrier true;
- `cancelled_before_dispatch` implies barrier false;
- `failed` and `abandoned` may be terminal with either barrier value so pre/post-barrier failure remains distinguishable.

**Deterministic test required**

Table-drive `InferenceAttempt.model_validate()` and `load_attempt()` across the valid and invalid stable combinations, including failure/abandonment on both sides of the barrier. Also keep transition tests proving the methods land only in valid combinations and never move backwards.

**Merge disposition**

Fix before merge.

---

## P1A-03 — `MUST_FIX` — AR-02 can leave an orphan committed tool result

**File / symbol**

`cerebro/harness/history.py::InferenceHistory.supersede_abandoned_attempt`

**Concrete failure sequence**

1. Attempt A finalizes a provider `ToolCallItem`.
2. Cerebro commits a harness-local `ToolResultItem` for that call (for example success, error, denied or another terminal result).
3. Attempt A is later abandoned without authoritative `InferenceCompleted`.
4. The caller invokes `supersede_abandoned_attempt()` without that call id in `protected_call_ids` (or with an incomplete protection set).
5. The method supersedes the provider-originated `ToolCallItem` because only provider-attempt items participate in `positions`.
6. The harness-local `ToolResultItem` is never considered for supersession and remains in `canonical_request_history()`.
7. Future replay can therefore contain a tool result whose causal assistant tool call has been removed. In the OpenAI dialect this can become a standalone `role="tool"` record, or fail depending on whether the result retained its provider ref.

The current test `test_committed_tool_results_are_never_superseded` proves the result remains, but does not assert that its causal tool call must also remain.

The multiple-call boundary logic is otherwise directionally correct: with a correct protected set it retains the prefix through the last protected call and supersedes only later attempt-originated output; unrelated conversation items are not touched.

**Violated contract**

Clarified AR-02 / `PHASE_1_CONTRACT.md` §32.2: committed/possibly escaped effect history is monotonic; the smallest ordered causal prefix needed for the effect and committed result must remain active. Supersession may not create semantically orphaned evidence.

**Smallest correction**

Make committed tool results fail-closed protection evidence rather than relying solely on caller discipline. Before choosing the supersession boundary, derive/protect the call ids of active `ToolResultItem`s that belong to calls from the abandoned attempt, then union those with caller-supplied ids for unresolved `dispatch_may_have_escaped` calls that have no result yet. Alternatively validate that every active result's originating call remains active and reject supersession if the supplied protection set would orphan it.

The method should still accept explicit protected ids because an escaped unresolved call may have no `ToolResultItem` yet.

**Deterministic test required**

Construct one attempt with two tool calls and results, then exercise at least:

- first call protected/committed, second unprotected: prefix through first survives; second/trailing output supersedes;
- second call protected/committed: causal prefix through second survives;
- committed result present but caller omits the call id: method must preserve the causal call automatically or fail closed;
- unrelated projected/conversation items interleaved around the attempt remain untouched.

Assert every active `ToolResultItem` has its causal active `ToolCallItem` after supersession.

**Merge disposition**

Fix before merge.

---

## P1A-04 — `MUST_FIX` — external cancellation works only through an out-of-contract `track()` call

**Files / symbols**

- `cerebro/harness/external_agent.py::ExternalAgentAdapter.start_or_resume`
- `cerebro/harness/adapters/cli_external.py::CliExternalAgentAdapter.start_or_resume`
- `cerebro/harness/adapters/cli_external.py::CliExternalAgentAdapter.stream_events`
- `cerebro/harness/adapters/cli_external.py::CliExternalAgentAdapter.cancel`
- `cerebro/harness/adapters/cli_external.py::CliExternalAgentAdapter.track`

**Concrete failure sequence**

1. A caller follows the protocol surface: `handle = await start_or_resume(request)`.
2. The caller drives `stream_events(handle)` in a task.
3. No protocol method requires or even exposes `track()`; it is a concrete-adapter extra.
4. `cancel(execution_id)` looks only in `_live`, which remains empty.
5. Cancellation returns successfully but does not cancel the task driving `CliAgentProvider.stream()` and therefore does not reach the provider's subprocess-kill-on-`CancelledError` behavior.

The existing cancellation test passes only because the test manually calls `adapter.track(...)`.

There is a second direct contract mismatch: the clarified external-agent contract specifies `start_or_resume(ExternalExecutionRequest, cancel_token)`, but the protocol and implementation omit the cancel token entirely.

Structural separation from `ProviderAdapter` is otherwise correct and restart recovery is honestly deferred.

**Violated contract**

`PHASE_1_CONTRACT.md` §9 external-agent contract and the Phase 1 requirement to preserve explicit CLI cancellation cleanup. The public adapter lifecycle must make cancellation ownership explicit and usable without an undocumented extra method.

**Smallest correction**

Make the normal protocol lifecycle own/record the task that `cancel(execution_id)` must reach, rather than requiring callers to know `track()`. One narrow option is for `stream_events()` to register its current driving task for the execution id on entry and remove it in `finally`. Restore the clarified `cancel_token` parameter on `start_or_resume()` and carry/observe it consistently. Remove `track()` from the required usage path (it may disappear entirely if no longer needed).

Do not add restart recovery.

**Deterministic test required**

Drive a hanging fake CLI stream using only protocol methods, never call `track()`, invoke `cancel(execution_id)`, and assert the driving task receives `CancelledError` and the underlying CLI cleanup path runs. Also assert a pre-cancelled/triggered `CancelToken` is honored according to the restored contract.

**Merge disposition**

Fix before merge.

---

## P1A-05 — `MUST_FIX` — sensitive opaque payload leaks through validation errors

**Files / symbols**

- `cerebro/harness/items.py::_ItemEnvelope` / `ProviderOpaqueItem`
- `cerebro/harness/serialization.py::_ITEM_ADAPTER`
- `cerebro/harness/serialization.py::load_item`
- nested request/event validation paths that can accept an opaque item

**Concrete failure sequence**

1. A sensitive `ProviderOpaqueItem` payload is supplied for validation with an invalid field or invalid envelope combination, e.g. `origin="harness_local"` plus `exact_payload="secret"`.
2. Pydantic raises `ValidationError`.
3. Default Pydantic error rendering includes `input_value=...` and can include all or part of `exact_payload`.
4. `load_item()` exposes the `TypeAdapter` validation error directly, so ordinary exception logging can persist the replay secret.

Direct `repr`, `str`, `log_projection()` and normal logging of a valid item are redacted correctly. Durable `dump_item()` intentionally keeps the exact payload. The leak is specifically generic error/validation observability, which the current tests do not exercise.

**Violated contract**

Clarified AR-12 and the Phase 1 opaque replay rules: hidden/signature/secret-like replay state is excluded from normal log/UI/observability surfaces. Validation failure is not durable serialization and must not disclose `exact_payload`.

**Smallest correction**

Configure validation paths that can receive opaque items to hide input values in errors. `ProviderOpaqueItem` / its envelope should use `hide_input_in_errors`, and the discriminated `_ITEM_ADAPTER` must also be created with `config={"hide_input_in_errors": True}` because a union `TypeAdapter` otherwise reintroduces the raw input. Apply the same protection to request/event validation surfaces that can nest `ProviderOpaqueItem`, or wrap those loaders so their raised errors contain only safe metadata.

**Deterministic test required**

Use a short unmistakable sentinel payload and force validation failures through:

- direct `ProviderOpaqueItem` construction;
- `load_item()` / discriminated union validation;
- at least one nested request or event validation path containing an invalid opaque item.

Assert the sentinel is absent from `str(exc)`, `repr(exc)`, formatted traceback/log output, and any chained replacement error.

**Merge disposition**

Fix before merge.

---

## P1A-06 — `FOLLOW_UP` — legacy missing call-id fallback can masquerade as provider-owned identity

**Files / symbols**

- `cerebro/providers/openai_compatible.py::OpenAICompatibleProvider.stream_payload`
- `cerebro/harness/adapters/openai_compatible.py::OpenAICompatibleAdapter._finalize_call`

**Concrete sequence**

The transport preserves existing runtime behavior by emitting `ToolCallDelta.id = call_id or f"call_{index}"`. If a non-conforming server omits the provider-native tool-call id, the Harness adapter receives the synthetic fallback and stores it as `ProviderCallRef.native_call_id` with `replay_required=True`. The canonical layer can no longer tell that the id was invented locally rather than issued by the provider.

For conforming responses the identity mapping is correct, and changing the existing runtime fallback in this PR would be unnecessary scope expansion. The risk appears only when the new Harness adapter is activated against malformed responses.

**Contract ambiguity/risk**

`ProviderCallRef` is explicitly provider-owned correlation/replay state. A locally synthesized fallback must not silently become proof of a provider-issued replay handle.

**Smallest correction**

Before Harness adapter activation, preserve missing-id provenance across the transport boundary (for example an explicit synthetic/missing flag) and have the canonical adapter fail closed or represent it separately instead of calling it `native_call_id`.

**Deterministic test required**

Feed the real transport an SSE tool-call delta with no `id`, then run it through the Harness adapter. Assert the result does not claim a provider-native `ProviderCallRef` unless the provider actually supplied the id.

**Merge disposition**

Safe to merge Phase 1A after the MUST_FIX findings because the Harness adapter is not selected by production yet; gate this before provider-selection/cutover.

---

## P1A-07 — `FOLLOW_UP` — import-boundary guard is too syntax-specific

**File / symbol**

`tests/test_harness_contracts.py::test_no_generic_harness_module_reads_collaboration_messages`

**Concrete weakness**

The AST test detects only:

`from cerebro.models import Message`

outside two allowed filenames. It does not catch equivalent reverse dependencies such as:

- `import cerebro.models` followed by `cerebro.models.Message`;
- `from cerebro import models` followed by `models.Message`;
- generic use of `Message.meta_json` through an indirect import/helper;
- imports from an OpenAI dialect/transport module into generic canonical modules.

The current implementation is clean: the actual `Message` imports are confined to `projection.py` and `adapters/cli_external.py`, and OpenAI wire shapes are in adapter/transport modules. This is therefore guard weakness, not present boundary contamination.

**Smallest correction**

Strengthen the architectural test to enforce allowed dependency directions/modules rather than one exact import statement. At minimum detect module imports/aliases and forbid generic modules from importing compatibility/adapters/current provider transport. A lightweight import graph or a small AST policy table is sufficient; no production change is needed.

**Deterministic test required**

Test the guard/policy against representative forbidden syntaxes (`import cerebro.models`, aliased module import, generic import from `cerebro.harness.adapters.openai_dialect`) and allowed explicit edges.

**Merge disposition**

Follow-up; current source is boundary-clean.

---

## `FALSE_POSITIVE / COVERED` checks

### OpenAI-specific wire shapes in canonical models

Covered. Chat roles, `tool_calls`, `tool_call_id`, wire tool names and finish reasons stay in the OpenAI adapter/dialect or pre-existing transport. Canonical `ToolKey`, items, requests and events are provider-neutral.

### Provider call identity for valid fresh and replayed calls

Covered. Fresh valid native ids become `ProviderCallRef`; Cerebro mints independent `CerebroCallId`. Replay rendering requires provider refs and refuses to substitute the Cerebro id.

### `attempt_id` affects model semantics/hash

Covered. `attempt_id` is on `PreparedProviderRequest`, not `InferenceRequest`; it is absent from the wire payload and from `request_semantic_hash()` input.

### Unknown format versions / silent variant coercion

Covered. Persisted canonical families fail explicitly on missing/future versions; the inference-item union is discriminated by `item_type`.

### Existing OpenAI transport extraction changes current runtime behavior

Covered. `stream()` constructs the same payload and delegates to the extracted parser; `ProviderError.status_code` is additive and does not alter the existing message text.

### Scope/cutover creep

Covered. No SQL/store/recovery-driver/reducer/provider-selection/new-SDK/external-paid-agent work exists in the exact compare; `AgentRuntime` stays active.

### Listed whitespace edits

Covered. Exact compare hunks show EOF blank-line deletion only.
