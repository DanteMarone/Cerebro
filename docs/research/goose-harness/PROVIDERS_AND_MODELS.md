# Goose providers and models

Upstream: `aaif-goose/goose`

Pinned commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification: **conceptual inspiration only**.

## Provider abstraction

The shared provider contract is primarily in `crates/goose-provider-types/src/base.rs`; product wiring is in `crates/goose/src/providers/`, while reusable direct-provider implementations live in `crates/goose-providers/`.

Confirmed behavior:

- `Provider` is async, `Send + Sync`, and streaming-first.
- `stream(model_config, system, messages, tools)` is the primary generation interface; default `complete` collects the stream.
- Providers expose a stable provider name and can optionally expose a provider-owned session id.
- `resume(session_id)` is a provider hook; default behavior is a no-op.
- `manages_own_context()` defaults false.
- `supports_builtin_tools()` defaults to `!manages_own_context()`.
- `permission_routing()` defaults to `Noop`; providers can opt into external/action-required permission handling and receive confirmations.
- providers can report thinking-effort support and subscribe to capability changes.

This is not a minimal LLM API abstraction. It can represent both direct model APIs and external agent harnesses.

## Registry and provider families

Confirmed source:

- `crates/goose/src/providers/init.rs`
- `crates/goose/src/providers/mod.rs`
- `crates/goose-providers/src/lib.rs`

The pinned registry includes multiple provider families:

- direct first-party APIs such as Anthropic, Google and OpenAI;
- cloud/model-platform adapters such as Azure/Foundry, Databricks, GCP Vertex AI, Hugging Face, OpenRouter and others;
- local inference/Ollama paths;
- OAuth/subscription-backed paths such as Gemini OAuth, xAI OAuth and GitHub Copilot;
- CLI or harness-backed providers such as Gemini CLI and Claude Code;
- ACP-backed agent providers such as Claude ACP, Codex ACP, Copilot ACP, Pi ACP and Amp ACP;
- custom/declarative/OpenAI-compatible providers.

`crates/goose-providers/src/lib.rs` contains the reusable direct-provider layer (Anthropic, Google, OpenAI, OpenAI-compatible, Azure Foundry, Databricks, Ollama, Snowflake, declarative providers, optional local inference). Product-specific wrappers and harness adapters stay under `crates/goose/src/providers/`.

The registry also distinguishes provider type (`Preferred`, `Builtin`, `Declarative`, `Custom`) and can attach inventory/configured-state discovery plus provider-specific cleanup functions.

## Provider metadata

`ProviderMetadata` / `ModelInfo` in `crates/goose-provider-types/src/base.rs` carry more than display labels.

Provider metadata includes:

- internal/display name and description;
- default model and known-model list;
- model documentation link;
- configuration/setup keys and steps;
- model-selection hint;
- optional `fast_model` for lightweight/cheap tasks;
- setup/deprecation metadata.

Per-model information can include:

- resolved model name;
- context limit;
- input/output token cost and currency;
- cache-control support;
- reasoning capability;
- thinking preservation format;
- static request parameters.

This lets the harness reason about models without hard-coding every capability into the central loop.

## ModelConfig and capability normalization

Confirmed source: `crates/goose-provider-types/src/model.rs`.

`ModelConfig` contains model name, optional resolved context limit, temperature, max output tokens, tool-shim configuration, provider request parameters, reasoning configuration, vision support and non-serialized request headers.

Important semantics:

- default context fallback is 128,000 tokens when no stronger source resolves it;
- persisted/deserialized context limits are intentionally ignored and reset to `None`, avoiding stale model limits across runs;
- canonical model metadata can populate output limits, reasoning and vision support;
- max output fallback is 4,096 tokens;
- model-name conventions can map suffixes such as `-low`/`-medium`/`-high` into thinking effort for supported model families;
- model-name heuristics infer reasoning for selected families unless explicitly configured;
- direct request headers are not serialized into the request body;
- Goose-internal request parameters are filtered rather than blindly forwarded.

The model-switch/subagent inheritance path deliberately whitelists model-family-agnostic reasoning settings rather than copying arbitrary provider request parameters. This reduces accidental provider-specific state leakage when a session changes model/provider.

## Thinking/reasoning is a first-class capability axis

Confirmed source:

- `crates/goose-provider-types/src/base.rs`
- `crates/goose-provider-types/src/model.rs`
- `crates/goose-provider-types/src/thinking.rs`
- `crates/goose/src/acp/provider.rs`

Goose separates “model supports reasoning” from “how thinking state can be replayed.” `ThinkingPreservationFormat` supports:

- content prepend;
- XML-wrapped content;
- provider-native `reasoning_content`.

The source explicitly notes that not every OpenAI-compatible endpoint accepts provider-native reasoning replay (Cerebras is named as an example), so preservation format is modeled per backend rather than assumed universal.

ACP providers can advertise a dynamic thinking-effort selector. Goose mirrors that capability and watches it for changes, which matters when an external harness changes model/session configuration beneath the Goose provider wrapper.

## Context ownership is the largest provider leak

Confirmed source:

- `crates/goose-provider-types/src/base.rs`
- `crates/goose/src/acp/provider.rs`
- `crates/goose/src/context_mgmt/mod.rs`

A provider can declare that it owns context. ACP does:

- `AcpProvider::manages_own_context()` returns true;
- `permission_routing()` returns `ActionRequired`;
- `provider_session_id()` returns the ACP session id;
- `resume()` loads the ACP session and swaps it into the provider wrapper.

When context is provider-owned, Goose disables its own compaction path and by default does not expose Goose built-in tools through the normal model-tool path. In other words, the provider is effectively another agent runtime, not merely an inference endpoint.

This is architecturally pragmatic but blurs two concepts:

1. **model provider** — stateless-ish inference service with model-specific capabilities;
2. **agent/harness provider** — sessionful external runtime that owns history/tools/approvals.

For Cerebro, keeping these as separate interface families would likely make ownership boundaries easier to reason about while still allowing adapters between them.

## Provider session resume and handoff

Confirmed source:

- `crates/goose/src/agents/mod.rs`
- `crates/goose/src/agents/agent.rs`
- `crates/goose/src/acp/provider.rs`

Inference metadata stored on messages includes provider identity and optional provider session id. `latest_provider_session_id()` finds the newest inference metadata for the same provider. Before continuing, `Agent` asks the provider to resume that external session.

If provider resume fails, Goose logs the failure and continues with a handoff rather than failing the entire local Goose session. ACP specifically supports loading a stored ACP session id and closes the previous backing session after successful replacement.

This produces two layers of resumability:

- Goose-owned local session/conversation continuity;
- optional provider/harness-owned session continuity.

The local session can survive loss of the provider-side session, though behavior may degrade to a context handoff.

## Capability differences that affect harness behavior

The important provider/model differences are not just payload syntax. They can change central harness behavior along these axes:

| Capability | Harness consequence |
|---|---|
| Context limit | compaction threshold and tool-response budgeting |
| Provider owns context | disables Goose compaction and changes tool ownership |
| Provider session id/resume | enables external-session continuity |
| Permission routing | approval may be handled by external harness rather than Goose |
| Built-in tool support | determines whether Goose tools are offered directly |
| Reasoning/thinking | controls effort UI/config and replay representation |
| Vision | controls image-capable message paths |
| Cache control | enables provider-specific cache semantics |
| Model costs | usage/cost accounting |
| Streaming quirks | provider adapter must normalize partial text vs complete tool calls |
| Request params | provider-specific knobs must not leak across model/provider changes |

## Cerebro implications

The strongest reusable idea is a capability-bearing provider/model descriptor rather than a provider name switch scattered throughout the loop.

The strongest caution is that Goose's `Provider` interface spans two abstraction levels. Cerebro's intended direct-provider architecture would benefit from keeping direct model inference narrow, then representing external harnesses (ACP-like or future agent backends) as a distinct capability boundary. Context ownership, tool ownership, approvals and external session lifecycle can then be negotiated explicitly instead of being inferred from one provider trait.

No implementation code from Goose should be copied or adapted in this phase.
