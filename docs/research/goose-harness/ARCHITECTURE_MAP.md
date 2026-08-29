# Goose harness architecture map

Upstream: `aaif-goose/goose`

Pinned commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification for implementation-relevant findings: **conceptual inspiration only**.

## Executive map

At this snapshot Goose is in the middle of an architectural transition. The established product agent still lives in `crates/goose/src/agents/agent.rs`, while a newer generic loop in `crates/goose-agent/` implements an ordered, re-entrant state machine over persisted conversation state. The new path is explicitly experimental behind `GOOSE_STATE_MACHINE` (with bang-shell commands forcing that path), so it should not be described as the sole production loop.

The important architectural split is:

1. **Surfaces** — CLI, desktop, ACP/server-facing clients collect input and select/create/resume sessions.
2. **Product agent** — `crates/goose/src/agents/agent.rs` owns Goose policy/configuration: provider selection, extensions, prompt construction, approvals/inspection, hooks, retries, steering, container state.
3. **Generic control-loop seam** — `crates/goose-agent/` defines a persisted machine, operations, inference input aggregation, effects, events, cancellation, and yield semantics.
4. **Provider boundary** — `crates/goose-provider-types/` defines provider/model contracts; `crates/goose-providers/` plus product provider modules implement direct APIs and harness-backed providers.
5. **Tool boundary** — MCP is the common protocol shape. External MCP extensions and Goose-owned platform extensions both implement the same client trait and are managed through `ExtensionManager`.
6. **Durable state** — `SessionManager` persists sessions/conversations in SQLite and applies state-machine effects between steps.
7. **Observability** — agent events are a compact runtime event stream, while tracing/OpenTelemetry records model, usage and tool-call details.

## Inbound request > context > model > tools > follow-up > completion

### 1. Surface chooses a session and runtime mode

Confirmed source:

- `crates/goose-cli/src/cli.rs`
- `crates/goose-cli/src/session/*`
- `ui/desktop/src/main.ts`
- `ui/desktop/src/gooseServe.ts`
- `crates/goose/src/acp/server.rs`

The CLI supports interactive sessions, one-shot runs, resume, ACP, MCP helpers, and an HTTP/WebSocket `serve` surface. The desktop Electron main process finds the Goose binary, chooses an available loopback port, injects `GOOSE_SERVER__SECRET_KEY`, starts `goose serve`, health-checks `/status`, and connects to `/acp` over WebSocket. This makes the desktop primarily a client/process supervisor around the shared Rust runtime rather than an independent harness implementation.

There is no separate `crates/goose-server` directory at the pinned commit; earlier Goose lineages or documentation may use “goosed/server” terminology, but source-level claims here follow this snapshot.

### 2. Agent receives a persisted session plus user kickoff

Confirmed source:

- `crates/goose/src/agents/agent.rs`
- `crates/goose/src/session/session_manager.rs`
- `crates/goose/src/agents/types.rs`

`Agent` is configured with a `SessionManager`, permission manager, optional scheduler, platform (desktop/CLI), MCP host capabilities, login-shell behavior and subagent status. Sessions persist conversation, provider/model, Goose mode, extension state, usage/cost, recipe/schedule/project information and parent session id.

### 3. The control loop evaluates ordered operations

Confirmed source:

- `crates/goose/src/agents/state_machine/mod.rs`
- `crates/goose/src/agents/state_machine/session.rs`
- `crates/goose-agent/src/machine.rs`
- `crates/goose-agent/src/operation.rs`

The generic state machine scans ordered operations and applies the first applicable result. Important properties:

- it reloads the session between iterations;
- operations return explicit effects rather than mutating the durable conversation directly;
- the product `SessionManager` applies those effects, then the machine re-enters from persisted state;
- operations can leave metadata notes on messages so a rebuilt pipeline recognizes work already performed;
- an operation may yield to the client, ending the current machine run without implying the overall session is finished;
- cancellation is shared through a `CancellationToken` and forces an applied step to yield.

Goose's concrete pipeline includes steering, max-turn enforcement, bang-shell handling, compaction, tool-pair compaction, approval, doctor/project/recipe/skills/slash-command behavior, hooks, retries, tool execution, unknown-tool handling and inference. `Agent::reply` remains the composition root because these policies depend on product configuration.

### 4. Operations contribute the next inference input

Confirmed source:

- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/*`
- `crates/goose/src/agents/prompt_manager.rs`

Before inference, the state machine asks operations for:

- `inference_tools()` — tool definitions;
- `prompt_parts()` — system-prompt contributions;
- `moim_parts()` — model-oriented injected metadata/context.

The inference step receives the aggregate. This turns prompt/tool composition into a property of the operation pipeline rather than a giant hard-coded caller argument list.

### 5. Context policy runs only when Goose owns context

Confirmed source:

- `crates/goose/src/context_mgmt/mod.rs`
- `crates/goose-context-management/`
- `crates/goose-provider-types/src/base.rs`

A provider can return `manages_own_context() == true`. In that case Goose disables its normal compaction path. ACP-backed providers do this (`crates/goose/src/acp/provider.rs`). When Goose owns context, it uses model/provider context-limit information, usage metadata or estimation, threshold-based compaction and optional old tool-pair summarization.

Compaction distinguishes durable history from active model context: old messages remain persisted/user-visible but become agent-invisible, while an agent-only summary and continuation replace them in the model-visible history.

### 6. Provider streams the assistant turn

Confirmed source:

- `crates/goose-provider-types/src/base.rs`
- `crates/goose-provider-types/src/model.rs`
- `crates/goose-providers/src/*`
- `crates/goose/src/providers/*`

The core provider contract is streaming-first. It receives model config, system prompt, messages and tools and yields a `MessageStream`. Provider adapters expose capabilities such as provider-owned context/session resume, permission routing, reasoning/thinking support, context/cost metadata and optional fast models.

Goose's provider registry contains direct HTTP/API adapters, local inference, OAuth-backed services, CLI/harness-backed providers and ACP-backed agents. This is broader than a pure “LLM API” abstraction.

### 7. Tool requests are inspected, approved and dispatched

Confirmed source:

- `crates/goose/src/tool_inspection.rs`
- `crates/goose/src/permission/permission_inspector.rs`
- `crates/goose/src/security/security_inspector.rs`
- `crates/goose/src/security/egress_inspector.rs`
- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/agents/extension_manager.rs`

Tool requests flow through an ordered inspector chain. At agent construction Goose installs security, egress, adversary, permission and repetition inspectors. Inspector outcomes are mixed conservatively: an `Allow` from one inspector does not override another inspector's deny/approval requirement.

Permission modes include Chat, Auto, Approve and SmartApprove. SmartApprove can trust read-only MCP annotations or ask an LLM to classify uncached calls as read-only. Explicit per-tool user permissions take precedence.

Calls that require approval produce a user-only `ActionRequired` message and suspend execution until the confirmation router receives a decision. Persistent AlwaysAllow/NeverAllow choices update the permission manager. ACP providers can instead advertise provider-side permission routing.

### 8. Tool execution is protocol-normalized but product-policy-heavy

Confirmed source:

- `crates/goose/src/agents/mcp_client.rs`
- `crates/goose/src/agents/extension_manager.rs`
- `crates/goose/src/agents/platform_extensions/developer/mod.rs`
- `crates/goose/src/agents/platform_extensions/developer/shell.rs`

External MCP servers and Goose platform extensions implement the same `McpClientTrait` (tools plus optional resources/prompts/notifications/MOIM). Tool calls carry session id, working directory and tool-request id context.

The built-in developer extension exposes write, edit, shell, tree and image-read tools. The shell tool chooses platform-appropriate shell semantics, supports configured/login-shell PATH behavior, timeouts and cancellation, streams output notifications, caps displayed output and spills long output to temporary files.

### 9. Tool results re-enter the same persisted loop

Confirmed source:

- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/session.rs`
- `crates/goose/src/agents/state_machine/ops_toolcalling.rs`

Tool responses are appended as conversation effects. The next machine iteration reloads that conversation, letting another operation or inference step become applicable. This is the core follow-up mechanism: tool execution is not a nested provider callback; it is another persisted transition.

### 10. Completion is a policy result, not only a provider finish reason

Confirmed source:

- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/ops_maxturns.rs`
- `crates/goose/src/agents/state_machine/ops_retry.rs`
- `crates/goose/src/agents/state_machine/ops_exit_on_error.rs`

An assistant message ends a normal turn only when it has no error and contains no tool request/action-required content. Even then, later operations can intervene: goals/grind can inject another hidden user nudge, recipe success checks can reset and retry the turn, max-turn logic can yield a continuation question, or a trailing error can force yield.

So “provider stopped” and “agent task completed” are deliberately different concepts.

## State and event representation

Confirmed source:

- `crates/goose-agent/src/events.rs`
- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/conversation/*`
- `crates/goose/src/agents/gen_ai_telemetry.rs`

The generic event surface is intentionally small:

- `Message`
- provider `Usage`
- per-message usage
- MCP notification
- `HistoryReplaced`

Durable transitions are richer than emitted events: effects can append messages, replace the conversation, patch tool-request metadata, change message visibility and, in Goose-specific effects, update recipe/extension/usage state.

OpenTelemetry/tracing records standardized GenAI request/response/model/token/tool attributes. Message/tool content capture is opt-in through `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`, reducing accidental content capture by default.

## Architectural interpretation for Cerebro

The strongest generalizable decision is not any particular loop body. It is the separation of **durable conversation/session state**, **ordered policy operations**, **explicit effects**, **provider inference**, and **client yield**. That structure makes cancellation, approval, compaction, retries and delegation reconstructable from persisted state.

A second useful lesson is negative: Goose's provider boundary is intentionally broad enough to encompass another agent harness (ACP), which causes provider-specific ownership of context, approvals and session state to leak upward. Cerebro should preserve the capability concept, but may want a cleaner distinction between a direct model provider and an external-agent/harness adapter.

These are architectural observations only. No Goose implementation code should be copied or adapted in this phase.
