# Edge Cases and Losslessness

**Issue:** #204

## Core invariant

At every durable execution boundary, Cerebro must retain enough:

1. provider-neutral semantic history;
2. exact adapter-owned replay items marked required;
3. native tool-call references;
4. snapshotted request/tool policy;

to either continue the same native inference flow validly or explicitly abandon it and start a fresh semantic inference step.

A provider cache/session ID is not sufficient durable state by itself.

## 1. Do not execute a streamed tool call before the replay checkpoint is complete

The current Harness v1 proposal emphasizes exact tool execution against `StepSnapshot`, but native reasoning APIs add another precondition.

Bad sequence:

```text
stream emits enough JSON to identify a tool call
  > Cerebro executes side-effecting tool
  > process crashes
  > late provider signature/reasoning item was never durably captured
  > tool side effect exists, but provider-valid continuation cannot be reconstructed
```

This is realistic because:

- Anthropic thinking signatures can arrive near content-block completion;
- Gemini signed thought steps may precede/interleave with function calls and must be replayed exactly in stateless mode;
- OpenAI reasoning output items can be required alongside a function-call continuation;
- DeepSeek thinking + tools requires `reasoning_content` on subsequent requests.

Required ordering:

```text
provider stream
  > adapter finalizes ordered output items
  > persist OutputItemCompleted items + required ProviderOpaqueItems + ProviderCallRefs
  > mark inference checkpoint executable
  > only then dispatch ToolRuntime side effects
```

A streamed `ToolCallInputDelta` is UI/progress state, never execution authority.

## 2. Tool call identity must survive a process crash

If Cerebro executes a tool and only its internal `CerebroCallId` is durable while the provider's native call ID is not, the result may be impossible to send back correctly.

Therefore the durable call record needs both:

```text
CerebroCallId
ProviderCallRef(provider_id, native_call_id/opaque binding)
```

This does not make the native ID canonical. It makes it protocol replay state associated with a canonical call.

Losslessness test:

> Kill the worker after tool execution but before the next provider request. A new worker must be able to serialize the tool result with the exact provider-required correlation ID.

## 3. Required replay items are pinned against compaction while their scope is active

Context compaction cannot blindly summarize an active native tool/reasoning cycle.

Examples:

- Anthropic latest thinking + tool-use sequence must remain exact;
- Gemini stateless thought/function steps must remain exact;
- DeepSeek required tool-cycle `reasoning_content` must remain exact;
- OpenAI current reasoning/tool output items needed for the continuation must remain exact.

`ProviderOpaqueItem` should therefore participate in context policy with an effective property such as:

```text
trimmable = false while replay_requirement == required_for_correctness
```

After the adapter marks the replay scope closed, old opaque items can become droppable or fidelity-only according to provider rules.

Cerebro may summarize the surrounding semantic history without summarizing or modifying pinned opaque replay state.

## 4. Switching providers is a fresh semantic boundary, not opaque-state translation

Provider replay material is intentionally non-portable.

Never send:

- Anthropic signed thinking to OpenAI;
- Gemini thought signatures to DeepSeek;
- OpenAI encrypted reasoning items to Anthropic;
- DeepSeek `reasoning_content` to a different provider as if it were user-visible reasoning.

When switching provider/model families:

```text
Cerebro semantic history
  > retain portable messages/tool outcomes/task/world state

old ProviderOpaqueItems
  > retain for audit/recovery if needed
  > do not serialize to the new provider
```

If the previous provider has an **active required continuation** (for example a tool result still needs to be returned with signed reasoning state), a provider switch cannot be represented as seamless continuation. The Harness should either:

- finish/close the native continuation with the original provider; or
- mark that inference attempt interrupted/abandoned and construct a fresh new inference step from portable semantic state.

Do not attempt to translate hidden reasoning between providers.

## 5. Model switches within one provider can also invalidate replay state

Opaque reasoning/signature state may be model-family specific even when the provider is unchanged.

`ProviderOpaqueItem` needs provider-defined scope/compatibility metadata. The adapter, not the generic runner, decides whether an opaque item may be reused with a new model.

If reuse is unsupported, model switching follows the same rule as provider switching: start a fresh semantic inference boundary rather than trying to reinterpret the opaque block.

## 6. Stateful continuation handles can expire or disappear

OpenAI response/conversation IDs, Gemini interaction IDs and LM Studio response IDs are useful fast paths but can be lost through:

- provider retention windows;
- server restart/local process restart;
- region/account migration;
- worker state loss;
- deliberate `store: false` / privacy configuration.

Acceptance test for adapters claiming stateless recoverability:

1. complete a model step with tools/reasoning;
2. persist canonical + required opaque items;
3. discard all provider continuation/cache IDs and HTTP client state;
4. reconstruct the next request from Cerebro durable state;
5. provider accepts it and the semantic tool/result flow continues.

This should be a fixture-level adapter test for OpenAI and Gemini.

## 7. Provider-side cache state must never be the only copy of prompt material

Prompt caches can expire or miss without warning.

Cerebro must retain or be able to reconstruct the source content represented by:

- OpenAI prompt-cache breakpoints/keys;
- Anthropic cache-control prefixes;
- Gemini implicit/legacy explicit cached content;
- DeepSeek automatic context cache;
- local KV/session caches.

Cache configuration may be snapshotted because it affects cost/performance policy. Cache contents/handles are dispensable unless a future provider explicitly documents otherwise.

## 8. Provider-side context editing/compaction is derived state

If a provider removes old tool results/thinking from its prompt or returns a compaction artifact, Cerebro should not erase the original durable semantic history merely to mirror that provider representation.

Store:

```text
canonical history/checkpoint
provider context-management configuration
optional provider compaction/replay artifact if required
```

This preserves the ability to:

- switch providers;
- audit prior tool outcomes;
- rebuild context under a different model budget;
- recover when provider-side state expires.

Provider context management may be a useful execution strategy, but Cerebro `ContextManager` remains the durable owner.

## 9. Parallel tool calls need stable per-call association, not array position

Streaming protocols can index call fragments, but final history must identify calls by stable canonical/native IDs.

Do not make stream array index the durable call identity. It is parser state only.

For N parallel calls:

- produce N finalized `ToolCallItem`s;
- persist each native `ProviderCallRef`;
- execute each once according to snapshotted parallel-safety/policy;
- produce exactly one terminal canonical `ToolResultItem` per admitted call;
- let the adapter serialize provider-required result grouping/order.

Anthropic's “all tool results together” wire requirement should not leak into ToolRuntime scheduling. Gemini/OpenAI parallel-array/event shape should not become canonical either.

## 10. Partial tool arguments are not valid canonical input

OpenAI, Anthropic, Gemini/compatibility APIs can stream tool arguments incrementally.

`ToolCallInputDelta` may carry an opaque text fragment for UI/debugging, but executable canonical input exists only after adapter completion/validation:

```text
partial wire fragments
  > adapter parser
  > finalized JSON/text ToolInput
  > OutputItemCompleted(ToolCallItem)
  > schema validation in ToolRuntime
```

Malformed/incomplete JSON before stream end is a provider inference failure, not a ToolRuntime call with guessed arguments.

## 11. Provider-hosted tools create retry barriers

A provider-hosted web/code/MCP/computer tool can execute inside an inference request without Cerebro `ToolRuntime` owning the side effect.

If the stream disconnects after a provider-hosted operation may have run, automatic request replay may duplicate work or side effects.

For Harness v1:

- provider-hosted tools remain explicit provider extensions;
- adapters should surface enough metadata to mark that semantic/provider-managed progress occurred;
- recovery policy should not blindly replay an entire inference after such progress;
- client-side Cerebro tools remain preferred where exactly-once/auditable execution matters.

If a provider offers idempotency/request keys, those can be adapter-owned replay aids but do not remove the need for a durable retry barrier.

## 12. A stream can fail after HTTP success

Anthropic and Gemini explicitly document SSE error events; OpenAI/DeepSeek Responses streams also have failure/incomplete terminal semantics.

Adapter responsibilities:

- parse stream-level errors into `InferenceFailed`;
- retain already finalized items/checkpoints;
- report provider request IDs/codes where available;
- avoid converting an early HTTP 200 into unconditional success.

Harness responsibilities:

- decide whether any semantic output was committed;
- decide whether a same-request replay is safe;
- preserve already executed tool side effects/results;
- create a fresh inference attempt if necessary.

## 13. `incomplete` / max-output is not ordinary completion

Provider finish reasons differ. A normalized status should distinguish:

```text
end_turn
tool_calls_pending
provider_continuation_required
max_output_reached
content_filtered_or_refused
incomplete
```

The `CompletionPolicy` should not interpret “stream ended” as “assistant successfully completed the task.”

A max-output stop may need continuation/feedback; a refusal may be terminal or policy-handled; provider pause may need an adapter continuation.

## 14. Provider error classes must not erase billing vs rate limits

Concrete provider APIs distinguish states with very different recovery:

- Anthropic 402 billing vs 429 rate/spend variants;
- DeepSeek 402 insufficient balance vs 429 rate limit;
- Gemini `rate_limit_exceeded` vs `quota_exceeded`;
- provider 403 permission vs Cerebro's own `policy_denied`.

Therefore add `quota_or_billing` and `permission_denied` to canonical errors.

A 429 is not automatically retryable if it represents a spend/quota condition with no near-term reset. Preserve provider code/retry-after and let recovery policy decide.

## 15. Byte-size limits and model context limits are different failures

Anthropic explicitly has a request-byte-size 413 independently of context-window constraints. Other providers can also reject context based on model tokens or payload/media size.

Normalize separately when possible:

```text
request_too_large   # HTTP/payload/file/body size
context_exhausted   # model usable context/token budget
```

Only the latter should trigger normal context compaction automatically.

## 16. “Accepted parameter” does not prove support

DeepSeek explicitly documents silently ignored Responses fields. Local OpenAI-compatible servers may similarly accept fields they do not meaningfully honor.

Adapter rule:

> Validate requested canonical semantics before serialization using known dialect/model capabilities. Do not use request success as feature negotiation.

If degradation is allowed, record it in the immutable `StepSnapshot`/provider preparation metadata so the run is explainable.

## 17. Native vs emulated tool calls should not change canonical ToolRuntime semantics

LM Studio can parse model text into OpenAI-compatible tool-call objects even for models without native tool training/templates.

Canonical `ToolCallItem` remains the same after the adapter has validated a call. But `ModelProfile.tool_calling_mode` should record `native` vs `emulated` because it affects planning/reliability, especially for destructive tools or strict structured arguments.

The Harness can later apply policy (for example disallow destructive direct tools for emulated calling) without changing the provider wire contract.

## 18. Required replay state needs explicit sensitive-data handling

Some correctness state contains provider-encrypted reasoning; DeepSeek may require plaintext `reasoning_content`. Retaining it durably has privacy/security implications even though Cerebro must not display it.

Minimum design requirements before implementation:

- mark replay-item sensitivity;
- exclude hidden reasoning payloads from normal logs/Hub events/UI;
- do not include them in user-facing transcript exports by default;
- preserve exact bytes/JSON needed for provider replay;
- apply normal at-rest retention/access controls appropriate to durable inference state;
- permit adapter-defined deletion after the replay scope is safely closed if product retention policy allows.

This is storage of provider-returned protocol state, not reconstruction of hidden chain-of-thought.

## 19. Losslessness acceptance suite

Before declaring Phase 1/6 provider-neutral, build deterministic adapter fixtures for at least:

1. text-only response;
2. one client tool call/result;
3. parallel tool calls;
4. streamed partial arguments with final completed call;
5. required opaque reasoning/signature replay;
6. crash after finalized call checkpoint, before tool execution;
7. crash after tool execution, before result is sent back;
8. continuation after deleting provider conversation/cache IDs;
9. context compaction while a required replay item is pinned;
10. stream error after some output items completed;
11. unsupported canonical capability on a silently-ignoring compatibility endpoint;
12. provider/model switch at a safe fresh inference boundary.

The runner should be identical across adapters. Only fixtures/adapters/profiles should change.
