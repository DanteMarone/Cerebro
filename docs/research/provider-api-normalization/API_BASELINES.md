# Native Provider API Baselines

**Issue:** #204 — `Research: normalize native provider APIs for Harness v1`

**Research date:** 2026-08-29

**Rule:** Current/time-sensitive provider claims in this research are grounded in first-party documentation wherever available. These are documentation/API baselines, not copied implementation source.

## OpenAI

Primary interface reviewed: **Responses API**.

First-party sources accessed 2026-08-29:

- Responses create reference: https://developers.openai.com/api/reference/resources/responses/methods/create
- Conversation state / manual history guidance: https://developers.openai.com/api/docs/guides/conversation-state
- Function calling: https://developers.openai.com/api/docs/guides/function-calling
- Reasoning models / reasoning continuity: https://developers.openai.com/api/docs/guides/reasoning
- Prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching
- Current model guidance: https://developers.openai.com/api/docs/guides/latest-model

Baseline facts relevant to Cerebro:

- Responses is item-oriented rather than only role/message-oriented. `input` and `output` can contain messages, function calls/results, reasoning items and provider-hosted tool items.
- Function calls carry a provider `call_id`; function-call outputs must reference that `call_id`.
- `previous_response_id` and `conversation` provide provider-side continuation, but OpenAI also documents manual stateless history replay.
- For stateless reasoning use, previous response output items — including encrypted reasoning items — can/must be replayed to preserve reasoning continuity. Current model guidance says to preserve every response output item when managing history manually.
- Reasoning models used with function calling require reasoning items from the tool-producing response to accompany the subsequent function output. Raw hidden reasoning is not exposed; encrypted reasoning items are opaque replay material.
- `prompt_cache_key` / `prompt_cache_options` are cache controls and are not the semantic conversation source of truth.
- Responses streaming exposes typed lifecycle/item/delta/completion events.
- Current Responses also contains provider-specific hosted tools, background responses, context management/compaction, and programmatic tool calling. These should not automatically become generic Harness primitives.

Documentation freshness note: pages above were current when accessed on 2026-08-29; the OpenAI docs do not consistently expose a page-level publication date.

## Anthropic

Primary interface reviewed: **Messages API** plus thinking, tool use, prompt caching and context management documentation.

First-party sources accessed 2026-08-29:

- Messages API: https://platform.claude.com/docs/en/api/http/messages
- Tool use overview / client tool results: https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
- Tool-use troubleshooting / exact thinking replay: https://platform.claude.com/docs/en/agents-and-tools/tool-use/troubleshooting-tool-use
- Extended/adaptive thinking and tool use: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
- Streaming Messages: https://platform.claude.com/docs/en/build-with-claude/streaming
- Prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Context editing: https://platform.claude.com/docs/en/build-with-claude/context-editing
- API errors: https://platform.claude.com/docs/en/api/errors

Baseline facts relevant to Cerebro:

- Messages content is block-oriented. Blocks include text, images/documents, `tool_use`, `tool_result`, thinking and redacted-thinking variants, plus provider/server-tool variants.
- Client tool calls use a provider-issued `tool_use` ID; the corresponding `tool_result` references that ID. Parallel tool use can emit multiple `tool_use` blocks in one assistant response.
- When thinking accompanies tool use, Anthropic requires the complete unmodified thinking block, including its signature, to be returned with the tool result. Modified thinking blocks can be rejected with 400. Redacted-thinking blocks are opaque and likewise intended for pass-through replay.
- Anthropic therefore has provider-originated replay material that is correctness-relevant inside a tool/reasoning cycle and must not be represented only as displayable reasoning text.
- Streaming tool arguments arrive as incremental JSON fragments; thinking can stream separately and signatures arrive as their own deltas near block completion.
- Provider/server-tool flows can return `pause_turn`; Anthropic documents continuing by passing the paused response back unchanged. This is provider-controlled continuation state, distinct from a Cerebro client tool call.
- Prompt caching (`cache_control`, TTL/breakpoints) changes cost/latency rather than conversation semantics.
- Context editing is a provider-side request-context optimization/transform. Anthropic guidance allows the client to retain full original history rather than making the edited server context canonical.
- Errors have useful distinct classes including authentication, billing, permission, request-too-large, rate limit, timeout and overloaded; an error can also arrive after HTTP 200 inside an SSE stream.

Documentation freshness note: pages above were current when accessed on 2026-08-29; Anthropic docs do not consistently expose a page-level publication date.

## Google Gemini

Primary interface reviewed: **Interactions API**, now the current recommended/stateful agent-capable interface. `generateContent` was reviewed only where legacy thought-signature/caching behavior helps explain compatibility requirements.

First-party sources accessed 2026-08-29:

- Gemini API overview/getting started: https://ai.google.dev/gemini-api/docs/get-started
- Interactions overview: https://ai.google.dev/gemini-api/docs/interactions-overview
- Interactions API reference: https://ai.google.dev/api/interactions-api
- Function calling: https://ai.google.dev/gemini-api/docs/function-calling
- Thinking / thought signatures: https://ai.google.dev/gemini-api/docs/thought-signatures
- Tools: https://ai.google.dev/gemini-api/docs/tools
- Context caching: https://ai.google.dev/gemini-api/docs/caching
- Structured output: https://ai.google.dev/gemini-api/docs/structured-output
- API versions: https://ai.google.dev/gemini-api/docs/api-versions
- Interactions errors: https://ai.google.dev/gemini-api/docs/api-errors

Freshness observed in first-party docs:

- Main Gemini API / API-version pages: last updated 2026-08-26 UTC.
- Tools documentation: last updated 2026-08-18 UTC.
- Context caching documentation: last updated 2026-08-13 UTC.
- Interactions API errors were updated during August 2026; the reviewed result carried the current machine-readable error table.

Baseline facts relevant to Cerebro:

- Google states that Interactions became the default Gemini API interface in June 2026; `generateContent` is now the legacy interface for this research target.
- The current Interactions schema is ordered **steps**, not only messages. Inputs can include content and prior steps; outputs can include text/content steps, function calls, function results, thought steps, and provider-hosted tool steps.
- Interactions supports provider-side state with `store: true` plus `previous_interaction_id`, but also documents stateless operation.
- In stateless mode, Google requires all model-generated steps to be preserved and resent exactly, including `thought` and `function_call` steps. `thought` steps contain encrypted reasoning signatures that must not be edited or dropped.
- Stateful continuation manages thought blocks/signatures server-side. This makes `previous_interaction_id` a convenience/state carrier, not the only way to recover semantics if Cerebro durably retains the exact steps.
- Custom function calls have IDs and function results must match them. Parallel and sequential/compositional function calling are supported.
- Built-in tools execute provider-side; custom functions execute client-side. Combined flows can interleave provider tool steps, custom calls/results and signed thought state.
- Interactions currently uses implicit caching; explicit cached-content objects remain associated with legacy `generateContent`. Cache state is performance/cost state, not required replay state.
- Interactions streaming is typed around interaction/step events. Errors can be returned as HTTP failures or typed SSE error events.

## DeepSeek

Primary interfaces reviewed: current **OpenAI-compatible Chat Completions and Responses behavior**, with special attention to thinking + tool calling.

First-party sources accessed 2026-08-29:

- API docs home: https://api-docs.deepseek.com/
- Responses compatibility guide: https://api-docs.deepseek.com/guides/responses_api/
- Thinking mode: https://api-docs.deepseek.com/guides/thinking_mode/
- Context caching: https://api-docs.deepseek.com/guides/kv_cache/
- Error codes: https://api-docs.deepseek.com/quick_start/error_codes/
- Current model/pricing page: https://api-docs.deepseek.com/quick_start/pricing/
- V4-Pro GA release note, published 2026-08-13: https://api-docs.deepseek.com/news/news260813/
- Change log: https://api-docs.deepseek.com/updates/

Baseline facts relevant to Cerebro:

- DeepSeek's 2026-08-13 V4-Pro GA release says the API now natively supports the OpenAI Responses format and is adapted for Codex. Some individual Responses/pricing documentation snapshots still carried pre-GA text saying only V4-Flash was supported and V4-Pro support was upcoming. For model-availability claims, this research treats the newer dated 2026-08-13 release as authoritative and treats the compatibility guide as authoritative for wire/dialect semantics where not contradicted by the release.
- OpenAI compatibility remains a **dialect/subset**, not semantic identity with OpenAI. The Responses compatibility guide documents unsupported fields/items that may be ignored, rewritten or returned with fixed values.
- In the reviewed Responses dialect, `previous_response_id` and `conversation` are not stateful continuation mechanisms equivalent to OpenAI's; unsupported parameters may be silently ignored.
- DeepSeek thinking-mode Chat Completions emits `reasoning_content`. In a thinking + tool-call cycle, DeepSeek requires this reasoning content to be fully passed back in subsequent requests; omitting it can produce a 400 error.
- That reasoning payload is therefore correctness-relevant provider replay state. Cerebro must retain it without treating it as UI-visible chain-of-thought or attempting to interpret/reconstruct it.
- Tool calls use OpenAI-compatible call IDs/results and can be parallel depending on current model/endpoint semantics.
- DeepSeek context caching is automatic prefix caching and is an optimization only.
- DeepSeek documents distinct 400/401/402/422/429/500/503 errors. The 402 class is a concrete reason the canonical error taxonomy should not collapse billing/quota into authentication.

## LM Studio / Cerebro OpenAI-compatible path

Cerebro branch sources reviewed:

- `cerebro/providers/base.py`
- `cerebro/providers/openai_compatible.py`
- `cerebro/providers/lmstudio.py`

LM Studio first-party sources accessed 2026-08-29:

- OpenAI-compatible endpoints: https://lmstudio.ai/docs/developer/openai-compat
- Chat Completions: https://lmstudio.ai/docs/developer/openai-compat/chat-completions
- Responses: https://lmstudio.ai/docs/developer/openai-compat/responses
- Tool use: https://lmstudio.ai/docs/developer/openai-compat/tools
- Structured output: https://lmstudio.ai/docs/developer/openai-compat/structured-output

Baseline facts relevant to Cerebro:

- Cerebro currently uses `/v1/chat/completions` through `OpenAICompatibleProvider`; `LMStudioProvider` is a thin preset/subclass.
- Current Cerebro serializes tool-call protocol state through `Message.meta_json`, proving the workspace `Message` model is not a sufficient inference-history AST.
- The adapter consumes Chat-style `delta.content`, `delta.reasoning` / `reasoning_content`, and indexed `delta.tool_calls` fragments.
- LM Studio currently exposes both OpenAI-compatible Chat Completions and Responses; its Responses endpoint includes streaming/reasoning and optional `previous_response_id` state. Cerebro does not need to adopt that state as its durable source of truth.
- LM Studio tool support can be native for models/templates explicitly supported by the runtime or default/emulated by prompting/parsing model text into OpenAI-compatible tool calls. Therefore “supports tools” is not purely provider-level; model/runtime tool-call fidelity belongs in model capability/profile data.

## Cross-provider baseline conclusion

The native APIs validate the broad `ProviderAdapter` boundary from `CEREBRO_HARNESS_V1.md`, but they reject one oversimplification: **not all provider-owned state is merely cache/session optimization**.

At least OpenAI reasoning items, Anthropic signed/redacted thinking blocks, Gemini signed thought steps, DeepSeek thinking replay state, and native tool-call IDs can be required for correct stateless continuation or tool-result association. Cerebro should still own conversation/task semantics, but it must durably preserve exact provider-originated replay material when an adapter marks it correctness-required.

Conversely, prompt-cache keys/entries, implicit KV caches, HTTP/WebSocket connection state, and provider continuation IDs for APIs that also support lossless stateless replay remain optional performance/convenience state.
