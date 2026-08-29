# Anthropic Messages Mapping

**Baseline:** Anthropic Messages/tool use/thinking/caching/context documentation accessed 2026-08-29. See `API_BASELINES.md`.

## Bottom line

Anthropic is the strongest evidence that Cerebro cannot normalize history into only text messages plus tool calls. An assistant response can contain ordered thinking/redacted-thinking, text and tool-use blocks; during a thinking + tool-use cycle, the thinking sequence is authenticated provider replay state and must be returned unchanged.

The generic Harness should preserve that state opaquely and in order without treating it as visible chain-of-thought.

## Request mapping

| Cerebro semantic | Anthropic mapping | Notes |
| --- | --- | --- |
| `ModelRef.model_id` | `model` | Model profile owns thinking/tool restrictions. |
| `Instruction` | system/instruction surface | Adapter maps authority according to current API/model support. |
| `MessageItem(user/assistant)` | Messages `messages` entry with content blocks | Tool blocks are handled separately in canonical history. |
| `ToolDefinition` | client tool definition | JSON-schema client tools map well. |
| `ToolCallItem` | `tool_use` block | Native `id` becomes durable `ProviderCallRef`. |
| `ToolResultItem` | `tool_result` block in the required user-message structure | Adapter owns wire grouping/order rules. |
| `ReasoningSummaryItem` | summarized thinking, if requested/supported and Cerebro policy exposes it | Not the replay representation. |
| `ProviderOpaqueItem` | exact thinking/redacted-thinking block/signature | Required inside active tool-thinking cycle. |
| `provider_options` | server tools, context editing, beta/provider-specific controls | Keep outside generic ToolRuntime unless deliberately promoted. |
| `cache_hints` | cache-control/breakpoint/TTL policy | Optimization/cost only. |

## Tool-call IDs and result ordering

A client `tool_use` block has a provider-issued ID. Its `tool_result` references that ID. Parallel tool use can produce several `tool_use` blocks in one assistant response, and Anthropic's client-tool guidance requires results to be returned in the protocol-prescribed content layout.

Cerebro should not make the Anthropic ID its global tool identity. Store:

```text
ToolCallItem.call_id = CerebroCallId
ToolCallItem.provider_ref = ProviderCallRef(
  provider_id="anthropic",
  native_call_id=<tool_use id>,
  replay_required=true
)
```

The adapter is responsible for grouping canonical `ToolResultItem`s into the native user-message/content-block arrangement and preserving ordering constraints. The generic ToolRuntime only needs the Cerebro ID and snapshotted `ToolKey`.

## Thinking is both display content and protocol state — model them separately

Current Anthropic thinking supports provider-controlled visibility such as summarized or omitted output. Thinking blocks also carry opaque signatures. During tool use, Anthropic requires every relevant thinking/redacted-thinking block from the latest assistant turn to be passed back complete, unmodified and in the original sequence; modified blocks can produce `400 invalid_request_error`.

Therefore one canonical `ReasoningDelta(text)` is unsafe.

Recommended mapping:

```text
provider-supported summarized thinking intended for display
  > ReasoningSummaryDelta / ReasoningSummaryItem

exact thinking block + signature needed for replay
  > ProviderOpaqueItem(
       provider_id="anthropic",
       kind="thinking_block",
       replay_requirement=required_for_correctness,
       retention_scope=current_tool_cycle,
       sensitivity=hidden_reasoning or signature_or_encrypted_reasoning
     )

redacted_thinking
  > ProviderOpaqueItem(... exact opaque data ...)
```

The adapter may derive both a summary item and an opaque replay item from one provider block. The generic runner must never attempt to reconstruct omitted/full thinking from the summary/signature.

Outside a tool-use cycle, Anthropic documents more flexible/model-dependent thinking retention. The adapter can downgrade older blocks to `fidelity_preserving` or omit them when current provider rules say they are no longer required.

## Streaming

Anthropic SSE is block-oriented:

```text
message_start
content_block_start
content_block_delta*
content_block_stop
message_delta
message_stop
```

Tool input can arrive via incremental JSON fragments. Thinking and signature material have distinct deltas, with signature data arriving late in the block lifecycle.

Cerebro adapter mapping:

```text
message_start
  > InferenceStarted

text_delta
  > AssistantTextDelta

summarized thinking delta, if displayable
  > ReasoningSummaryDelta

input_json_delta
  > ToolCallInputDelta

content_block_stop
  > OutputItemCompleted(final canonical item)

message_delta/message_stop
  > usage/finish mapping + InferenceCompleted

SSE error event
  > InferenceFailed
```

The finalized content block is authoritative. This matters because an opaque signature needed for future replay may not exist until the end of a streamed block.

Adapters must accept unknown/new provider event types defensively rather than crashing the generic runner solely because Anthropic adds an event.

## Server tools and `pause_turn`

Anthropic provider/server tools are materially different from Cerebro client tools. The provider can execute them internally and can return `pause_turn`, with documentation instructing the client to continue by passing the paused response back unchanged.

Do not fabricate a Cerebro `ToolCallItem` for a provider-hosted tool unless Cerebro actually owns execution.

Instead:

- retain exact provider continuation material as opaque ordered items as required;
- map the stop condition to `provider_continuation_required`;
- let the Anthropic adapter perform the next native continuation request under Harness control/budgets/cancellation.

This gives the generic runner one portable semantic fact — “provider continuation is required” — without teaching it Anthropic server-tool wire types.

## Prompt caching

Anthropic prompt caching uses cache-control policy/breakpoints with provider TTL behavior. It affects cost and latency, not canonical conversation meaning.

Store/cache classification:

```text
cache policy requested on a StepSnapshot  > durable request/provider option if it affects billing policy
cache entries / provider cache lifetime    > optimization only
cache hit/write usage                      > normalized usage metadata where useful
```

Loss of provider cache state must degrade performance only.

## Context editing

Anthropic context editing can clear old tool results/thinking from provider-visible context. This is useful but should not become Cerebro's durable history reducer.

Important architectural observation: Anthropic explicitly permits the application to maintain the full original history while provider context editing determines what is actually shown to the model. That matches Cerebro's intended split:

```text
Cerebro durable semantic history
  > ContextManager policy
  > optional Anthropic context-editing provider option
  > native request
```

If Cerebro enables the feature, its configuration belongs in the `StepSnapshot` because it can change effective model context. Provider-side edited/cache state remains derived.

## Errors

Current Anthropic error classes support a richer canonical taxonomy than Harness v1 originally listed:

- 400 invalid request > `invalid_request`;
- 401 > `authentication`;
- 402 > `quota_or_billing`;
- 403 > `permission_denied`;
- 409 conflict > usually `invalid_request`/fresh-attempt disposition depending operation;
- 413 > `request_too_large`;
- 429 > `rate_limited` or quota/spend variant when distinguishable;
- 500 > `provider_internal`;
- 504 > transient/provider timeout;
- 529 > `provider_overloaded`.

Anthropic can emit an SSE error after HTTP 200. Consequently, adapter transport success does not imply inference success.

SDK retry defaults are useful evidence for transport policy but must not be copied blindly into Cerebro: after semantic output/tool calls have been observed, Harness replay safety must override a generic “retry 5xx/429” rule.

## ModelProfile implications

Anthropic model profiles need more than `supports_reasoning_controls: bool`:

- thinking mode: adaptive / manual extended / disabled combinations;
- whether summarized thinking can be requested/displayed;
- whether old thinking blocks are retained/stripped by model;
- interleaved thinking support;
- tool-choice restrictions while thinking;
- client/parallel tools;
- structured output/tool schema restrictions;
- context/output limits and sampling incompatibilities.

Current Anthropic docs already show thinking controls changing across model generations, so this cannot safely live as global provider behavior.

## State classification

### Required for correctness in relevant flows

- provider `tool_use` ID until matching result/continuation;
- complete unmodified `thinking` and `redacted_thinking` sequence in an active thinking + tool-use turn;
- exact paused/provider-tool response state when continuing a `pause_turn` flow;
- any provider-server-tool block explicitly required to continue the native interaction.

### Fidelity preserving / model-dependent

- older thinking blocks outside the active tool-use cycle when current model rules allow omission but retaining them may preserve continuity.

### Caching/performance only

- prompt-cache entries and TTL state;
- connection/session transport state;
- provider request IDs used only for diagnostics;
- derived provider context-editing/cache state, provided Cerebro retains canonical full history and the editing configuration.

## Harness v1 pressure-test result

Anthropic requires the following corrections before implementation freezes the types:

1. `ProviderOpaqueItem` must be ordered and durably replayable, not a generic metadata bag;
2. visible reasoning summaries must be distinct from signed/hidden replay state;
3. provider call IDs are durable native references, not non-durable hints;
4. completion needs `provider_continuation_required` for provider/server-tool flows such as `pause_turn`;
5. `ModelProfile` needs richer reasoning/tool-interaction capability data than booleans.
