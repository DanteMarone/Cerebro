# Harness v1 Recommendations After Native Provider Review

**Issue:** #204

## Decision

The Codex-derived Harness v1 architecture is fundamentally sound. Do **not** replace the `ProviderAdapter` / `ModelProfile` / `StepSnapshot` / Cerebro-owned durable history design.

However, `docs/research/codex-harness/CEREBRO_HARNESS_V1.md` should be corrected **before Phase 1 implementation** in several specific places. The current text is too casual about provider-owned state being optional optimization state and is still slightly too message-centric for Anthropic/Gemini/OpenAI reasoning flows.

The required change is narrow: make the generic protocol **ordered-item based**, distinguish **opaque required replay state** from cache hints, and make durable native call references/replay checkpoints part of the execution invariant.

## Required changes to `CEREBRO_HARNESS_V1.md`

### 1. Replace the Section 6 history sketch with ordered `InferenceItem`s

Current sketch centers `InferenceMessage` and leaves “tool calls/results can either be separate input-item variants or represented beside message items” unresolved.

Resolve it now:

```text
Instruction
  authority: system | developer
  content: list[ContentPart]
  provenance

InferenceItem =
  MessageItem(role=user|assistant, content, provenance)
  ToolCallItem(call_id, ToolKey, input, provider_ref?)
  ToolResultItem(call_id, ToolKey, status, content, provider_ref?)
  ReasoningSummaryItem(content, provenance)
  ProviderOpaqueItem(provider_id, kind, payload,
                     replay_requirement, retention_scope, sensitivity)

InferenceRequest
  model
  instructions: list[Instruction]
  history: list[InferenceItem]
  tools
  tool_policy
  reasoning_policy
  output_policy
  trace/task metadata
  provider_options?
  cache_hints?
```

Rationale: Gemini Interactions is step-oriented; OpenAI Responses is item-oriented; Anthropic thinking/tool blocks have exact order; DeepSeek reasoning replay sits in protocol history. A side metadata bag is insufficient.

### 2. Strengthen Section 6.1 from “optional provider opaque part” to explicit replay classes

The current text already says opaque state required for correctness must be durable. Keep that insight, but make it enforceable:

```text
replay_requirement:
  required_for_correctness
  fidelity_preserving
  optimization_only
```

Add retention scope and sensitivity. State that `required_for_correctness` items are ordered, durable, non-trimmable while active, adapter-owned and never interpreted by generic Harness logic.

Examples to name:

- Anthropic signed/redacted thinking during tool-use continuation;
- Gemini signed thought steps in stateless continuation;
- OpenAI encrypted reasoning/output items required for stateless reasoning/tool continuation;
- DeepSeek `reasoning_content` required in thinking + tool flows.

Explicitly say these are retained for protocol replay without exposing/reconstructing hidden chain-of-thought.

### 3. Change `provider_call_id? # opaque adapter hint, not canonical identity`

That comment is incorrect for the reviewed APIs.

Replace with a two-ID design:

```text
ToolCallItem
  call_id: CerebroCallId
  ...
  provider_ref?: ProviderCallRef

ProviderCallRef
  provider_id
  native_call_id?
  opaque?
  replay_required
```

`CerebroCallId` remains the canonical ToolRuntime/audit identity. The native ID is still provider-owned, but it must be durable when a provider requires it to correlate the result (`call_id`, `tool_use_id`, function-call ID, `tool_call_id`).

### 4. Rename generic `ReasoningDelta` to `ReasoningSummaryDelta`

The current name invites adapters to pipe provider chain-of-thought/replay content into the UI.

Use:

```text
ReasoningSummaryDelta
ReasoningSummaryItem
```

only for provider-supported summarized/visible reasoning that Cerebro policy intentionally exposes.

Any reasoning payload needed only for continuation belongs in `ProviderOpaqueItem`, even if the provider serializes it as plaintext (DeepSeek is the important case).

### 5. Make finalized output items authoritative in Section 7.1

Add:

```text
OutputItemStarted
...
OutputItemCompleted(item: InferenceItem)
```

Deltas are transient streaming UX/parser output. `OutputItemCompleted` is the durable semantic boundary.

A tool call is executable only after its completed item, provider call reference and all preceding required replay items have been durably checkpointed.

This is required because provider signatures/replay state can arrive late in a streamed block/step.

### 6. Add canonical inference completion status

`InferenceCompleted` should carry a semantic status such as:

```text
end_turn
tool_calls_pending
provider_continuation_required
max_output_reached
content_filtered_or_refused
incomplete
```

Do not equate provider stream termination with `AgentTurn` completion.

`provider_continuation_required` is needed for provider-hosted/server-tool flows such as Anthropic `pause_turn` without teaching generic Harness code the native stop reason.

### 7. Split Section 6/22 provider state into three categories

Replace the broad “provider_hints are explicitly non-durable optimization hints” framing with:

```text
provider_options
  semantic provider-specific request options
  snapshotted/durable because they can affect model behavior

cache_hints / ContinuationHandle
  optional provider-side cache/conversation fast paths
  may be lost if full replay exists

ProviderOpaqueItem / ProviderCallRef
  provider-originated replay state
  durable when required for correctness/fidelity
```

Update Section 22's rule to:

> Provider conversation/session/cache identity must not become Cerebro's source of truth. Exact provider-originated replay material may be part of Cerebro's durable inference history when the native API requires it for a valid/fidelity-preserving continuation.

For reviewed ordinary client-tool flows, OpenAI `previous_response_id`/conversation and Gemini `previous_interaction_id` remain optional because both document stateless replay paths when exact output steps/items are retained.

### 8. Add replay state to `StepSnapshot` and the pre-tool execution invariant

Add to Section 11 conceptually:

```text
canonical inference history checkpoint/version
provider replay checkpoint/version
provider semantic options/version
```

Add to Sections 17/18:

```text
stream inference
  > finalize output items
  > persist completed calls + ProviderCallRefs + required ProviderOpaqueItems
  > commit executable inference checkpoint
  > then execute ToolRuntime side effects
```

This should be a named Harness v1 invariant. It prevents a crash from producing a tool side effect without retaining the provider state required to continue afterward.

### 9. Expand `InferenceErrorKind`

Add at least:

```text
quota_or_billing
permission_denied
request_too_large
```

Keep `policy_denied` for Cerebro/provider safety-policy denial rather than provider account authorization.

Why:

- Anthropic and DeepSeek expose billing-specific 402 conditions;
- Gemini distinguishes quota from rate limits;
- Anthropic distinguishes 413 request byte size from model context exhaustion;
- 403 provider permission is not the same as Cerebro tool/policy denial.

Retain provider code/message/request ID/retry-after and make retry disposition explicit enough to separate backoff, auth refresh, compaction, fresh checkpoint attempt and terminal failure.

### 10. Enrich `ModelProfile` beyond capability booleans

Add/replace fields sufficient for request validity and planning:

```text
tool_calling_mode: unsupported | emulated | native
tool_input_forms
reasoning_control_modes
reasoning_summary_support
requires_opaque_reasoning_replay
instruction_role_fidelity
stateless_lossless_replay
model-specific parameter incompatibilities
```

Keep endpoint/API-version/unknown-field behavior in the ProviderAdapter/dialect layer.

LM Studio makes `native` vs `emulated` tool calling useful. Anthropic makes reasoning mode/tool-choice compatibility model-specific. DeepSeek proves a compatibility endpoint can accept-but-ignore fields.

### 11. Add an explicit compatibility-dialect rule to `ProviderAdapter`

State:

> “OpenAI-compatible” identifies a wire family, not a semantic capability set. An adapter must validate requested canonical semantics against known dialect + model capabilities before serialization; provider acceptance or silent ignoring is not capability negotiation.

DeepSeek's current Responses compatibility guide is the concrete example.

### 12. Update compaction rules to pin active required replay items

In Section 16, state that compaction cannot summarize, reorder or delete `ProviderOpaqueItem`s marked `required_for_correctness` while their adapter-defined replay scope is active.

After a provider closes that scope, older opaque items may be pruned according to provider/product retention policy without changing the semantic transcript.

### 13. Add provider-switch semantics

A provider/model switch must not translate opaque reasoning/signature state.

Add a rule:

```text
provider switch
  > portable semantic Cerebro history is reusable
  > old provider opaque replay state is not sent to new provider
  > if an active native continuation is unresolved, either finish it with the original provider
    or explicitly abandon it and start a fresh semantic inference step
```

This is necessary for the stated model-agnostic goal.

### 14. Strengthen Phase 1 and acceptance tests

Phase 1 should define the ordered item/replay/call-ref types immediately, even though the first implementation wraps the existing OpenAI-compatible Chat provider.

Add tests for:

- durable provider call ID linkage after worker restart;
- no tool execution before finalized/replay checkpoint;
- required opaque state pinned against compaction;
- stateless reconstruction after deleting provider continuation/cache IDs;
- compatibility adapter rejecting/degrading unsupported semantics explicitly rather than trusting ignored fields;
- provider switch only at a safe fresh semantic boundary.

Phase 6 remains the right place for the second native protocol. Gemini Interactions is the strongest item/step stress test; Anthropic Messages is the strongest signed-thinking/tool-block stress test. Either is valid, but the canonical fixtures should cover both wire shapes before declaring the contract frozen.

## Confirmations: what should *not* change

The provider review confirms these major Harness v1 decisions:

- Cerebro owns durable agent/channel/task/history identity; provider conversation IDs do not.
- `ProviderAdapter` owns auth, endpoint/wire serialization, native stream parsing, native continuation/cache mechanisms and raw error mapping.
- `ModelProfile` remains separate from provider runtime/configuration.
- `StepSnapshot` remains the core request/tool reproducibility boundary.
- Tool definitions/results remain Cerebro-native types, with provider wire names generated late.
- full raw tool result vs bounded model-facing result separation remains correct.
- generic Harness code should never branch on provider names.
- sparse durable lifecycle/checkpoint events remain preferable to persisting token-by-token text streams.
- Cerebro `ContextManager` remains the source of truth even when a provider offers cache/context-management/compaction features.
- provider-hosted tools should stay explicit extensions until Cerebro has a real cross-provider semantic reason to promote them.
- no hidden chain-of-thought should be reconstructed or surfaced merely because a provider requires opaque reasoning state to be replayed.

## Recommended exact disposition before implementation

Do **not** start Phase 1 against the current text unchanged.

Before the Phase 1 implementation PR is opened, fold the 14 corrections above into `CEREBRO_HARNESS_V1.md`, then reconcile them with the independent Goose findings from issue #203. No wholesale architecture rewrite is indicated.

The most important sentence to add to the architecture is:

> Cerebro owns semantic history, but semantic history alone is not always sufficient for provider-valid continuation: exact provider-originated replay items and native call references are durably retained when the adapter marks them required, while provider conversation IDs and cache state remain optional whenever lossless stateless replay exists.
