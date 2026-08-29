# Provider Capability Matrix

**Baseline date:** 2026-08-29. This matrix describes API/interface semantics, not a promise that every model under a provider supports every capability. Effective capability remains provider/dialect ∩ model profile ∩ Cerebro policy.

| Capability | OpenAI Responses | Anthropic Messages | Gemini Interactions | DeepSeek OpenAI-compatible | Cerebro LM Studio Chat path |
| --- | --- | --- | --- | --- | --- |
| Native history shape | ordered input/output items | ordered messages with content blocks | ordered steps | Chat or Responses-compatible dialect | Chat messages |
| System/developer semantics | system/developer/instructions supported | system/instruction surface; model/API rules vary | `system_instruction` | system + developer accepted in Responses, developer documented as system-equivalent | system role rendered by local chat template |
| Text | yes | yes | yes | yes | yes |
| Images | API/model dependent | yes on supported models | yes on supported models | current Responses guide does not provide OpenAI-equivalent image semantics | Chat endpoint supports images depending model/runtime |
| Documents/files | yes | document/file mechanisms | multimodal/document support | current Responses compatibility is limited | model/runtime/API dependent |
| Audio/video | model/API dependent | model/API dependent | native multimodal support on capable models | not portable through reviewed compatibility path | model/runtime dependent |
| Client JSON function tools | yes | yes | yes | yes | yes |
| Parallel client calls | yes, model/profile gated | yes, model/profile/tool-policy gated | yes | current Responses dialect documents always-on parallel behavior | model/template/runtime dependent |
| Tool result native correlation ID | `call_id` | `tool_use_id` | function-call ID | OpenAI-compatible call ID | OpenAI Chat `tool_call_id` |
| Provider-hosted tools | many | server tools | built-in tools | subset such as web search | Responses can expose Remote MCP; current Cerebro Chat path does not use it |
| Structured output | yes | model/API feature-specific | yes | supported subset | JSON schema structured output supported |
| Provider reasoning controls | yes, model-specific | adaptive/manual/disabled modes vary by model | thinking controls vary by model | thinking/reasoning effort; some sampling fields ignored in thinking | model/runtime dependent |
| Provider-supported reasoning summary | supported on applicable models | summarized/omitted thinking modes on applicable models | thought summaries where exposed | reviewed Responses guide says OpenAI-style summary not generated | model/runtime dependent |
| Opaque/sensitive reasoning replay state | encrypted reasoning items in stateless reasoning flows | signed `thinking` / `redacted_thinking` blocks | signed `thought` steps | `reasoning_content` required in tool flows; treat as sensitive replay state | no generic requirement in current Chat adapter, but model/provider-specific fields may exist |
| Stateless lossless continuation path | yes when complete required output items are replayed | ordinary Messages is client-history driven | yes if all model-generated steps are replayed exactly | yes; reviewed Responses endpoint is stateless | yes for current Chat path |
| Provider-side continuation ID | `previous_response_id`, conversation resource | no equivalent required for ordinary client-tool Messages; provider resources/server-tool flows exist | `previous_interaction_id` | current Responses compatibility: unsupported | LM Studio Responses supports `previous_response_id`; current Cerebro Chat path does not use it |
| Provider continuation ID required for ordinary client-tool correctness | no if full replay retained | no | no if full exact step replay retained | no | no |
| Prompt/context caching | implicit/explicit cache controls | explicit cache control/breakpoints | implicit caching in Interactions | automatic context caching | local/runtime caching; endpoint-dependent |
| Cache handle required for semantic correctness | no | no | no | no | no for current path |
| Provider context management/compaction | Responses context management/compact features | context editing | provider-side state plus API-specific context behavior | reviewed Responses subset does not support OpenAI context management | local/native features vary; current Chat path client-history driven |
| Streaming semantic events | rich typed Responses SSE | block/delta SSE | interaction/step SSE | OpenAI-shaped stream subset | Chat delta SSE |
| Mid-stream error after successful HTTP start | yes/possible in streamed protocol | yes, explicitly documented | yes via SSE error event | yes according to stream/result semantics | transport/provider dependent |
| Unsupported field may be silently ignored | OpenAI itself generally validates per API/model | validation errors common | machine-readable validation errors | **yes, explicitly documented for compatibility** | compatibility/model behavior varies |
| Tool-call fidelity classification useful | native API capability | native API capability | native API capability | native API capability | **yes: native vs emulated/default tool use** |

## Portable semantic core

The matrix supports a deliberately small but expressive core:

```text
ModelRef
Instruction
ordered InferenceItem history
  MessageItem
  ToolCallItem
  ToolResultItem
  ReasoningSummaryItem
  ProviderOpaqueItem

ContentPart
ToolDefinition / ToolKey / ToolResult
ReasoningPolicy
OutputPolicy
InferenceEvent
InferenceError
Usage
CompletionStatus
```

This is not a lowest common denominator because `ProviderOpaqueItem` and provider extensions preserve richer capabilities without teaching the generic runner their wire schema.

## Capabilities that belong in `ModelProfile`

Prefer model/profile data for facts that affect planning/request validity:

```text
context/output limits
input/output modalities
structured-output support
client tool support
tool_calling_mode: unsupported | emulated | native
parallel tool support
reasoning control modes
reasoning summary support
required reasoning-replay behavior
instruction-role fidelity
sampling/control incompatibilities
native provider-tool availability by semantic capability
```

Do not assume all models under one provider are identical. Anthropic thinking modes, Gemini tool/thinking capabilities, OpenAI reasoning/hosted-tool support and LM Studio local-model tool fidelity all vary at model level.

## Capabilities that belong in `ProviderAdapter` / dialect

Prefer adapter/dialect behavior for:

```text
endpoint/API version/auth/headers
wire item/block/step representation
stream event parser
native call-ID serialization
opaque replay capture/re-emission
provider continuation resources
cache protocol
provider error codes
unknown-field behavior
provider-wide compatibility translations
```

DeepSeek's “accepted but ignored” Responses fields are the strongest example of dialect behavior that cannot be inferred from a generic OpenAI schema.

## Features that should remain explicit provider extensions in Harness v1

Do not put these into the portable core solely because one provider has them:

- OpenAI Programmatic Tool Calling and provider-hosted tool item families;
- Anthropic provider/server-tool block families and context-editing strategy details;
- Gemini managed agents/environments/background resources and provider built-in tool step types;
- DeepSeek-specific hosted-search/apply-patch compatibility items;
- LM Studio Remote MCP/provider-owned stateful Responses behavior.

The generic runner may normalize only the cross-provider semantic consequences it actually needs — for example `provider_continuation_required`, usage, completion/incomplete state, or a provider-hosted operation consuming budget — while the native payload stays adapter-owned.

## Required replay state vs optimization state

| State | Classification |
| --- | --- |
| Provider-issued client tool call/result correlation ID | correctness-required until result/continuation is complete |
| OpenAI encrypted reasoning/output items required by stateless tool/reasoning continuation | correctness/fidelity-critical; durable |
| Anthropic signed/redacted thinking blocks during tool-use continuation | correctness-required; durable exact replay |
| Gemini signed thought/model-generated steps in stateless continuation | correctness-required; durable exact replay |
| DeepSeek `reasoning_content` in thinking + tool flows | correctness-required; durable but non-display/sensitive |
| Anthropic `pause_turn` exact provider continuation response | correctness-required for chosen server-tool flow |
| OpenAI `previous_response_id` | optional continuation handle if full replay retained |
| Gemini `previous_interaction_id` | optional continuation handle if full replay retained |
| LM Studio Responses prior response ID | optional if full canonical history retained |
| prompt-cache keys/cache entries/implicit KV cache | performance/cost only |
| HTTP/WebSocket connection/session state | performance/transport only |
| provider request ID | diagnostics only unless a specific async/background API requires it operationally |

## Main design consequence

The “provider state should only be hints” rule is too broad. The correct rule is:

> Provider **conversation identity** and **cache state** should not become Cerebro's source of truth, but exact provider-originated replay material may be part of Cerebro's durable inference history when the native API requires it for a valid or fidelity-preserving continuation.
