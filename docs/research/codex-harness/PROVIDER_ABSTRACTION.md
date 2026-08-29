# Codex Provider Abstraction

**Status:** Initial confirmed map of provider metadata, runtime provider behavior, model catalogs, authentication, request/client lifetime, transport state and Responses normalization.

**Pinned upstream:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

No Codex implementation code is copied into Cerebro by this document. Findings are currently **conceptual inspiration only**.

## Main conclusion

Codex has a meaningful provider abstraction, but it is not yet the abstraction Cerebro needs for truly heterogeneous native model APIs.

The good separation is:

- `ModelProviderInfo`: configured/serialized endpoint, auth, headers, retry and transport metadata;
- `ModelProvider`: runtime provider-owned behavior such as auth resolution/recovery, account state, model catalog, capability upper bounds, endpoint selection and API-error mapping;
- `ModelClient`: session-scoped provider/API state;
- `ModelClientSession`: turn-scoped transport/sticky-routing state;
- `ModelInfo`: model-specific behavior/capabilities, separate from provider behavior.

The important limitation is that the actual model wire abstraction remains Responses-shaped. At the pinned baseline `WireApi` contains only `Responses`, configured providers are described as OpenAI-compatible endpoints, the generic prompt/history uses Codex/OpenAI `ResponseItem`s, and normalized stream events are `codex_api::ResponseEvent` derived from the Responses protocol.

For Cerebro, provider-native clients should normalize into a **Cerebro-owned inference contract before entering the generic turn runtime**. Do not make Anthropic, Gemini, DeepSeek or local adapters impersonate OpenAI Responses unless that is genuinely the best transport for that provider.

## 1. Provider configuration and provider runtime are separate

`ModelProviderInfo` is the serializable configuration surface. It includes:

- display name and base URL;
- environment-key, command-backed, bearer-token and AWS auth configuration;
- query parameters and static/environment-derived headers;
- request retry and stream retry budgets;
- stream idle and WebSocket connection timeouts;
- whether OpenAI login is required;
- whether Responses-over-WebSocket and standalone web search are supported.

Users can extend/override built-in provider entries through configuration.

`ModelProvider`, by contrast, is a runtime trait. It owns behavior that cannot be expressed as passive config alone.

**Cerebro implication:** split `ProviderConfig` from `ProviderAdapter`. Secrets/endpoints/retry knobs are data; auth refresh, request construction, error mapping and streaming are executable adapter behavior.

Upstream:
- `codex-rs/model-provider-info/src/lib.rs`
- `codex-rs/model-provider/src/provider.rs`

## 2. The runtime provider owns capability upper bounds

`ModelProvider::capabilities()` returns provider-level bounds including:

- namespace tools;
- image generation;
- web search;
- external web access;
- remote compaction support.

The comments explicitly describe these as an upper bound: normal configuration can disable more, but callers should not expose capabilities the provider marks unsupported.

This complements the richer per-model `ModelInfo` already mapped in `CONTEXT_AND_PROMPTS.md`.

**Cerebro implication:** effective capability should be an intersection, roughly:

```text
provider capability
  intersect model capability/profile
  intersect Cerebro feature policy
  intersect workspace/agent/turn permissions
  > effective request/tool capability
```

Provider and model capabilities should not be collapsed into one flat model registry.

Upstream:
- `codex-rs/model-provider/src/provider.rs`
- model metadata sources referenced in `CONTEXT_AND_PROMPTS.md`

## 3. Authentication is provider-owned and recoverable

The runtime provider abstraction exposes:

- provider-scoped auth manager access;
- current auth/account state;
- request auth construction, including task-scoped auth;
- recognition of recoverable authentication failures;
- provider-specific authentication recovery;
- user-facing recovery lifecycle messages.

The default configured provider preserves OpenAI-login/API-key behavior. Amazon Bedrock demonstrates that a provider implementation can override endpoint resolution, AWS credential sources/signing, refreshable auth-error recognition, recovery, account state, model catalogs and error mapping.

**Cerebro implication:** provider adapters should own credential acquisition/refresh/signing and convert auth failures into canonical harness errors. Generic turn code should ask the adapter for a request client/auth context rather than know how OAuth, API keys, AWS SigV4, Google credentials or local-daemon authentication work.

Upstream:
- `codex-rs/model-provider/src/provider.rs`
- `codex-rs/model-provider/src/amazon_bedrock/mod.rs`
- provider auth modules

## 4. Endpoint and header policy belongs below the harness loop

Provider config can define base URLs, query parameters and headers, while runtime providers can further resolve the actual request-time base URL and mutate API-provider setup.

Examples include:

- ChatGPT versus OpenAI API default endpoints depending on auth mode;
- managed residency headers;
- Amazon Bedrock region/runtime endpoint selection;
- environment-derived headers;
- provider-specific authentication headers/signing.

**Cerebro implication:** the generic harness should not concatenate `/v1/...`, construct authorization headers or know cloud-region endpoint rules. It should pass a canonical inference request to the active adapter.

Upstream:
- `codex-rs/model-provider-info/src/lib.rs`
- `codex-rs/model-provider/src/provider.rs`
- `codex-rs/model-provider/src/amazon_bedrock/*`

## 5. Request retry policy is provider metadata; semantic retry remains harness policy

`ModelProviderInfo` carries provider-specific HTTP and stream retry counts/timeouts. Converting it to the lower API `Provider` creates the HTTP retry policy used by the transport client.

As mapped in `RECOVERY_AND_VERIFICATION.md`, the higher sampling loop separately decides whether a semantic/stream failure is retryable and may perform transport fallback.

**Cerebro implication:** preserve at least two retry layers:

- adapter transport/request retry for failures known to be safe at the HTTP/RPC layer;
- turn-runtime retry/recovery based on canonical inference failure semantics.

Adapters should expose retry hints and typed failure metadata rather than internally retrying everything until a generic timeout appears.

Upstream:
- `codex-rs/model-provider-info/src/lib.rs`
- `codex-rs/codex-client/src/retry.rs`
- `codex-rs/core/src/responses_retry.rs`

## 6. Model catalogs belong to the provider, model behavior does not

`ModelProvider` creates the appropriate `ModelsManager`. The default OpenAI-like provider may use remotely cached model catalogs; Bedrock can provide normalized static provider-specific catalogs.

The resulting `ModelInfo` still describes model-level behavior separately from provider runtime behavior.

**Cerebro implication:** a provider adapter should supply/discover its models, aliases and raw capability data, but Cerebro should normalize these into its own `ModelProfile` layer. A model identity should include provider namespace so ambiguous strings such as `claude-*`, `gemini-*` or local model names never rely on global coincidence.

Upstream:
- `codex-rs/model-provider/src/provider.rs`
- `codex-rs/model-provider/src/amazon_bedrock/mod.rs`
- `codex-rs/models-manager/*`

## 7. Session-scoped and turn-scoped provider state are deliberately separated

`ModelClient` is session-scoped. Its documented stable state includes provider selection/auth, thread identity and transport-fallback state.

`ModelClientSession` is created fresh for each turn and owns turn-specific Responses transport state such as:

- a lazily opened/reused WebSocket connection;
- last request/response information used for incremental requests;
- the server-provided `x-codex-turn-state` sticky-routing token.

The source explicitly warns that reusing `ModelClientSession` across turns would leak a previous turn's routing token into the next turn.

**Cerebro implication:** define adapter lifetimes explicitly:

```text
ProviderAdapter / provider account
  long-lived configuration/auth/catalog state

AgentProviderSession (optional)
  reusable connection/cache state safe across turns

InferenceTurnSession
  provider state valid only for one Cerebro turn
```

Do not let provider-side conversation/routing tokens become generic thread identity.

Upstream:
- `codex-rs/core/src/client.rs`

## 8. Provider-side incremental state is an optimization, not the durable source of truth

The Responses WebSocket client can reuse a previous response ID and send only incremental input when the new request is a compatible extension of the previous one. Prewarm can establish such state before real generation.

Crucially, rollout tracing still records the **logical full model-visible request** rather than treating the compressed WebSocket delta as canonical history.

This is an important architectural rule.

**Cerebro implication:** Anthropic prompt caching, OpenAI response IDs, Gemini cached content, local KV-cache handles and similar mechanisms should remain adapter optimizations. Cerebro's durable request/context state must be sufficient to reconstruct a semantically equivalent request without those opaque provider handles.

Provider cache handles may be checkpointed as hints, but loss of a hint should degrade performance rather than destroy task recoverability.

Upstream:
- `codex-rs/core/src/client.rs`

## 9. Codex already normalizes transport events before the turn loop

The lower API layer maps the Responses SSE/WebSocket protocol into a shared `ResponseEvent` stream including concepts such as:

- response created/completed;
- output item added/done;
- text/tool-input/reasoning deltas;
- token usage and response ID;
- server model/rate-limit metadata;
- moderation/verification metadata.

`core::client_common::ResponseStream` exposes these normalized events to the generic turn loop and propagates cancellation if the consumer drops early.

**Cerebro implication:** this normalization boundary is exactly the right *kind* of boundary. Cerebro should own an analogous provider-neutral event type, for example:

```text
InferenceEvent
  Started
  AssistantContentDelta
  ReasoningDelta/Metadata
  ToolCallStarted/Delta/Completed
  Usage
  ProviderMetadata
  Completed
```

The exact schema should be designed from the union of GPT, Claude, Gemini, DeepSeek and local APIs rather than copied from Responses.

Upstream:
- `codex-rs/codex-api/src/common.rs`
- `codex-rs/core/src/client_common.rs`

## 10. The current wire abstraction is Responses-only

At the pinned baseline, `WireApi` has one supported variant: `Responses`. The old Chat wire API is explicitly rejected.

`ModelProviderInfo` describes a provider's OpenAI-compatible endpoint. Even Amazon Bedrock support is implemented against Bedrock's OpenAI-compatible Responses endpoint(s), while customizing auth/catalog/capabilities around it.

The core `Prompt` and normalized event types also use `ResponseItem` / Responses concepts directly.

Therefore Codex's current abstraction boundary is roughly:

```text
provider differences around an OpenAI Responses-shaped wire
```

not:

```text
arbitrary native model protocol > generic harness protocol
```

**Cerebro implication:** do not adopt `WireApi::Responses` as the central abstraction. Cerebro needs adapters for at least:

- OpenAI Responses;
- Anthropic Messages;
- Google Gemini generate/stream APIs;
- DeepSeek's actual chosen API shape;
- OpenAI-compatible local endpoints where appropriate;
- potentially direct local inference engines with no HTTP protocol at all.

Upstream:
- `codex-rs/model-provider-info/src/lib.rs`
- `codex-rs/core/src/client.rs`
- `codex-rs/codex-api/src/common.rs`

## 11. Some provider-specific features should stay adapter-local

Codex's core client contains many OpenAI-specific request/header behaviors: Responses WebSocket versions, sticky turn-state headers, response IDs, OpenAI beta headers, routing hints, server model headers and specialized endpoint calls.

These are useful optimizations/features but poor candidates for a generic harness contract.

**Cerebro implication:** the generic turn runtime should care about semantic capabilities such as:

- streaming;
- native tool calls;
- parallel tool calls;
- structured output;
- reasoning controls/visibility;
- image/audio input/output;
- prompt caching/stateful continuation;
- context limits;
- usage/rate-limit reporting.

Adapter-specific headers, cache tokens and endpoint dialects should stay private unless promoted into a provider-neutral capability with a clear cross-provider meaning.

Upstream:
- `codex-rs/core/src/client.rs`
- `codex-rs/codex-api/*`

## 12. Candidate Cerebro provider boundary

A better model-agnostic boundary for Cerebro is likely:

```text
ProviderAdapter
  provider_id
  auth/account lifecycle
  discover_models()
  capabilities(model)
  open_session(optional)
  start_turn(turn_request) -> stream<InferenceEvent>
  classify_error(raw_error) -> InferenceError
  optional cache/continuation hints

Cerebro InferenceRequest
  model_ref = provider_id + model_id
  system/developer/context messages in Cerebro canonical form
  multimodal content
  canonical tool definitions
  tool-choice / parallel-call policy
  reasoning/verbosity controls when supported
  output schema
  metadata/tracing

Cerebro InferenceEvent
  provider-neutral semantic events
  opaque provider metadata only where needed
```

The provider adapter then translates between this canonical contract and the native provider protocol.

## 13. Proposed portability rule

A strong acceptance test for the Cerebro provider boundary is:

> If an active worker disappears and all provider-owned connection/cache IDs are lost, can another worker rebuild the next semantically equivalent inference request from Cerebro-owned durable state?

If the answer is no, provider state has leaked too far upward into the harness model.

This follows directly from the Codex distinction between durable logical request/history and opportunistic Responses WebSocket incremental state.

## Open questions carried forward

- exact canonical message/content/tool schema needed to faithfully represent Anthropic and Gemini without lowest-common-denominator loss;
- whether reasoning blocks/signatures must be stored opaquely and replayed for some providers;
- provider-specific prompt-cache lifetime/checkpoint semantics;
- cancellation behavior and usage finalization across each native API;
- whether some providers require conversation/session IDs for correctness rather than optimization;
- model discovery/versioning and capability refresh policy;
- how Cerebro should expose provider-specific experimental controls without polluting the generic contract;
- pricing/rate-limit normalization and budget enforcement.

These should be validated against additional harnesses/providers after the Codex mining pass, but they do not block finishing the remaining Codex-specific MCP/tool-output research.

## Provenance ledger additions

| Finding | Upstream source | Classification | Candidate Cerebro use |
| --- | --- | --- | --- |
| Config metadata separate from runtime provider behavior | `model-provider-info`, `model-provider` | conceptual inspiration only | `ProviderConfig` + `ProviderAdapter` split |
| Provider capability upper bounds | `model-provider/src/provider.rs` | conceptual inspiration only | Capability intersection model |
| Provider-owned auth/account/recovery | provider trait + Bedrock implementation | conceptual inspiration only | Strong adapter responsibility |
| Provider-owned model catalog | provider/models-manager | conceptual inspiration only | Model discovery/profile pipeline |
| Session vs turn client lifetime | `core/src/client.rs` | conceptual inspiration only | Adapter state-lifetime contract |
| Opaque continuation/cache state as optimization | Responses WebSocket client | conceptual inspiration only | Provider cache-hint rule |
| Normalize wire stream before generic turn loop | `codex-api`, `client_common` | conceptual inspiration only | Strong Harness v1 candidate |
| Current Responses-only wire abstraction | `model-provider-info`, client/api types | conceptual inspiration only | Explicit gap; do not copy boundary |

No Codex implementation source has been copied or adapted into Cerebro.
