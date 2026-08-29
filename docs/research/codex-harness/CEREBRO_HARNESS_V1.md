# Cerebro Harness v1

**Status:** Reconciled and frozen for implementation by issue #206.

**Scope:** Architecture/design only. No production implementation is included in this branch.

**Reconciliation date:** 2026-08-29.

**Authoritative Cerebro inputs:**

- Codex harness research: `research/codex-harness-mining@3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- Goose harness research: `research/goose-harness-mining@ddb3ad9b5951fcbfe51420aac10df213200ccad5`
- Native provider normalization: `research/provider-api-normalization@f33801a853b6e6952e07767c83947fd582a41f13`
- Accepted Phase 0 characterization: `test/harness-v1-phase0-characterization@df542c53f587c8963ce84e8d83d731473ee7bd0d`
- Current seam inventory: `research/harness-v1-seam-inventory@3870a64baeb81e6d32b1ddd13bf0022db30961a0`
- Failure-mode audit: `research/harness-v1-failure-audit@ee7a8a37fc03d2538ee3ecc5007a48a79d8a4af4`
- Current-source baseline characterized by those inputs: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

Codex and Goose findings remain **conceptual inspiration only**. Harness v1 is an independent Cerebro design. No upstream implementation code is to be copied or adapted without a separate provenance decision.

## 1. Goal

Harness v1 is Cerebro's provider-neutral execution layer beneath the existing Slack/channel/task product runtime.

The architectural invariant is:

> A Cerebro agent turn is durable Cerebro state. Providers and external harnesses are replaceable execution mechanisms operating against immutable, versioned Cerebro snapshots.

Harness v1 must support direct native provider APIs without making any provider's message format, conversation ID, cache, process lifetime, or reasoning representation the source of truth. It must also preserve current Cerebro product behavior while removing provider/tool protocol state from collaboration `Message` objects.

## 2. Product boundaries that stay above the harness

Harness v1 does not absorb Cerebro's collaboration/wake layer.

These remain above it:

- `RuntimeService` wake/dispatch policy;
- `ChannelPoller` channel wake policy;
- channels, DMs, teams, memberships and attribution;
- public collaboration `messages` and read cursors;
- product `tasks`;
- agent profile/home/memory concepts;
- final message publication semantics;
- `Hub` / WebSocket live fanout;
- measured usage and external-harness quota presentation.

Current entry shape can remain approximately:

```text
RuntimeService / ChannelPoller
        > AgentRuntime.run_turn(...)
        > TurnCoordinator / HarnessRunner
        > durable AgentTurn + reducer/effects
        > final product outcome
        > existing messages + Hub projections
```

`AgentRuntime` remains the migration adapter/product-facing turn boundary initially. Its current `_generate` and `_run_tool` responsibilities move behind harness contracts incrementally rather than through a greenfield rewrite.

## 3. Non-goals for the first implementation phases

Do not block Harness v1 on:

- durable multi-worker takeover;
- parallel mutation or parallel client-tool execution;
- child/subagent execution;
- durable recovery of CLI/external coding harnesses;
- compaction;
- deferred/vector tool search;
- provider-hosted tools as a generic cross-provider feature;
- every native provider at once;
- hard distributed provider concurrency limits;
- token-by-token durable stream storage;
- replacing SQLite/asyncio/Hub with distributed infrastructure.

The canonical types and durable identities must leave room for these without schema/type breakage.

## 4. Component architecture

```text
TurnCoordinator
  admits/loads durable AgentTurn
  preserves causal wake identity
  owns product finalization boundary

HarnessReducer
  pure/re-entrant decision over durable turn state
  selects the next effect or terminal/suspended state

EffectExecutor
  admits one version-bound effect
  invokes ProviderAdapter or ToolRuntime
  persists authoritative completion/recovery facts

ContextManager
  projects collaboration/product state into canonical inference history
  owns context budgeting/compaction later

StepSnapshot
  immutable executable state for one semantic inference step

ProviderRegistry
  direct-native ProviderAdapter instances/configuration
  ModelProfile resolution

ExternalAgentRegistry
  ExternalAgentAdapter instances for CLI/ACP/vendor harnesses

ToolCatalog / ToolPlanner / ToolPolicy / ToolRuntime
  Cerebro-owned tool identity, exposure, binding, policy and execution
  MCP is one tool source/transport beneath these contracts

CompletionPolicy
  separates provider inference completion from Cerebro product/task acceptance

TurnStore
  durable turn projection, ordered inference items, attempts,
  snapshots, tool execution state and sparse execution events
```

These are logical boundaries, not a requirement for one class per box.

## 5. Re-entrant reducer/effect model

Harness operation is a durable reducer/effect loop, not one coroutine whose local variables are the execution state.

Conceptually:

```text
load AgentTurn at version V
  > reduce durable state
  > no effect | provider effect | tool effect | finalization | suspend
  > atomically admit effect against V
  > execute admitted effect
  > atomically persist authoritative result and advance version
  > reload/reduce again
```

Phase 1 may run only one local worker, but every authoritative object carries identities/versions sufficient for later stale-worker fencing. Process-local task ownership and semaphores remain capacity/cancellation conveniences, never recovery truth.

A reducer retry may recompute a decision; it may not repeat an external effect unless the durable effect state authorizes that dispatch.

## 6. Durable AgentTurn and causal admission

A collaboration `turn_id` is not sufficient execution state. Introduce a distinct durable `AgentTurn` per acting agent.

Required semantic fields include:

```text
AgentTurn
  id: AgentTurnId
  format_version
  state_version                 # monotonic compare-and-set version
  execution_epoch               # reserved for later ownership fencing

  conversation_turn_id
  causal_wake_key
  trigger_message_id?
  channel_id
  agent_id

  root_agent_turn_id?
  parent_agent_turn_id?
  product_task_id?

  lifecycle:
    queued | running | suspended | completed | cancelled | failed
  suspension_reason?
  cancel_requested_at?

  current_step_index
  active_step_snapshot_id?
  active_inference_attempt_id?

  product_outcome_kind?
  final_message_id?
  failure_kind?
  failure_detail?

  created_at / started_at / updated_at / completed_at
```

`causal_wake_key` makes admission idempotent. For current message-driven wakes it is derived from wake kind, target agent and durable trigger identity; intentionally recurring future wakes must include an occurrence identity.

Do not put this lifecycle into `messages` or `Message.meta_json`.

## 7. Canonical inference model

Canonical history is an **ordered `InferenceItem` stream**, not a role/message transcript.

```text
Instruction
  authority: system | developer
  content: list[ContentPart]
  provenance

InferenceItem =
  MessageItem(
    item_id,
    role=user|assistant,
    content,
    provenance
  )

  ToolCallItem(
    item_id,
    call_id: CerebroCallId,
    tool_key: ToolKey,
    input: ToolInput,
    provider_ref?: ProviderCallRef
  )

  ToolResultItem(
    item_id,
    call_id: CerebroCallId,
    tool_key: ToolKey,
    status,
    content,
    provider_ref?: ProviderCallRef
  )

  ReasoningSummaryItem(
    item_id,
    content,
    provenance
  )

  ProviderOpaqueItem(
    item_id,
    provider_id,
    adapter_dialect,
    kind,
    exact_payload,
    replay_requirement,
    retention_scope,
    sensitivity
  )
```

Portable `ContentPart` types begin with text, JSON and media/artifact references. Vendor wire blocks are not generic content merely because a provider serializes them alongside messages.

### 7.1 Provider opaque replay material

`ProviderOpaqueItem` is ordered adapter-owned protocol state. Generic harness code persists/sequences it but never interprets its payload for tool/task/completion decisions.

```text
replay_requirement:
  required_for_correctness
  fidelity_preserving
  optimization_only

retention_scope:
  current_tool_cycle
  current_turn
  conversation
  provider_defined

sensitivity:
  ordinary
  hidden_reasoning
  signature_or_encrypted_reasoning
  secret_like
```

Active `required_for_correctness` items are durable and non-trimmable/reorderable. This covers signed/encrypted reasoning blocks, thought signatures, DeepSeek reasoning replay and other native continuation material when required by the owning adapter.

Provider reasoning retained only for replay remains sensitive adapter-owned state. Generic/UI surfaces expose only provider-supported `ReasoningSummaryItem` / `ReasoningSummaryDelta` according to Cerebro policy. Hidden chain-of-thought is never reconstructed or promoted to normal logs/Hub output.

### 7.2 Two tool-call identities

```text
CerebroCallId
  stable Cerebro identity for one admitted client-tool call

ProviderCallRef
  provider_id
  native_call_id?
  opaque?
  replay_required
```

`CerebroCallId` is authoritative for Cerebro execution/audit/recovery. `ProviderCallRef` is provider protocol state and is durable whenever required to correlate a result or continue native history.

## 8. Inference request and ProviderAdapter

```text
InferenceRequest
  step_snapshot_id
  model_profile_ref
  instructions: list[Instruction]
  history: list[InferenceItem]
  tools: list[ToolDefinition]
  tool_policy
  reasoning_policy?
  output_policy
  trace/task metadata
  provider_options?
  cache_hints?
```

State categories are deliberately different:

- `provider_options`: semantic provider-specific request configuration; frozen in the `StepSnapshot`;
- `cache_hints` / optional continuation handles: performance/convenience state that may be lost when stateless lossless replay exists;
- `ProviderOpaqueItem` / `ProviderCallRef`: exact provider-originated replay state, durable when required.

`ProviderAdapter` is only for direct native/provider inference.

```text
ProviderAdapter
  provider_id
  dialect_id / version

  resolve_capabilities(...)
  prepare(InferenceRequest, ProviderConfig) -> PreparedProviderRequest
  stream(prepared, cancel_token) -> AsyncIterator[InferenceEvent]
  classify_error(...) -> InferenceError
  close()
```

Provider adapters own auth, endpoint/wire schema, serialization, stream parsing, native call/reference binding, opaque replay capture/re-emission, provider continuation/cache mechanisms, raw error mapping and transport-only retry when unquestionably safe.

The generic runner never branches on provider names.

### 8.1 ExternalAgentAdapter is separate

`CliAgentProvider` is not a direct inference provider. It launches an external harness whose process/session may own context, approvals, tools and side effects.

Introduce a separate contract:

```text
ExternalAgentAdapter
  adapter_id
  start_or_resume(execution_request, cancel_token)
  stream_events(...)
  cancel(...)
  reconcile_orphan(...)
```

Phase 1 may preserve current CLI behavior through a compatibility path, but it must not model CLI/ACP/vendor harnesses as `ProviderAdapter`. Durable orphan/reconnect semantics are deferred before external harnesses are allowed to claim Harness v1 re-entry guarantees.

## 9. ModelProfile is not provider configuration

`ProviderConfig` answers where/how to call a provider: credentials, endpoint, API/dialect version, transport options.

`ModelProfile` answers how a model behaves for planning/request construction and is separately versioned.

```text
ModelProfile
  profile_id / version
  model_id
  context/output limits
  input/output modalities
  tool_calling_mode: unsupported | emulated | native
  tool_input_forms
  parallel_client_tools
  structured_output
  reasoning_control_modes
  reasoning_summary_support
  opaque_replay_behavior
  instruction_role_fidelity
  stateless_lossless_replay
  hosted_tool capability names
  parameter incompatibilities
  token-estimation policy
```

Adapter/dialect capabilities are intersected with the `ModelProfile`; an "OpenAI-compatible" endpoint is a wire family, not proof of semantic capability. Silent acceptance/ignoring of fields is never capability negotiation.

## 10. Authoritative inference events and provider attempts

Streaming events provide UX/parser progress; finalized items provide semantic authority.

```text
InferenceStarted
OutputItemStarted
AssistantTextDelta
ReasoningSummaryDelta
ToolCallInputDelta
OutputItemCompleted(item: InferenceItem)   # authoritative
UsageUpdate
ProviderMetadata
InferenceCompleted(status, usage, metadata)
InferenceFailed(error)
```

`InferenceCompleted.status` includes at least:

```text
end_turn
tool_calls_pending
provider_continuation_required
max_output_reached
content_filtered_or_refused
incomplete
```

Provider inference completion is not Cerebro turn completion.

Every provider dispatch has a durable `InferenceAttemptId` bound to one immutable `StepSnapshot` before network dispatch. The attempt state must allow the harness to know that dispatch may have escaped even when local completion is missing. Late events are accepted into current semantic history only while their attempt remains active for that snapshot/version.

A provider/model switch with incompatible active replay state requires an explicit durable abandonment/fresh semantic boundary. Old opaque state is never translated to the new adapter, and late events from the abandoned attempt cannot execute tools or complete the turn.

## 11. Provider errors, retryability and semantic replay

Canonical error kinds include:

```text
transient_transport
rate_limited
quota_or_billing
authentication
permission_denied
invalid_request
request_too_large
context_exhausted
provider_overloaded
provider_internal
cancelled
policy_denied
unsupported
fatal_internal
```

`InferenceError` records provider code/message/request ID/retry-after and provider-level retryability. That is not enough to decide semantic recovery.

A separate harness recovery disposition answers whether semantic work may be repeated:

```text
same_attempt_transport_retry
fresh_attempt_from_current_checkpoint
compact_then_fresh_attempt
refresh_auth_then_fresh_attempt
reconcile_or_suspend
not_replay_safe
```

A 429, timeout or transient stream failure does not authorize rewinding over committed semantic/tool effects. Durable semantic progress is monotonic across recovery.

## 12. StepSnapshot

Every semantic provider sample is built from one immutable `StepSnapshot`.

```text
StepSnapshot
  snapshot_id
  format_version
  agent_turn_id
  step_index
  turn_version_at_creation

  provider_config_ref / adapter_dialect_version
  model_profile_ref / model_profile_version
  provider_semantic_options

  inference_history_version
  provider_replay_version
  context_projection_version
  token_budget

  ToolPlanSnapshot
  permission_policy_version
  security_revocation_epoch
  workspace/cwd/environment reference

  completion_policy_version
  trace/root/parent metadata
```

`ToolPlanSnapshot` contains exact model-visible definitions, provider wire-name mapping, executable binding identity/generation, policy grant evidence and recovery/idempotency capabilities.

Snapshot immutability means a call never inherits a new binding or grant. A monotonic security revocation/kill epoch may still invalidate an old grant before dispatch; it produces a denial/stale result under the original call identity rather than rebinding the call.

Mutable workspace contents are not made immutable merely by snapshotting a path. Until resource/version preconditions or isolated workspaces exist, preserve sequential mutation behavior.

## 13. Tool architecture

Cerebro owns the canonical tool model. MCP is a source/transport, not the internal execution model.

```text
ToolKey
  source_type: core | mcp | connector | extension
  source_id
  namespace
  name

ToolDefinition
  key
  description
  input_schema
  output_schema?
  provenance
  annotations

ToolBinding
  key
  executor_identity
  binding_generation
  policy_version
  catalog_version

ToolRecoveryCapability
  effect_class: read_only | side_effecting
  repeat_semantics:
    idempotent
    stable_idempotency_key
    reconcile_before_repeat
    never_automatic_repeat
  reconciliation_binding?
```

`CoreTools` and `CompositeToolExecutor`/`MCPRegistry` are current implementation sources to wrap, not replace wholesale. Existing trust-tier filtering, execution-time allowlist checks and filesystem confinement remain mandatory.

## 14. Tool execution state and crash ambiguity

Generic exactly-once external side effects are not promised.

A stable `CerebroCallId` prevents duplicate execution of the same admitted call when durable state can prove what happened. It cannot prove that an arbitrary remote effect did or did not commit after a crash/network/cancellation race.

Every admitted call therefore has orthogonal monotonic execution state:

```text
ToolExecution
  call_id
  snapshot_id
  admitted_turn_version

  dispatch_state:
    not_dispatched
    dispatch_may_have_escaped
    resolved

  resolution:
    known_outcome(outcome)
    indeterminate_needs_attention

  executor_recovery_capability
  stable_operation_key?
  raw_output_ref?
  model_output?
```

Before invoking an external executor, Cerebro durably advances the call to `dispatch_may_have_escaped`. This is intentionally conservative: after restart, absence of a result never proves a side effect did not occur.

Automatic repeat dispatch is allowed only when the executor contract proves read-only behavior, idempotency, stable externally enforced idempotency key semantics, or authoritative reconciliation. Otherwise recovery resolves/suspends as indeterminate and issues no second side effect.

Cancellation is a turn/control fact, not evidence about an already-dispatched effect. Pre-dispatch cancellation may prevent a call. Post-dispatch cancellation cannot rewrite known success or uncertainty into "did not happen".

## 15. The pre-side-effect executable barrier

This is a hard Harness v1 invariant.

Before any side-effecting client tool can execute, one atomic durable checkpoint must contain or reference:

- finalized `ToolCallItem` from `OutputItemCompleted`;
- stable `CerebroCallId`;
- required `ProviderCallRef`;
- all preceding required `ProviderOpaqueItem`s in correct order;
- immutable executable `StepSnapshot` and `ToolPlanSnapshot` binding;
- provider semantic options/replay versions;
- tool recovery/idempotency capability and operation key when applicable;
- the durable transition that makes this call eligible for dispatch.

Only after this checkpoint commits may dispatch begin.

Streaming deltas are never sufficient authority, even if arguments appear complete.

## 16. Tool result representation

Raw/full tool output and model-visible output are separate.

```text
ToolResultItem
  call_id
  tool_key
  status:
    success | error | denied | cancelled_before_dispatch |
    timeout | unavailable | indeterminate
  content: bounded typed model-visible ContentParts
  raw_output_ref?
  original_size?
  omission/truncation metadata?
  timing/error metadata?
```

The durable raw result/artifact is the recovery/evidence fact when needed. Bounded model projection can be regenerated and must explicitly say when content was omitted.

For an unreconcilable post-dispatch ambiguity, `indeterminate` truthfully represents the unknown outcome; it must never be manufactured as ordinary `error`/`cancelled` merely to close the call.

## 17. Durable storage semantics

Define semantics first; do not reuse an existing table merely because its name looks similar.

Phase 1-compatible durable objects are:

```text
agent_turns          current indexed turn projection + versions
turn_events          sparse versioned semantic transition/audit log
step_snapshots       immutable serialized executable snapshots
inference_items      ordered canonical semantic + opaque history
inference_attempts   provider dispatch identity/state/result metadata
tool_executions      canonical call admission/dispatch/resolution state
```

Exact SQL column layout is an implementation detail constrained by `PHASE_1_CONTRACT.md`.

Current `tool_calls` and `audit_events` are **not** treated as existing Harness v1 state. They are unused by the current runtime and have different/underspecified semantics. Leave them untouched unless a later migration deliberately maps them with explicit compatibility/provenance.

Current product `tasks` stay product work items. Current `messages` stay collaboration history. `Message.meta_json` may retain product/import compatibility metadata but is not canonical inference/replay storage.

SQLite's existing `db.run_in_writer()` / `BEGIN IMMEDIATE` discipline is the atomicity primitive for multi-record executable transitions.

For every executable transition, `agent_turns` projection and its corresponding semantic event/checkpoint either commit in one transaction or one representation is explicitly derivable under the same monotonic version. No crash may leave two plausible next effects.

## 18. Final product outcome and Phase 0 behavior

Accepted completion is a durable product decision separate from provider completion.

For ordinary chat success, final collaboration message insertion and terminal-success `AgentTurn` state are one idempotent SQLite finalization transaction (or an equivalent idempotent outbox protocol if storage later diverges). This preserves completion-order message IDs because the final `messages` row still appears only at completion.

Phase 0 behavior is contractual:

- zero partial/intermediate channel message rows during streaming/tool rounds;
- concurrent final agent replies remain ordered by completion time;
- topic `PASS` exact-match behavior remains silent/discarded;
- topic empty `stop` remains valid silent completion;
- DM `PASS` and empty completion remain fail-closed with an error message;
- multiple client tool calls execute sequentially for now;
- per-provider concurrency isolation remains;
- `TurnGuard` ceilings/freeze behavior remain observable;
- cancellation emits terminal UI/runtime cleanup and leaves no partial collaboration row;
- CLI cancellation still kills/terminates the owned child as today;
- measured usage remains resilient best-effort telemetry;
- provider/tool failures preserve current fail-closed user-visible behavior until a deliberate product change.

A valid topic silent/PASS result is a terminal `AgentTurn` product outcome whose `final_message_id` is intentionally absent. Recovery distinguishes that from a lost final message.

## 19. Context migration from current `ContextBuilder`

`ContextBuilder` is retained as a useful current collection/budgeting seam. It stops being the canonical history type owner.

Migration direction:

```text
StoreAdapter.history / collaboration state
  + identity/manual/channel/scratchpad/memory sources
  > ContextManager source sections
  > canonical Instructions + InferenceItems
  > StepSnapshot context projection
  > ProviderAdapter serialization
```

The existing single-system-message behavior remains a compatibility projection for local/OpenAI-chat templates, not a canonical inference rule.

Compaction is deferred from Phase 1, but active provider replay scopes and history versions are represented now so future compaction cannot delete/reorder required replay state.

## 20. Current runtime seam migration

### `cerebro/runtime.py::AgentRuntime`

Keep the product-facing entry and Phase 0 behavior. Move provider/tool loop state out of `_generate` locals into durable reducer state. Move tool admission/execution semantics out of `_run_tool` into canonical `ToolRuntime` while preserving current executor routing.

### `cerebro/providers/base.py::Provider.stream(list[Message], ...)`

Replace/bridge this boundary with canonical `ProviderAdapter`. During migration, a compatibility adapter can translate `InferenceRequest` into the existing OpenAI-compatible wire behavior.

### `OpenAICompatibleProvider` / `LMStudioProvider`

Keep as the first compatibility path. `to_chat_messages()` becomes edge translation from canonical ordered items rather than a reason for canonical history to remain `Message`-shaped. LM Studio `/v1/chat/completions` remains a supported Phase 1 target.

### `CliAgentProvider`

Reclassify behind `ExternalAgentAdapter`; do not force its flattened prompt/process/session semantics into native provider inference contracts. Preserve current subprocess/cwd/timeout/cancellation behavior while durable external-session recovery remains deferred.

### `cerebro/service.py::RuntimeService`

Stay above the harness. `_provider_for`/composition is gradually replaced by provider/external-agent registries/factories, but `_consider`, `_responder`, `_poll_turn`, live cancellation ownership and channel wake semantics are not moved into the harness.

### `cerebro/poller.py::ChannelPoller`

Stay a product wake mechanism. Harness durability does not automatically make poller backoff/cursor state restart-durable.

### `CoreTools`, MCP registry/composite executor

Wrap current catalog/execution sources behind canonical ToolCatalog/Policy/Runtime. Preserve trust tiers, allowlists and confinement. MCP server `trust`/`env` fields are not assumed to be stronger enforced boundaries than current source proves.

### `TurnGuard`

Keep current Phase 0 ceilings/observable freeze behavior. Its process-local counters are not durable turn ownership. Durable state/versioning becomes the recovery/execution authority; TurnGuard remains a policy/admission input until deliberately consolidated later.

### Hub

Hub/UI events remain lossy/transient projections. Durable turn/inference/tool state is recovery truth. Event duplication/loss across process failure is tolerated; clients resynchronize from durable product state.

### Usage/quota

Preserve provenance:

- `budget_usage`: measured provider token usage, resilient telemetry;
- `agent_quota`: self-reported/relayed external-harness quota.

Do not collapse them when `CliAgentProvider` is reclassified.

## 21. Recovery and monotonic progress

Recovery always resumes from the latest authoritative durable semantic boundary.

Rules:

1. committed `InferenceItem`s and tool resolutions are never silently removed to retry an earlier semantic step;
2. provider errors do not imply semantic replay safety;
3. a new semantic retry is a new `InferenceAttemptId` from the current checkpoint;
4. an exact admitted `CerebroCallId` is never rediscovered/reissued by rewinding history;
5. post-dispatch uncertainty is reconciled/idempotently retried only with executor proof; otherwise suspend/needs-attention;
6. late superseded provider/tool events cannot become current;
7. cancellation prevents new autonomous effects after terminal control state, but does not falsify prior effects;
8. active incompatible provider replay state must be explicitly abandoned before switching provider/model families.

## 22. Concurrency model

Keep these concepts separate:

- **turn/effect ownership:** durable state/version/epoch; correctness;
- **provider semaphores:** process-local capacity controls;
- **resource/workspace ownership:** mutation conflict control;
- **idempotency/reconciliation:** external-effect recovery.

Phase 1 is single-process and preserves current sequential tool execution. `state_version`, `execution_epoch`, attempt IDs, snapshot IDs and binding generations exist immediately so later multi-worker fencing can be added without redefining the canonical objects.

Before multi-worker recovery ships, every authoritative transition/dispatch/finalization must validate a monotonic ownership epoch. Current TTL leases alone are not sufficient fencing.

## 23. CompletionPolicy

`CompletionPolicy` receives provider-completed semantic output plus durable turn/tool evidence and decides:

```text
allow(product_outcome)
continue_with_feedback(canonical feedback)
fail(reason)
suspend(reason)
```

Phase 1 implements the current chat policy only: exact PASS/silence/DM/error/length behavior. Coding-task verification gates are deferred but use the same contract later.

Provider `end_turn` is an inference state, not automatic product acceptance.

## 24. Observability and event layers

Three layers remain distinct:

1. **Durable execution facts**: `agent_turns`, ordered items, attempts, tool executions, sparse `turn_events`.
2. **Transient UI/Hub stream**: text/summary deltas, activity, tool progress, `message.new`/`message.done`.
3. **Telemetry/accounting**: timings, measured usage, retries, quotas, diagnostics.

Identifiers should include turn, step snapshot, attempt and call identities. Sensitive provider replay payloads and full tool output are excluded from generic logs/Hub by default.

## 25. Phase 1 scope

Phase 1 is the smallest **single-process durable core** that proves the frozen contracts without adding broad features.

It includes:

- canonical IDs/types and versioned serialization;
- ordered `InferenceItem` history;
- `ProviderAdapter` plus existing OpenAI-compatible/LM Studio compatibility path;
- separate `ExternalAgentAdapter` boundary while preserving legacy CLI behavior;
- immutable `StepSnapshot` and current CoreTools/MCP tool-plan bindings;
- durable `AgentTurn`, snapshot, inference attempt, item and tool execution state beside `messages`;
- durable provider-attempt identity before dispatch;
- finalized-output/replay checkpoint before side-effecting tools;
- explicit tool dispatch uncertainty and executor recovery capability;
- raw/full versus model-visible tool result separation;
- re-entrant reducer/effect loop for the direct-provider path;
- current chat `CompletionPolicy` and atomic/idempotent final product publication;
- current Hub/usage projections and Phase 0 behavior unchanged.

Phase 1 does **not** claim safe multi-worker takeover, parallel tool execution, compaction, child agents, recoverable external harness sessions or multiple native wire families.

The exact canonical types/invariants/fixtures are frozen in `docs/research/harness-v1/PHASE_1_CONTRACT.md`.

## 26. Ordered implementation / PR plan

Keep Cerebro runnable after every slice.

1. **PR 1 — canonical contracts and compatibility edges**
   - add canonical IDs/items/errors/model-profile/provider/external-agent/tool types;
   - add `ProviderAdapter` compatibility path for current OpenAI-compatible/LM Studio behavior;
   - introduce `ExternalAgentAdapter` boundary without durable CLI recovery;
   - no runtime ownership cutover yet.

2. **PR 2 — additive durable Harness store**
   - add new Harness migrations/CRUD for turns, events, snapshots, items, attempts and tool executions;
   - add versioned atomic transaction helpers using `run_in_writer()`;
   - do not repurpose `messages`, `tool_calls`, `audit_events` or product `tasks`.

3. **PR 3 — StepSnapshot + canonical tools/checkpoint barrier**
   - wrap existing CoreTools/MCP specs/bindings;
   - freeze exact tool plan/policy/binding generations per step;
   - implement provider finalized-item persistence and pre-side-effect checkpoint;
   - keep multiple tool calls sequential.

4. **PR 4 — reducer/effect direct-provider cutover**
   - move the OpenAI-compatible/LM Studio direct-provider path from `_generate` locals to durable reducer/effects;
   - implement attempt identity, replay decisions, tool uncertainty/resolution, monotonic recovery and cancellation truth;
   - preserve all Phase 0 behavior.

5. **PR 5 — product finalization and recovery hardening**
   - make accepted final message/silent outcome and terminal AgentTurn one idempotent durable decision;
   - add restart/crash-fixture coverage at provider/tool/finalization boundaries;
   - verify Hub remains projection-only and usage remains resilient telemetry.

6. **PR 6 — ContextManager/model-aware budgeting**
   - move `ContextBuilder` output behind typed context projection and versioned history;
   - still no compaction required.

7. **PR 7 — second native provider**
   - implement Gemini Interactions or Anthropic Messages as the first materially non-OpenAI wire family;
   - require opaque replay/native reference fixtures to pass through unchanged generic runner code.

8. **Later independent PRs**
   - compaction;
   - durable multi-worker ownership/fencing;
   - workspace/resource concurrency;
   - external-agent reconnect/orphan recovery;
   - child agents;
   - completion verifiers;
   - deferred tool search/artifact UX;
   - hard budget admission.

## 27. Acceptance bar

Harness v1 core is not proven by returning text from a native API. The durable direct-provider path must demonstrate:

1. a normal Cerebro wake creates one durable AgentTurn without creating a partial channel message;
2. one immutable StepSnapshot binds provider/model/history/tools/policy;
3. provider attempt identity exists before request dispatch;
4. streamed tool arguments remain non-executable until `OutputItemCompleted` plus replay/native references are durably checkpointed;
5. a side-effecting call moves durably through dispatch uncertainty and cannot be blindly duplicated after a crash;
6. a known ToolResult is monotonic and retained across later provider failure/retry;
7. a large raw result is retained separately from bounded model-visible output;
8. cancellation stops future work without rewriting already-known or indeterminate effects;
9. current topic PASS/silent and DM fail-closed semantics are unchanged;
10. final ordinary channel publication is exactly one completion-ordered row tied to terminal turn state;
11. deleting optional provider cache/conversation handles still permits provider-valid continuation when the adapter advertises stateless lossless replay;
12. an incompatible provider/model switch abandons active replay state before a fresh step and fences late old-attempt output;
13. the same generic runner can later satisfy equivalent fixtures with a materially different native provider adapter.

## 28. Explicitly deferred functionality

Deferred does not mean undefined. The contracts reserve required identities/versions now.

- **Multi-worker/takeover recovery:** later ownership epoch/fencing enforcement; no claim that current leases provide it.
- **Parallel tools:** later resource-aware conflict keys/commutativity proof; Phase 1 remains sequential.
- **Concurrent workspace mutation:** later isolated worktrees or resource/version preconditions.
- **Compaction:** later versioned checkpoint/trim logic; required replay scopes already pin data.
- **Subagents:** later idempotent child admission/lineage/descendant terminal policy.
- **External harness recovery:** later process/session identity, orphan reconciliation and reconnect semantics.
- **Hard budgets:** later durable reservation/admission; current usage remains best-effort telemetry.
- **Deferred/searchable tools and richer artifacts:** later after direct tool catalog semantics are proven.
- **Provider-hosted tools:** explicit adapter extension until a cross-provider semantic contract is justified.

## 29. Frozen architecture decisions

The following are no longer open questions for Harness v1 implementation:

- collaboration `messages` are not the canonical execution log;
- `Message.meta_json` is not provider replay state of record;
- `AgentTurn`/execution state is durable and separate from product messages/tasks;
- harness operation is a durable re-entrant reducer/effect loop;
- every inference uses an immutable `StepSnapshot`;
- direct `ProviderAdapter` and `ExternalAgentAdapter` are distinct;
- `ModelProfile` is versioned separately from provider configuration;
- canonical history is ordered `InferenceItem`s;
- required provider replay/native call references are durable;
- optional provider cache/conversation IDs are optimizations where stateless replay is lossless;
- generic reasoning visibility is summary-only;
- finalized output items are semantic authority, never streaming deltas;
- side-effecting tools require the durable pre-execution replay/snapshot checkpoint;
- MCP remains a tool source beneath Cerebro-owned tool policy/runtime;
- each admitted tool call has a stable Cerebro identity and monotonic durable resolution semantics;
- missing result after possible dispatch never means replay is safe;
- executor idempotency/reconciliation capability governs automatic repeat dispatch;
- provider retryability and semantic replay safety are separate;
- cancellation cannot falsify prior external effects;
- semantic progress never silently rewinds across committed effects;
- incompatible provider/model switches require explicit abandonment/fresh semantic boundary;
- transient Hub events and telemetry are not durable recovery truth;
- current `tool_calls` / `audit_events` are not silently repurposed;
- measured `budget_usage` and external-harness `agent_quota` keep distinct provenance;
- Phase 0 completion, tool sequencing, concurrency, TurnGuard, cancellation and usage behavior remains the compatibility bar.

Further design changes to these points require a new explicit architecture decision rather than incidental implementation drift.

## 30. Issue #210 contract clarification addendum

Issue #210 applies the accepted architecture-audit findings from
`review/harness-v1-architecture-audit@46865080a74a20f7406df506d7c6668ffdafc283` to this frozen
architecture. The detailed canonical field and fixture definitions are normative in
`docs/research/harness-v1/PHASE_1_CONTRACT.md` section 32. This addendum tightens ownership and
recovery semantics; it does not reopen any issue #206 decision.

### 30.1 Recovery has a named owner

`TurnCoordinator` owns the logical **`TurnRecoveryDriver`**. On process startup, before new wakes are
admitted for an agent, it scans non-terminal `AgentTurn`s in the active `execution_epoch` and drives
them from durable state through the recovery rules. Any turn Phase 1 cannot safely reconstruct or
resume becomes durably `suspended` with an explicit reason; a dead process may not leave it
indefinitely `running`.

### 30.2 Attempt ownership and format versioning are canonical

Every persisted `InferenceItem` carries its producing `InferenceAttemptId` when provider-originated,
plus its own `format_version`. `InferenceAttempt` and `ToolExecution` also carry their own
`format_version`.

Finalized provider output from an attempt that never reached authoritative `InferenceCompleted` and
authorized no dispatched side effect is attempt-scoped. On abandonment it is marked superseded,
excluded from later provider request history, and retained as audit evidence. Where a dispatched or
committed side effect exists, the causal prefix and committed tool resolutions needed to preserve
that effect remain active canonical history. Monotonic semantic progress across external effects is
unchanged.

### 30.3 Replay history has a conversation storage owner

`inference_items` is conversation-owned from the first durable schema and carries required
`AgentTurn` attribution. Turn-scoped history is a filtered view over that collection. This gives
`ReplayRetentionScope.conversation` a durable home without later re-keying and without putting
provider replay state into collaboration `messages` or `Message.meta_json`.

### 30.4 Causal admission distinguishes duplicate delivery from later occurrence

Duplicate-key loading applies only to the same admitted occurrence where the existing turn remains
the intended recoverable execution. Current DM and message-backed poll wakes use their durable
trigger message identity as the occurrence identity; explicit/manual turns and poll wakes without a
durable trigger use a durable explicit `occurrence_id`. A terminal prior occurrence cannot suppress
a legitimate later one. Re-delivery of the same terminal occurrence returns its recorded outcome,
and any intentional decline is durably recorded rather than silently dropped.

### 30.5 The pre-tool barrier includes the durable operation key

When a snapshotted executor binding relies on stable externally enforced idempotency, the
`stable_operation_key` is assigned and persisted before dispatch eligibility. The Phase 1 contract
now distinguishes facts committed in the atomic executable-barrier transaction from earlier durable
facts that the barrier verifies as preconditions. External dispatch remains impossible until the
whole precondition set is true and the atomic barrier has committed.

### 30.6 One causal wake has one execution authority

For one admitted `CausalWakeKey`, exactly one execution path may dispatch providers, dispatch client
tools, or insert collaboration/product rows. Legacy, compatibility or shadow paths may observe only
when they are mechanically non-side-effecting for that wake. This is a frozen Harness v1 safety
invariant, not a rollout implementation choice.

### 30.7 Indeterminate external effects have durable ownership and a discovery surface

An `AgentTurn` carries a durable authoritative projection of outstanding uncertain tool executions,
including an attention flag/count maintained transactionally with relevant `ToolExecution`
transitions. Turn cancellation or failure cannot implicitly resolve or hide
`dispatch_may_have_escaped` state. Phase 1 must provide a durable store/product/operator query that
surfaces turns needing attention and identifies the unresolved call without depending on transient
Hub delivery.

### 30.8 Product finalization has one discriminator

`product_outcome_kind` is the authoritative finalization/idempotency discriminator.
`final_message_id` is associated evidence for outcomes that publish a row and is never sufficient by
itself to decide that finalization did or did not occur. PASS/silent outcomes intentionally have no
final message. Any user-visible fail-closed error/failure publication participates in the same atomic
finalization transaction.

### 30.9 Phase 1 continuation is admitted only when durable replay is lossless

Phase 1 permits only adapter/model combinations whose correctness-required continuation state can be
losslessly represented and reconstructed from durable ordered `InferenceItem`,
`ProviderOpaqueItem`, and `ProviderCallRef` state. If a provider attempt cannot be reconstructed
safely, generic code does not invent replay: `reconcile_or_suspend` degenerates to durable
`suspend` unless the adapter has an authoritative reconciliation contract.

### 30.10 Security/storage gates move to the PR that first creates the data

The first adapter PR that can persist sensitive replay material must define its at-rest access,
classification, encryption where required, retention/deletion and redaction policy before that data
is created. For the Phase 1 OpenAI-compatible/LM Studio edge, PR 1 must explicitly state whether
such replay material is surfaced. PR 3 must define raw tool-output inline/artifact ownership,
retention, access, redaction and failure policy before raw tool output is persisted.

### 30.11 Acceptance set after clarification

The deterministic acceptance suite is F-01 through F-24. F-05, F-07 and F-14 are corrected to test
their intended crash/idempotency/binding-generation invariants, and F-21 through F-24 cover causal
admission, rollout single authority, orphaned in-flight attempt recovery and indeterminate-effect
visibility. The exact fixtures are frozen in `PHASE_1_CONTRACT.md` section 32.10.

### 30.12 Standing external-side-effect rule is unchanged

Cerebro still does not promise generic exactly-once external side effects. Once an external effect
may have escaped, automatic repeat dispatch is prohibited unless executor semantics prove read-only
behavior, idempotency, stable externally enforced idempotency, or authoritative reconciliation.
