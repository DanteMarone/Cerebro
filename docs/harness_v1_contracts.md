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
are never superseded at all. Active committed results automatically protect their causal tool
calls even if a caller omits those call ids from its explicit protection set.

### Format versions are per object

`InferenceItem`, `InferenceAttempt` and `ToolExecution` each carry their own `format_version`.
Loading refuses an unknown or missing version rather than parsing optimistically, because a field
this build silently ignores is a replay requirement it silently drops.

### The dispatch barrier

An `InferenceAttempt` is marked `dispatch_may_have_escaped` **before** the adapter is invoked. A
crash can therefore leave a false positive — an attempt that looks dispatched when the socket
never opened. That is the safe direction. The unsafe inference, which this ordering forbids, is
concluding that a missing local completion proves the provider was never called.

Construction and deserialization enforce the complete stable-state matrix: admitted means active
and pre-barrier, possibly escaped means active and post-barrier, and terminal dispatch and semantic
states imply one another. Failed and abandoned attempts deliberately retain either barrier value
so recovery can distinguish pre-dispatch from possibly-escaped outcomes.

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
- cancellation terminates and closes the provider stream without promoting accumulated text,
  reasoning, or tool fragments into completed items or a normal `InferenceCompleted` event;
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
place. `start_or_resume(request, cancel_token)` carries explicit cancellation state, and
`stream_events()` registers its own driving task so `cancel(execution_id)` reaches CLI subprocess
cleanup without a concrete-only tracking call.

Phase 1 claims nothing about restart recovery here. `recovery_capability` says no to reconnect,
resume and orphan reconciliation, and `reconcile_orphan()` answers `suspend` rather than guessing
what a lost subprocess did.

## Redaction policy for opaque replay material

Generic code has no legitimate reason to read adapter-owned bytes, so:

- `ProviderOpaqueItem.__repr__` and `__str__` never show the payload, at **any** sensitivity;
- `log_projection()` returns metadata plus `payload: "<redacted>"`, for logs, Hub events and UI;
- direct, discriminated-union and nested request/event validation errors hide their raw inputs;
- the durable serialized form keeps the payload exactly, because a redacted signature cannot
  continue a conversation.

No adapter in this slice can create `hidden_reasoning`, `signature_or_encrypted_reasoning` or
`secret_like` payloads. At-rest encryption, access control and retention for such payloads are
owed by the first adapter PR that can actually emit them.

## Durable store and recovery substrate

Phase 1B adds dedicated Harness tables beside the product schema:

- `agent_turns` and `turn_events` hold versioned current state and sparse semantic evidence;
- `inference_histories` and `inference_items` own deterministic conversation-order replay with
  required turn/attempt attribution and durable supersession metadata;
- `inference_attempts` retains the provider dispatch barrier separately from terminal semantics;
- `tool_executions` retains dispatch uncertainty/resolution and atomically maintains the turn-level
  attention projection;
- `step_snapshots` holds both the Phase 1B identity envelope (`format_version` 1) and the Phase 1C
  executable snapshot (`format_version` 2). They are never interchangeable;
- `harness_artifacts` indexes durable raw tool output, inline or on disk;
- `harness_metadata` names the active schema, storage-format, execution and security-revocation
  epochs.

`HarnessStore` uses the Phase 1A serializers for turns, items, attempts and executions. SQL keeps
query-critical identity/state/version fields explicit while canonical structured content remains in
deterministic JSON. Unknown format versions fail closed. Causal admission is uniquely indexed by
the exact versioned `CausalWakeKey.serialized()` text and its SHA-256 stable hash; duplicates load
the existing turn, while distinct occurrence identities admit distinct turns.

Every compound write runs through `db.run_in_writer()` / `BEGIN IMMEDIATE`. Agent-turn state,
attempt rows, tool rows and history rows use compare-and-set versions, with database constraints
and triggers rejecting identity reuse, version skips, terminal rewind and snapshot mutation.
Known tool resolution can append its bounded `ToolResultItem`, advance history, resolve execution,
and clear attention in one transaction. An indeterminate result keeps attention durable.

Attempt generations are unique within an immutable StepSnapshot, not across the entire AgentTurn.
Store admission rejects step-index rewind and rejects new snapshots, attempts, ToolExecutions, or
provider/tool dispatch marks once the owning turn is terminal. Provider dispatch additionally
requires the turn's current attempt and snapshot identities. The terminal SQL trigger freezes the
product-finalization identity in both explicit columns and canonical JSON, while versioned
post-terminal attention reconciliation remains valid.

Abandoned-attempt supersession requires the attempt to be durably `abandoned`. In the same writer
transaction, the store derives protected calls from ToolExecution rows whose effects may have
escaped and unions them with caller-provided protection. A caller can preserve extra history but
cannot remove the durable causal prefix of a possibly escaped effect.

Discovery queries use only broad owner/identity scope before strict canonical decoding. Lifecycle,
epoch, attention, supersession, and unresolved-effect filtering occurs only after duplicated SQL
state agrees with canonical payloads; disagreement raises instead of returning an incomplete view.

`TurnRecoveryDriver` is the TurnCoordinator-owned standalone startup primitive. Phase 1B does not
wire it into `RuntimeService.start()`: without the reducer, resuming would imply an execution
cutover. Its scan enumerates durable turn identities and reloads/classifies each candidate in
isolation. Loadable turns with missing or corrupt attempt/tool references are conservatively
suspended, stale recovery CAS reloads newer durable truth, and damage in one row cannot skip later
active-epoch work. It accepts no provider adapter or tool executor and performs no external effect.


## Executable snapshot, tool plan and the pre-side-effect checkpoint

Phase 1C makes one snapshotted call executable, and only through one door.

### The immutable executable `StepSnapshot`

`StepSnapshot` (`format_version` 2) freezes everything that decides what a step could run: provider
config and dialect version, model profile and version, provider semantic options, inference-history
and provider-replay versions, context-projection version and token budget, the frozen tool plan,
permission-policy version, security-revocation epoch, workspace/cwd/environment references, and the
completion-policy version. Recovery reads this and nothing else; if any field were left to
"whatever is configured now", a model or tool swap between crash and restart would silently rewrite
what the step meant.

It carries no credentials. Credential-shaped keys in the frozen options are rejected at
construction, and `ProviderConfig.credential_reference` stays the only handle.

Storage writes the canonical envelope *and* every queryable column, and every read compares them. A
hand-edited column is two answers to one question, so it fails closed. A `format_version` 1 identity
seam can never satisfy the executable barrier, and an unknown snapshot or tool-plan version is
refused rather than parsed for the fields this build happens to recognise.

### `ToolPlanSnapshot` and binding generations

The plan freezes the offered `ToolDefinition`s, their executable `ToolBinding`s, the provider
wire-name → `ToolKey` map, and per-key grant evidence. A wire name resolves through that map or not
at all. An unbound definition, an unmapped key, or a binding frozen at a different catalog/policy
version than the plan is rejected.

`ToolBindingGeneration` is the field execution actually re-checks, and its source differs by tool
kind for a reason:

- **CoreTools** run in-process from code, so the generation is a content digest over the canonical
  key, executor identity and the exact offered description and schema. It survives a Cerebro
  restart — a restart does not replace code — and it changes when the offered contract changes.
- **MCP** tools run in a subprocess, so the generation also folds in `StdioMCPClient.connection_id`,
  a fresh value minted on every successful handshake and cleared on stop. A respawn, a restart or a
  schema-changing `tools/list` refresh all produce a new generation. A server nobody has handshaken
  contributes nothing executable.

Trust tier and the `tools_enabled` globs are *grant* state, not binding identity. Revoking a tier
denies the frozen call under its original identity instead of pretending the executor changed.

### The A–L / E2 barrier

`HarnessStore.commit_executable_call_checkpoint` runs one `BEGIN IMMEDIATE` transaction. It first
verifies the facts earlier transactions were supposed to have committed — the executable snapshot is
the turn's active step (A); the named attempt is active and bound to it (B); every finalized item
this attempt produced up to the call is durable, ordered and unsuperseded (C, G); the call item is
this `CerebroCallId` and names the frozen binding's key (D); a replay-required `ProviderCallRef` is
present when required (F); history and replay versions match and never trail the snapshot (H); the
offered binding equals the frozen one exactly (J); the security-revocation epoch is unchanged.

Then it commits, together: the `CerebroCallId` (E), the stable operation key when the frozen
capability requires one (E2), the `ToolExecution` in `not_dispatched` (I) bound to the exact
generation, executor identity and recovery capability (J), the turn's state-version advance (K), and
the matching `tool.call_admitted` checkpoint event (L). Nothing partial survives a failure, and a
crash before the commit leaves a call that is not executable and an external world nobody touched.

### `HarnessToolRuntime`

The standalone effect primitive, deliberately unreachable from production. Its ordering is the point:
load turn/snapshot/execution/binding; reject terminal turns, superseded snapshots, advanced
revocation epochs, changed grants and stale bindings; re-verify the whole barrier **and** commit
`dispatch_may_have_escaped` in one transaction; only then invoke the executor. Verifying in one
transaction and marking in another would leave a window for a revocation to land between them.

After dispatch, only the frozen `ToolRecoveryCapability` may authorise anything. `idempotent` and
`stable_idempotency_key` allow one automatic repeat — the latter reusing the exact persisted key.
`reconcile_before_repeat` consults the declared authoritative lookup and stays indeterminate if it
cannot answer. `never_automatic_repeat` resolves indeterminate immediately. A raising executor is
unknown, never a known failure.

### Raw and model-visible tool output

Known results are split. The complete raw output becomes a durable `harness_artifacts` entry —
inline at or below 8 KiB, otherwise one file written, `fsync`-ed and atomically renamed *before* the
semantic transaction opens, with the index row inserted inside it. A committed `ArtifactRef`
therefore cannot point at a half-written object, and a rolled-back transaction leaves nothing
reachable. Retention is `conversation` scope with no automatic pruning; provenance records the
producing turn, call, tool key, binding generation, byte size and SHA-256.

The model sees the first 4096 characters plus `OmissionMetadata` naming the reason, omitted bytes and
original size. The payload itself is readable only through `ArtifactStore.read`; it never appears in
a turn event, a Hub projection, a log line or an operator attention listing.

## Not implemented here

The durable reducer and direct-provider cutover, production `RuntimeService`/`AgentRuntime` routing
to the Harness path, the semantic provider retry loop, cancellation orchestration, automatic recovery
resumption of executable work, atomic product finalization, and context compaction remain deferred to
Phase 1D. See the Phase 1C handoff for the exact boundary.

`AgentRuntime` is still the only active production execution path. Nothing outside
`cerebro/harness/` imports the package, and the tool-effect primitive is reached only by tests and
explicit internal calls.

## Tests

```bash
PYTHONPATH=. pytest -q tests/test_harness_contracts.py tests/test_harness_serialization.py tests/test_harness_openai_adapter.py tests/test_harness_external_agent.py tests/test_harness_projection.py tests/test_harness_redaction.py
PYTHONPATH=. pytest -q tests/test_harness_store.py tests/test_db_migrations.py
PYTHONPATH=. pytest -q tests/test_harness_snapshot.py tests/test_harness_tool_plan.py tests/test_harness_checkpoint.py tests/test_harness_tool_runtime.py tests/test_harness_crash_matrix.py
```

No test invokes Codex, Claude, Antigravity or Goose. The external-agent tests use a stub provider
and a fake command.
