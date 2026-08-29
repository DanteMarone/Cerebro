# DeepSeek and OpenAI-Compatible Mapping

**Baseline:** current DeepSeek API docs and Cerebro/LM Studio paths reviewed 2026-08-29. See `API_BASELINES.md`.

## Bottom line

“OpenAI-compatible” is a transport family, not a semantic capability guarantee.

DeepSeek is the clearest proof: its current Responses endpoint deliberately implements a subset/dialect of OpenAI Responses, silently ignores some unsupported parameters, has different reasoning representation, is stateless, and has provider-specific thinking replay requirements. LM Studio similarly exposes OpenAI-shaped endpoints while tool quality/capability depends on the loaded model and chat template.

Cerebro should retain an OpenAI-compatible adapter family, but it must be capability/dialect-driven rather than assuming that every accepted OpenAI field has OpenAI semantics.

# DeepSeek

## Current Responses compatibility

DeepSeek's first-party Responses guide documents compatibility details explicitly. At the reviewed baseline:

- Responses is a supported OpenAI-shaped interface for current DeepSeek models, with model availability changing over the current V4 rollout;
- `previous_response_id` and `conversation` are not supported: the endpoint is stateless;
- `store` is effectively false;
- several OpenAI parameters are unsupported or ignored;
- `parallel_tool_calls` is ignored because parallel calling is always enabled in the documented Responses dialect;
- prompt-cache controls are not supported because context caching is automatic;
- `context_management`, background operation and many OpenAI built-in tools are unsupported;
- message/function-call/function-result/reasoning items are translated into DeepSeek's own internal chat semantics;
- image/file inputs are not equivalent to OpenAI Responses support;
- unsupported parameters may be silently ignored for compatibility instead of producing an error.

This means Cerebro must not infer capability from “the request field was accepted.” `ModelProfile`/adapter dialect metadata must decide what the request may contain.

## DeepSeek reasoning replay is correctness state

Current thinking-mode docs say `reasoning_content` is returned alongside visible `content`.

The important distinction:

- if no tool call occurred between user messages, prior `reasoning_content` need not be returned and is ignored if sent;
- if a tool call occurred, the intermediate assistant `reasoning_content` must be fully passed back in subsequent requests;
- for requests carrying `tools`, failing to pass the required `reasoning_content` back can produce a 400 error.

This is a direct counterexample to treating all reasoning output as disposable UI text.

Cerebro mapping:

```text
DeepSeek reasoning_content needed for a tool continuation
  > ProviderOpaqueItem(
       provider_id="deepseek",
       kind="thinking_replay",
       replay_requirement=required_for_correctness,
       retention_scope=provider_defined/current tool interaction,
       sensitivity=hidden_reasoning
     )
```

Even though DeepSeek serializes this field as plaintext, Cerebro should not expose it as canonical `ReasoningSummaryItem` or attempt to interpret/reconstruct chain-of-thought. It is retained only because the provider protocol requires it for continuation.

A provider-approved separate summary, if DeepSeek later exposes one, could map to `ReasoningSummaryItem` independently.

## DeepSeek tool mapping

Chat/Responses function calls remain ordinary Cerebro client tools when Cerebro executes them:

```text
provider function call
  > ToolCallItem + durable ProviderCallRef(native id)

tool result
  > ToolResultItem
  > adapter restores native OpenAI-compatible tool-call/result linkage
```

Parallel calls are multiple canonical calls from the same inference. Do not rely on the request's `parallel_tool_calls` boolean to express capability because current DeepSeek Responses documents that field as ignored/always-on behavior.

DeepSeek provider-side web search is not a Cerebro ToolRuntime call. Keep it as a provider extension/opaque hosted-tool item unless Cerebro defines a portable hosted-search abstraction later.

## DeepSeek Responses reasoning differs from OpenAI Responses reasoning

The current compatibility guide documents `reasoning` input items but not OpenAI-style encrypted reasoning semantics: plain-text reasoning content is merged into the adjacent assistant history, while OpenAI `summary` / `encrypted_content` behavior is not supported equivalently.

Therefore the generic adapter architecture should be:

```text
Cerebro ordered items
  > DeepSeek adapter semantic mapping
  > DeepSeek Responses dialect
```

not:

```text
Cerebro > serialize exact OpenAI Responses schema > hope DeepSeek accepts it
```

The same rule applies to ignored modalities/provider tools.

## DeepSeek caching

DeepSeek context caching is automatic prefix/KV caching. Applications can observe cache-hit/miss token accounting but do not need a cache handle for semantic continuation.

Classification:

```text
cache contents/identity  > optimization only
cache usage tokens       > normalized usage metadata
```

## DeepSeek errors

The documented status classes include:

- 400 invalid format/request;
- 401 authentication;
- 402 insufficient balance/billing;
- 422 invalid parameters;
- 429 rate limit;
- 500 server error;
- 503 overloaded/unavailable.

Recommended mapping:

```text
400/422  > invalid_request (or unsupported when positively identified)
401      > authentication
402      > quota_or_billing
429      > rate_limited
500      > provider_internal
503      > provider_overloaded/transient
```

DeepSeek can keep a long-running request alive with provider-specific streaming behavior; the adapter owns that transport detail.

# Generic OpenAI-compatible adapter family

## Compatibility must be represented as a dialect/profile

`OpenAICompatibleProvider` is useful and should survive Phase 1, but the final adapter should know at least:

```text
wire_family:
  chat_completions
  responses

supported request fields
supported input/output item/content forms
supports reasoning + exact replay rule
supports JSON function tools
supports parallel calls / policy control
supports structured output
supports images/files/audio/video
supports stateful continuation
supports prompt caching controls
unknown-field behavior: reject | ignore | provider-defined
```

These are not all `ModelProfile` fields. Split them:

- endpoint/protocol-wide quirks > adapter dialect capability;
- loaded/model-specific limits and behavior > `ModelProfile`;
- effective request > intersection.

## Unknown/ignored-field behavior matters

A provider that silently ignores an unsupported field is more dangerous than one that rejects it because the request appears successful while semantics changed.

Rule:

> ProviderAdapter should validate canonical requested semantics against its known capability/profile before serialization. Do not use provider acceptance as capability discovery.

Examples:

- requested structured output when compatibility endpoint ignores the schema;
- requested reasoning controls that are accepted but no-op;
- developer authority collapsed to system;
- image/file input accepted but replaced/ignored;
- tool parallelism control accepted but ignored.

If a requested semantic feature cannot be honored, return canonical `unsupported` or apply an explicit, snapshotted degradation policy. Never silently degrade inside the generic runner.

# LM Studio and Cerebro's existing path

## Current Cerebro behavior

`cerebro/providers/openai_compatible.py` currently:

- POSTs `/v1/chat/completions`;
- maps database `Message` rows into Chat messages;
- serializes assistant `tool_calls` and tool results via `Message.meta_json`;
- parses text, `reasoning` / `reasoning_content`, and indexed streaming tool-call fragments;
- exposes coarse `ProviderError` / `ProviderUnavailable` exceptions.

`cerebro/providers/lmstudio.py` is a thin specialization of that adapter.

This path should be wrapped behind the new canonical contract first, not rewritten to LM Studio's native API during Phase 1.

## Current LM Studio APIs

LM Studio currently exposes OpenAI-compatible:

- `/v1/chat/completions`;
- `/v1/responses` with streaming, reasoning and `previous_response_id` state;
- models/embeddings/completions;
- tool use through Chat Completions and Responses.

It also supports provider/server-side features such as Remote MCP on Responses. Those are not required to preserve existing Cerebro behavior.

## Tool capability is model/runtime-specific

LM Studio's tool documentation explicitly distinguishes native tool support from default/emulated tool support. In emulated/default mode, LM Studio prompts the model to emit a tool-call format and parses model text into OpenAI-compliant `tool_calls`; quality varies with model/template.

Therefore a boolean `supports_tools` loses useful information. Recommended profile field:

```text
tool_calling_mode:
  unsupported
  emulated
  native
```

Optionally add a capability confidence/source. For local models this can inform tool planning, default model selection and diagnostics without changing the canonical ToolRuntime contract.

Canonical tool-call output still maps to the same `ToolCallItem`; the distinction is about model reliability/fidelity, not generic execution semantics.

## LM Studio stateful Responses is optional

LM Studio Responses supports `previous_response_id`, but Cerebro does not need to adopt that as durable state. The existing Chat path is already client-history driven.

For Harness v1:

- preserve Chat Completions as the compatibility adapter acceptance target;
- remove `Message.meta_json` as the provider protocol store by translating to canonical `InferenceItem`s before serialization;
- make LM Studio model/profile discovery report actual modalities/tool/structured-output capability where possible;
- later evaluate `/v1/responses` as an adapter optimization/feature expansion, not as a prerequisite for the generic contract.

Remote MCP exposed by LM Studio should remain a provider-hosted extension unless Cerebro explicitly wants the provider, rather than Cerebro `ToolRuntime`, to own those tool calls.

# State classification summary

## DeepSeek correctness state

- OpenAI-compatible native tool-call IDs until results are correlated;
- required `reasoning_content` in thinking + tool flows;
- exact provider-hosted tool items explicitly required for a chosen continuation flow.

## DeepSeek optimization state

- automatic context cache contents;
- connection state;
- diagnostic request IDs.

## LM Studio current Chat correctness state

- assistant tool-call IDs and tool-result linkage;
- any model/provider-specific replay field that a future profile explicitly marks required.

No provider conversation handle is required by Cerebro's current Chat path.

## LM Studio optimization/convenience state

- future `/v1/responses` `previous_response_id` when full canonical history is retained;
- local KV/session/runtime cache state;
- connection state.

# Harness v1 pressure-test result

The OpenAI-compatible path requires these design rules before implementation:

1. “OpenAI-compatible” is an adapter dialect, not a capability claim;
2. validate requested semantics before serialization instead of trusting silently ignored fields;
3. reasoning replay can be correctness state even on Chat-style APIs and must not automatically be exposed as chain-of-thought;
4. tool calling should carry fidelity (`native` vs `emulated`) in model/profile data where relevant;
5. keep current LM Studio Chat behavior as Phase 1 compatibility target, while making canonical history independent of `Message.meta_json`.
