# Harness v1 canonical contracts (`cerebro/harness`)

`cerebro.harness` holds the provider-neutral types for durable agent execution: identities,
ordered inference history, provider attempts, tool execution state, and the two adapter
boundaries.

**This package does not execute anything yet.** The live production path is still
`cerebro/runtime.py::AgentRuntime`. Phase 1A adds the contracts that later Harness slices will
persist and run, without changing any current behaviour.

Design source of truth: `docs/research/harness-v1/PHASE_1_CONTRACT.md` and
`docs/research/codex-harness/CEREBRO_HARNESS_V1.md`.
Implementation record: `docs/research/harness-v1/PHASE_1A_IMPLEMENTATION_HANDOFF.md`.

## Why these types exist

Cerebro today reconstructs a provider request from collaboration `Message` rows and their
`meta_json`. That works while everything succeeds in one process. It cannot answer the questions
that matter when something goes wrong:

- did the provider see the request, or did the process die first?
- did that tool call reach the outside world, or was it never dispatched?
- is this half-finished assistant turn safe to send back as a prefill?

The canonical contracts answer each of those with a durable fact rather than an inference.

## Module map

| Module | Holds |
| --- | --- |
| `ids.py` | Prefixed identity types (`AgentTurnId`, `CerebroCallId`, `InferenceAttemptId`, …) |
| `content.py` | `Instruction`, `ContentPart` variants, `Provenance`, `OmissionMetadata` |
| `provider_ref.py` | `ProviderCallRef` — provider-owned call correlation and replay state |
| `items.py` | Ordered `InferenceItem` variants and the shared persisted envelope |
| `history.py` | `InferenceHistory` — canonical ordering and AR-02 supersession |
| `events.py` | Canonical inference stream events |
| `attempts.py` | `InferenceAttempt` and the pre-dispatch barrier |
| `errors.py` | `InferenceError` taxonomy and `SemanticRecoveryDisposition` |
| `execution.py` | `ToolExecution` dispatch/resolution state machine |
| `tooling.py` | `ToolKey`, `ToolDefinition`, `ToolBinding`, `ToolRecoveryCapability` |
| `model_profile.py` | `ModelProfile` and `ProviderConfig` |
| `request.py` | `InferenceRequest`, policies, and the request semantic hash |
| `turn.py` | `AgentTurn` lifecycle, product outcome, attention projection |
| `wake.py` | `CausalWakeKey` and its deterministic encoding |
| `serialization.py` | Versioned dump/load with strict `format_version` checks |
| `provider_adapter.py` | The direct native `ProviderAdapter` protocol |
| `external_agent.py` | The separate `ExternalAgentAdapter` protocol |
| `adapters/` | `OpenAICompatibleAdapter`, the CLI external shim, and the dialect registry |
| `projection.py` | Compatibility projection from collaboration `Message` rows |

## The properties worth knowing

### Identities carry their family

Every identity is a prefixed string (`atn_…`, `ccall_…`, `att_…`) and validates its own prefix.
A provider's `tool_call_id` cannot be constructed as a `CerebroCallId`, and one identity family
cannot be reused as another.

### Two identities for one tool call

`CerebroCallId` is what Cerebro executes, audits and recovers against. `ProviderCallRef` is the
provider's own handle — for OpenAI-compatible endpoints, the native `tool_call_id`. They travel
together and never merge. Losing a `replay_required` ref after the tool ran is a correctness
failure, because the provider will reject the continuation and the effect cannot legally be
re-run to recover it.

### Every item knows which attempt produced it

`InferenceItem.producing_attempt_id` is required for provider-originated items and forbidden for
projected ones. That is what lets an abandoned attempt be forgotten by the next request without
being forgotten by the audit trail.

### Supersession, not deletion

When an attempt is abandoned without authoritative completion, output that authorised no
dispatched effect is marked superseded: it leaves `canonical_request_history()` and stays in
`audit_history()`. Supersession never crosses a committed or possibly-escaped effect — the
smallest prefix preserving that effect's causal history stays active, and committed tool results
are never superseded at all.

### Format versions are per object

`InferenceItem`, `InferenceAttempt` and `ToolExecution` each carry their own `format_version`.
Loading refuses an unknown or missing version rather than parsing optimistically, because a field
this build silently ignores is a replay requirement it silently drops.

### The dispatch barrier

An `InferenceAttempt` is marked `dispatch_may_have_escaped` **before** the adapter is invoked. A
crash can therefore leave a false positive — an attempt that looks dispatched when the socket
never opened. That is the safe direction. The unsafe inference, which this ordering forbids, is
concluding that a missing local completion proves the provider was never called.

`ToolExecution` has the same shape: `not_dispatched` → `dispatch_may_have_escaped` → `resolved`,
never backwards, and a resolved outcome is never overwritten by a later timeout or cancellation.

### Uncertainty is representable

`IndeterminateResolution` is a truthful terminal outcome, not a placeholder. An execution that may
have escaped and has no known outcome keeps contributing to `AgentTurn.needs_attention` and
`unresolved_effect_count` even after the turn ends. Cancelling a turn does not make a mutation
that may already have run irrelevant.

A second dispatch after possible escape requires the executor to prove it is safe — via
`ToolRecoveryCapability.repeat_semantics`. `stable_idempotency_key` additionally requires a
durable `stable_operation_key` before the dispatch mark is allowed to commit.

### Transport retry is not semantic replay

`InferenceError.transport_retryable` is the wire's opinion. `classify_recovery()` is the harness's
decision and takes separate arguments for what may already have escaped. A 429 alone never
authorises a fresh semantic attempt, and an unresolved effect outranks every error kind.

`provider_action_for()` turns a disposition into a Phase 1 action. `reconcile_or_suspend`
degenerates to a durable suspend, because Phase 1 has no generic provider-side reconciliation.

### `ModelProfile` is not `ProviderConfig`

`ProviderConfig` answers where and how to reach an endpoint; it holds a `credential_reference`
and never a credential. `ModelProfile` answers how a model behaves. An endpoint speaking the
OpenAI wire format is a wire family, not proof of semantic capability.

## The OpenAI-compatible adapter

`cerebro/harness/adapters/openai_compatible.py` is the compatibility edge for the LM Studio /
OpenAI-compatible path Cerebro runs today.

- every OpenAI-shaped concept — chat roles, `tool_calls`, `tool_call_id`, the assistant-then-tool
  sequence — lives in `adapters/openai_dialect.py` and nowhere else;
- the payload is built from ordered `InferenceItem`s, never from `Message.meta_json`;
- it reuses `OpenAICompatibleProvider.stream_payload` as transport, so there is one HTTP client
  and one SSE parser rather than two that can drift;
- streamed deltas are published as progress and accumulated. Nothing becomes an item until the
  stream ends, so a complete-looking argument fragment can never authorise a tool;
- anything the dialect cannot express is refused explicitly: provider-opaque replay material,
  non-text content parts, a tool call with no provider ref, parallel tool calls, or a config
  naming a different dialect;
- **this adapter emits no `ProviderOpaqueItem`, and therefore no sensitive replay material.**
  `emits_sensitive_replay_material` is `False`. Streamed `reasoning`/`reasoning_content` is a
  summary, is never required back by chat completions, and is never persisted as opaque material.

Dialect assumptions are stated in `OpenAIDialectOptions` rather than assumed. The developer
authority falls back to `system` because the chat-completions servers Cerebro talks to have no
developer role; a future endpoint that does changes one flag.

Adapters are looked up by dialect via `adapters.adapter_factory_for_dialect()`. An unregistered
dialect raises `UnknownDialect`; it never falls back to the OpenAI adapter.

## The external-agent boundary

`claude -p`, `codex exec`, `agy` and `goose run` are not inference providers. Each launches a
harness that owns its own context, approvals, tools and side effects.

`ExternalAgentAdapter` is therefore a separate protocol sharing no base class and no request type
with `ProviderAdapter`. `CliExternalAgentAdapter` wraps the unchanged `CliAgentProvider`, so
prompt rendering, cwd, timeout, output-file handling and the cancellation kill all stay in one
place.

Phase 1 claims nothing about restart recovery here. `recovery_capability` says no to reconnect,
resume and orphan reconciliation, and `reconcile_orphan()` answers `suspend` rather than guessing
what a lost subprocess did.

## Redaction policy for opaque replay material

Generic code has no legitimate reason to read adapter-owned bytes, so:

- `ProviderOpaqueItem.__repr__` and `__str__` never show the payload, at **any** sensitivity;
- `log_projection()` returns metadata plus `payload: "<redacted>"`, for logs, Hub events and UI;
- the durable serialized form keeps the payload exactly, because a redacted signature cannot
  continue a conversation.

No adapter in this slice can create `hidden_reasoning`, `signature_or_encrypted_reasoning` or
`secret_like` payloads. At-rest encryption, access control and retention for such payloads are
owed by the first adapter PR that can actually emit them.

## Not implemented here

The Harness SQL schema and durable store, `TurnRecoveryDriver`, `StepSnapshot` and the tool-plan
projection, the pre-side-effect checkpoint transaction, the reducer/effect cutover, atomic product
finalization, and context compaction. See the handoff document for the exact split.

## Tests

```bash
PYTHONPATH=. pytest -q tests/test_harness_contracts.py tests/test_harness_serialization.py tests/test_harness_openai_adapter.py tests/test_harness_external_agent.py tests/test_harness_projection.py tests/test_harness_redaction.py
```

No test invokes Codex, Claude, Antigravity or Goose. The external-agent tests use a stub provider
and a fake command.
