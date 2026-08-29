# Harness v1 migration touchpoints

Issue: #207

Source baseline: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

This is a source-touch inventory. It identifies where a Harness v1 implementation is likely to meet current Cerebro; it does not decide the final architecture reserved for #206.

## Phase 1-critical touchpoints

### `cerebro/runtime.py`

Current symbols:

- `AgentRuntime.__init__`
- `AgentRuntime.run_turn`
- `AgentRuntime._generate`
- `AgentRuntime._run_tool`
- `AgentRuntime._context`
- `AgentRuntime._status`
- `AgentRuntime._post_system`
- `AgentRuntime._fail`
- `Completion`
- `is_pass`
- local `Persistence` protocol

Why it is the primary seam: `AgentRuntime` currently owns nearly every harness responsibility in one call tree: guard admission, provider resolution, context, provider concurrency, streamed inference, reasoning handling, tool protocol accumulation, tool execution, usage, completion policy, collaboration persistence, errors and Hub publication.

Likely migration boundary: preserve `run_turn(agent, channel_id, turn_id, depth, quote_msg_id)` or an equivalent service-facing entry point while the interior is decomposed. The exact replacement API is a #206 decision.

Behavior that must not be accidentally lost:

- no partial collaboration message rows during generation;
- completion-order persistence under concurrent turns;
- PASS/silent/DM completion policy;
- private reasoning handling;
- final/error event envelopes;
- cancellation signal propagation;
- bounded tool-loop behavior until replaced by explicit durable semantics.

Critical current weakness for migration: `_generate()` owns all intermediate state in locals. Tool-call protocol messages are synthesized into the local `transcript` and disappear on process loss.

### `cerebro/providers/base.py`

Current symbols:

- `ToolSpec`
- `Params`
- `Provider.stream(messages: list[Message], tools: list[ToolSpec], params: Params)`

Why touched: this protocol is the current inference abstraction but is not provider-neutral enough for #206 because its history type is the collaboration `Message` model and its params are chat-completions-shaped.

Likely migration boundary: adapter interface between canonical inference history/snapshot and provider-native request/response handling.

### `cerebro/providers/openai_compatible.py`

Current symbols:

- `OpenAICompatibleProvider`
- `OpenAICompatibleProvider.stream`
- `OpenAICompatibleProvider.resolve_model`
- `to_chat_messages`
- `_role_for`
- `_meta`
- `_tools_payload`
- `ProviderError`, `ProviderUnavailable`

Why touched: this file contains most explicit OpenAI-chat assumptions and current tool-protocol reconstruction from `Message.meta_json`.

Likely migration seam: keep OpenAI-compatible translation inside an adapter rather than allowing these shapes to define canonical history. Native OpenAI/Anthropic/Gemini work from #204 will need to meet the same higher-level boundary, but #207 makes no provider design decision.

### `cerebro/providers/lmstudio.py`

Current symbol: `LMStudioProvider(OpenAICompatibleProvider)`.

Why touched: LM Studio must keep working as Cerebro’s existing OpenAI-compatible/local path even if native provider adapters are added. It is a compatibility adapter, not evidence that all providers should be normalized through `/chat/completions`.

### `cerebro/providers/cli_agent.py`

Current symbols:

- `CliAgentProvider`
- `CliAgentProvider.stream`
- `render_prompt`
- `parse_cli_output`
- `BACKENDS`
- `OUTPUT_FILE_FLAG`

Why touched: this is an external agent harness disguised as a `Provider`. It executes Claude/Codex/Antigravity/Goose subprocesses, flattens Cerebro history into text and parses harness output.

Likely migration seam: classify this boundary separately from native provider inference, preserving subprocess/cwd/timeout/cancellation/output behavior. Exact `ExternalAgentAdapter` API belongs to #206.

### `cerebro/service.py`

Current symbols:

- `build_runtime`
- `_provider_for`
- `_profile_of`
- `_tools_for`
- `_run_tool`
- `_polling_agents`
- `_channels_for`
- `_latest_message_id`
- `RuntimeService.start/stop/_run/_consider/_responder/_poll_turn`

Why touched: this is the composition root for runtime/provider/context/tool policy and the owner of live turn tasks. It is also the boundary between collaboration wake policy and harness execution.

Likely migration seam: continue to let service decide when an agent gets a turn, then invoke the Harness v1 entry point. Provider/model/tool construction currently embedded here is likely to move behind narrower factories/registries, but #207 does not prescribe them.

Important coupling:

- `_provider_for` hard-codes provider-name dispatch and creates a fresh provider/CLI adapter instance per turn;
- `_profile_of` reads trust/policy from disk;
- module-global `CoreTools` is constructed without a Hub;
- `RuntimeService._turns` is the live cancellation ownership set;
- service has both Hub-driven DM dispatch and poller-driven channel wake.

### `cerebro/context.py`

Current symbols:

- `ContextBuilder.build`
- `ContextBuilder._fit_history`
- `identity`, `manual`, `channel_frame`, `scratchpad`, `memory`
- `Section`

Why touched: this is already a coherent context boundary, but its output is `list[Message]` and budgeting is based on approximate body-character counts.

Likely migration seam: preserve context-source collection/budgeting behavior while changing the target projection to canonical inference items or a request snapshot. Exactly one system message should be treated as current chat-template compatibility behavior, not automatically as canonical representation.

### `cerebro/persistence.py`

Current symbols:

- `StoreAdapter`
- `append_message`
- `history`
- `system_prompt`
- `channel`
- `members`
- `_message_fields`

Why touched: this is the cleanest existing runtime-to-storage adapter. Today it exposes collaboration messages only; Harness v1 durable turn/checkpoint state will need additional persistence ownership somewhere.

Likely migration seam: keep collaboration persistence behind this or a neighboring adapter while introducing durable harness persistence. Do not make channel `Message` the only durable turn representation merely because this adapter already exists.

### `cerebro/db.py`

Current symbols:

- `connect`, `migrate`, `fetch_one`, `fetch_all`, `enqueue_write`
- `run_in_writer`
- `_writer_consumer`

Why touched: any durable turn/replay/tool-checkpoint schema uses this transactional base.

Most relevant existing primitive: `run_in_writer(fn)` can atomically commit multiple changes under `BEGIN IMMEDIATE`. This is the current seam capable of supporting #206’s “checkpoint before side effect” requirement once a schema is chosen.

### `cerebro/store.py` / migrations / `cerebro/models.py`

Current relevant symbols/models:

- message CRUD
- task CRUD
- lease CRUD
- `Message`, `ToolCall`, `AuditEvent`, `BudgetUsage`, `Agent`
- schema/migrations 001–004

Why touched: durable Harness v1 state does not exist. `tool_calls`/`audit_events` are schema stubs from the harness perspective, not wired execution state.

Likely migration seam: additive/compatibility-aware schema evolution rather than redefining collaboration-message meaning in place. Exact tables are #206/implementation decisions.

### `cerebro/tools.py`

Current symbols:

- `CoreTools`
- `CoreTools._build`
- `CoreTools.tier_of`
- `CoreTools.specs_for`
- `CoreTools.execute`
- `_home`
- `_confined_path`
- `_resolve_safe_fs_path`
- individual collaboration/task/fs/memory tool handlers

Why touched: current ToolCatalog, part of ToolPolicy, ToolRuntime and confinement are co-located here.

Likely migration seam: preserve both catalogue-time filtering and execution-time enforcement. Any new Harness v1 tool planner/runtime must still route into Cerebro-owned tools rather than provider-owned execution.

### `cerebro/mcp.py`

Current symbols:

- `MCPServerConfig`
- `StdioMCPClient`
- `MCPRegistry`
- `MCPRegistry.filter_specs_for_agent`
- `MCPRegistry.execute`
- `CompositeToolExecutor`

Why touched: current MCP transport and tool-name routing are already separate from provider inference, but policy/catalog/execution are mixed across registry, profile and CoreTools.

Likely migration seam: `CompositeToolExecutor.specs_for/execute` is the current aggregate catalog/execution boundary.

### `cerebro/turnguard.py`

Current symbols:

- `TurnLimits`
- `TurnState`
- `TurnGuard`
- `AgentRateLimiter`
- `new_turn_id`

Why touched: turn lifecycle limits become problematic when turn state becomes durable/re-entrant. Current state is purely process-local and `check()` is admission-by-inspection, not a durable claim/reservation.

Likely migration seam: preserve configured ceilings, move/reconcile state ownership with durable turn lifecycle as decided in #206.

### `cerebro/hub.py`

Current symbols:

- `Hub.publish/subscribe`
- `Event`
- `Subscription`

Why touched: current runtime publishes both user-visible telemetry and facts used internally for immediate dispatch. Hub is lossy by design and process-local.

Likely migration seam: final/streaming outward projection from Harness v1 into current event envelopes. Do not equate Hub events with durable semantic execution events.

## Product-layer touchpoints that should stay above the harness

### `cerebro/api/routes_channels.py`

Relevant symbols:

- `post_channel_message`
- `get_channel_messages`
- channel/member mutation and read-cursor routes

Current behavior: authenticated messages are persisted, then `message.new` is published. Agent membership is enforced at the route. These routes should not need provider-native knowledge.

Migration concern: `messages` remains the public collaboration history. Harness persistence should not silently change the API payload schema without an explicit product decision.

### `cerebro/api/ws.py::websocket_endpoint`

Current behavior: inbound authenticated `message.send/message.new` is persisted then published; outbound pump forwards Hub envelopes. It should consume collaboration/runtime projections, not reducer internals.

### `cerebro/poller.py::ChannelPoller`

Current behavior: product wake policy based on channel message movement. It should invoke the harness rather than become part of it.

Migration concern: polling state is memory-only, so durable Harness v1 re-entry does not by itself make wake delivery restart-durable.

### `cerebro/usage.py`

Current symbols:

- `record_turn_usage`
- `report_quota`
- `board`

Current behavior: aggregate measured provider usage is deliberately distinct from self-reported CLI-harness quota. Preserve this provenance regardless of adapter reclassification.

## Secondary/later touchpoints

- `cerebro/agents_loader.py`: seeded/disk agent configuration becomes relevant if model/provider config is normalized.
- `cerebro/config.py`: global provider concurrency/history/tool-loop settings currently feed service/runtime directly.
- `cerebro/prompts/operating_manual.md.j2`: collaboration/operating rules are context input above provider adapters.
- `cerebro/transcript_import.py`: imported messages use `meta_json` for source provenance; relevant if `meta_json` semantics are narrowed.
- `cerebro/api/routes_usage.py`: external-harness quota provenance; mostly independent of Phase 1 harness internals.
- `cerebro/api/leases.py` and lease store methods: existing durable coordination pattern, not directly a turn-state implementation.

## Cross-cutting sequencing constraints exposed by current code

These are migration constraints, not a final implementation sequence.

1. Provider/history abstraction cannot be changed in isolation: `Provider.stream`, `ContextBuilder`, `FakeProvider`, `OpenAICompatibleProvider`, runtime tool-loop transcript and tests all share `Message`.
2. Tool durability cannot be solved only in `tools.py`: admission happens in `AgentRuntime._run_tool`, provider protocol items are assembled in `_generate`, and current `tool_calls` persistence is unused.
3. Re-entry cannot be added only to `RuntimeService`: the state that must survive is inside `AgentRuntime._generate` locals and provider-specific protocol state.
4. Cancellation semantics span `RuntimeService._turns` > `AgentRuntime.run_turn` > provider stream > `CliAgentProvider._terminate` for external harnesses.
5. Changing `messages` has product consequences across REST, WS, polling, read cursors, context and transcript import.
6. Separating external harnesses from native providers touches service selection and runtime adapter invocation but should not change channel wake policy.
7. Durable semantic events must coexist with lossy Hub telemetry; replacing Hub with an event store would be a product architecture decision beyond this inventory.

## Phase classification

### Phase 1-critical

- runtime turn state/re-entry boundary;
- provider adapter/history boundary;
- OpenAI-compatible/LM Studio compatibility adapter;
- explicit external-agent adapter boundary;
- immutable request snapshot inputs;
- context projection to canonical history;
- durable turn/provider/tool/checkpoint persistence;
- tool admission/runtime outcome semantics;
- guard/cancellation/recovery integration;
- service composition while preserving wake policy;
- outward event compatibility.

### Later or independent unless #206 pulls them forward

- product task schema/tool UX;
- usage board presentation and external quota UI;
- audit/revert product feature semantics;
- poller restart durability beyond the harness;
- broader channel/API redesign;
- unrelated legacy `tool_plugins/` framework.
