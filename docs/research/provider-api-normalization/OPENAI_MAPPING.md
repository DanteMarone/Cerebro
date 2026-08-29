# OpenAI Responses Mapping

**Baseline:** OpenAI Responses API documentation accessed 2026-08-29. See `API_BASELINES.md`.

## Bottom line

OpenAI Responses maps cleanly to the proposed Cerebro adapter boundary if Cerebro models **ordered inference items** rather than treating Responses items as the generic contract.

`previous_response_id`, Conversations, prompt-cache keys and transport state can remain adapter-owned conveniences because OpenAI documents manual stateless history replay. The important exception is provider-originated output state — especially reasoning items and function-call IDs — that must be preserved when Cerebro chooses stateless continuation.

## Request mapping

| Cerebro semantic | Responses mapping | Notes |
| --- | --- | --- |
| `ModelRef.model_id` | `model` | Provider namespace remains Cerebro-owned. |
| `Instruction(system/developer)` | `instructions` or input instruction items | Exact role serialization is adapter-owned. Instructions are not automatically carried forward by `previous_response_id`. |
| `MessageItem` | message/input item | Text/image/file inputs are native. |
| `ToolDefinition` | function tool | V1 should use client JSON-function tools. Built-in/server tools remain provider extensions. |
| `ToolPolicy` | `tool_choice`, `parallel_tool_calls`, limits | Capability/parameter availability is model-specific. |
| `ToolCallItem` | `function_call` output item | Preserve provider `call_id` in `ProviderCallRef`. |
| `ToolResultItem` | `function_call_output` input item | Must serialize the native `call_id`. |
| `ReasoningPolicy` | `reasoning` controls | Effort/summary/context options are model-specific. |
| `ReasoningSummaryItem` | reasoning summary output where requested/supported | Never equate this with hidden reasoning. |
| `ProviderOpaqueItem` | encrypted/persisted reasoning item or other exact output item needed for replay | Generic Harness stores/order-preserves; OpenAI adapter interprets. |
| `OutputPolicy` | `text.format`, output controls | Structured output is native. |
| `provider_options` | hosted tools, background, context management, programmatic tools, etc. | Semantic/provider-specific extension, not generic core by default. |
| `cache_hints` | `prompt_cache_key`, `prompt_cache_options` | Optimization/cost controls. |

## History and continuation

OpenAI exposes three useful ways to carry conversation state:

1. explicit input/history items;
2. `previous_response_id`;
3. a server-side `conversation` resource.

For Cerebro, (2) and (3) are optional adapter continuation handles. They must not replace canonical durable history because:

- Responses supports `store: false` / stateless operation;
- current guidance for manual history says to preserve previous user inputs and every response output item;
- instructions are interaction-scoped and are not implicitly inherited through `previous_response_id`;
- Cerebro needs recovery independent of provider retention/lifetime.

A provider response ID can be checkpointed as a fast-path hint. If lost, the OpenAI adapter should be able to serialize the retained full item history instead.

## Reasoning state

This is the critical non-message case.

For current reasoning models, OpenAI returns reasoning as separate output items. In stateless/ZDR flows, encrypted reasoning state can be returned/replayed without exposing raw chain-of-thought. Current model guidance says that when managing history manually, applications should preserve and resend every response output item; with function calling, reasoning items associated with the tool-producing response must accompany the tool continuation.

Cerebro mapping:

```text
OpenAI reasoning output item
  if provider-supported summary intended for display
    > ReasoningSummaryItem

  exact encrypted/non-display replay material
    > ProviderOpaqueItem(
         provider_id="openai",
         kind="reasoning_replay",
         replay_requirement=required_for_correctness or fidelity_preserving,
         sensitivity=signature_or_encrypted_reasoning
      )
```

Do not parse encrypted reasoning. Do not map opaque reasoning material to `ReasoningDelta`/UI text.

For conservative recovery, reasoning items inside an active reasoning/tool continuation should be treated as required replay state. Older reasoning outside the active provider-defined scope may be droppable when the model/API says it is no longer needed.

## Tool calls

Responses distinguishes an item's own item ID from the function `call_id` used to correlate the result. The latter is protocol-significant.

Cerebro should generate its own `CerebroCallId`, while retaining:

```text
ProviderCallRef(
  provider_id="openai",
  native_call_id=<Responses call_id>,
  replay_required=true
)
```

The tool result references the Cerebro call internally. At serialization, the adapter resolves the `ProviderCallRef` and emits the native function-call-output linkage.

This also prevents provider IDs from becoming global ToolRuntime identities.

Parallel function calls are naturally represented as multiple ordered `ToolCallItem`s produced by one inference. Tool execution scheduling remains Cerebro-owned.

## Streaming mapping

Responses already exposes a good event decomposition: response lifecycle, output-item lifecycle, content deltas, tool argument deltas, item completion and final response.

Recommended adapter behavior:

```text
response.created/in_progress
  > InferenceStarted / ProviderMetadata

text/content deltas
  > AssistantTextDelta

reasoning summary deltas
  > ReasoningSummaryDelta

function argument deltas
  > ToolCallInputDelta

response.output_item.done
  > OutputItemCompleted(canonical item)

response.completed
  > InferenceCompleted

response.failed / stream error
  > InferenceFailed(mapped InferenceError)
```

The adapter should execute no tool from partial argument deltas. `OutputItemCompleted(ToolCallItem)` is the authoritative executable record.

## Hosted tools and newer Responses item types

Responses supports a broad provider-native tool/item union: web search, file search, computer use, code interpreter, programmatic tool calling and other provider-managed flows.

Do not make every one a core `ToolCallItem`. The distinction is:

- **Cerebro client tool:** model asks Cerebro to execute a snapshotted `ToolKey` > canonical `ToolCallItem` / `ToolResultItem`.
- **provider-hosted tool:** provider executes/coordinates it > provider extension/item unless and until Cerebro needs portable semantics for that class.

The generic runner may still need a semantic completion status such as `provider_continuation_required` for provider-managed flows. It should not know OpenAI hosted-tool type names.

Programmatic Tool Calling is especially useful as a guardrail for the abstraction: it introduces `program`/caller linkage that should remain an OpenAI extension rather than forcing all providers into that shape.

## Caching

`prompt_cache_key`, implicit/explicit cache breakpoints, retention/TTL and cache token counters are optimization/cost metadata.

Classification:

```text
prompt cache configuration      semantic request optimization setting
cache hit/write token usage    canonical usage metadata where useful
cache storage/entry identity   optimization only
```

Loss of cache state must not make a turn unrecoverable.

## Context management and compaction

Responses now exposes provider context-management/compaction features. Cerebro can optionally use them through `provider_options`, but the authoritative compacted state should remain a Cerebro `ContextManager` checkpoint unless the product deliberately adopts a provider-specific mode.

A provider-generated compaction artifact may be retained opaquely if needed for exact continuation, but it should not silently replace Cerebro's full durable history/audit source.

## Error mapping

Provider/transport errors should map into the canonical taxonomy by semantic cause rather than HTTP code alone:

- auth failures > `authentication`;
- access/authorization > `permission_denied`;
- 429 or explicit rate-limit > `rate_limited` unless provider code distinguishes exhausted quota;
- invalid input/schema > `invalid_request`;
- input/context limit > `context_exhausted` or `request_too_large` as appropriate;
- provider 5xx/availability > `provider_internal` / `provider_overloaded` / `transient_transport`;
- unsupported model/field combination > `unsupported` where confidently identifiable.

A stream failure after output has been observed must not be blindly retried just because the underlying HTTP failure is transient. The Harness decides retry safety from the durable inference attempt state.

## ModelProfile implications

OpenAI model profiles should describe, rather than infer from model-name prefixes:

- input/output modalities;
- max context/output;
- function tools and parallel calls;
- structured output;
- reasoning mode/effort/summary support;
- stateless reasoning replay support;
- hosted-tool capabilities;
- any sampling/reasoning parameter incompatibilities.

## State classification

### Required or fidelity-critical replay state

- function `call_id` until the matching output/continuation is complete;
- exact reasoning/output items required by stateless reasoning/tool continuation;
- any provider item explicitly documented as required to continue a chosen Responses feature.

### Optional continuation/performance state

- `previous_response_id` when Cerebro retains lossless full item history;
- `conversation` ID when Cerebro retains lossless full item history;
- prompt-cache keys/entries;
- connection/WebSocket/session state;
- request IDs used only for diagnostics.

## Harness v1 pressure-test result

OpenAI confirms the proposed ProviderAdapter boundary but supports three corrections to the original type sketch:

1. history must be ordered items, not just `InferenceMessage` rows;
2. provider call IDs can be durable correctness state, not merely hints;
3. reasoning replay material must be separated from visible reasoning summaries.
