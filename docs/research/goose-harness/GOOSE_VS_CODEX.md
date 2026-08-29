# Goose versus Codex harness architecture

## Comparison baselines

Goose source baseline:

- repository: `aaif-goose/goose`
- pinned commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`
- findings in this directory are classified **conceptual inspiration only**.

Codex comparison source:

- Cerebro issue #202 research branch: `research/codex-harness-mining`
- finalized Cerebro branch commit read for this comparison: `3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- that research pins upstream `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- Codex implementation was **not** re-mined for this document; this comparison reads the durable issue #202 artifacts under `docs/research/codex-harness/`.

No implementation source from either upstream has been copied or adapted into Cerebro.

## Main conclusion

Goose and Codex independently converge on most of the boundaries a durable agent harness needs:

- persistent task/conversation state is distinct from provider process state;
- model-visible context is a derived view of durable history/state;
- tools need registry/discovery, policy, execution and result semantics beyond a function schema;
- approvals/cancellation/failures must become explicit runtime state rather than disappear into exceptions;
- subagents should be real child execution identities with lineage and budgets;
- UI/server surfaces should sit outside the headless harness;
- model/provider finish is not the same thing as task acceptance/completion.

Their strongest differences are complementary rather than mutually exclusive.

**Codex** is stronger at freezing an immutable request-scoped execution contract (`StepContext` + exact `ToolRouter`) and at reconstructing rich thread/turn/world-state semantics from a durable rollout/event log.

**Goose's newer architecture** is stronger at expressing the control loop itself as an ordered, re-entrant operation machine over persisted state with explicit effects. Its provider ecosystem is also substantially more heterogeneous at the product boundary, including direct APIs, local inference, CLI-backed harnesses and ACP-backed external agents.

For Cerebro, the likely synthesis is: **Codex-style immutable step snapshots inside a Goose-style durable effect/re-entry loop**, while keeping Cerebro's provider and tool interfaces more strictly model-agnostic than either upstream.

## Comparison table

| Concern | Goose at pinned commit | Codex durable research | Cerebro implication |
| --- | --- | --- | --- |
| Core loop | Existing `Agent` loop plus experimental generic `goose-agent` persisted operation state machine | Mature `run_turn` loop over thread/session state | Use explicit durable transitions, but also freeze each inference/tool step |
| Request consistency | Operations re-enter after persisted effects; tool/context contributions recomputed for inference | Immutable `StepContext` captures exact environment/context/MCP/tool router used by resulting calls | Add a request-scoped `StepSnapshot` to the durable loop |
| Durable identity | SQLite session with conversation/config/parent session | Durable thread + turn + rollout items/events, reconstructable runtime | Cerebro should persist task/turn execution state beyond final chat messages |
| Context | Message visibility + summaries + tool-pair compaction; provider may own context | Typed context fragments + persisted/diffed World State + compaction checkpoints | Context should be a state reducer/view, not concatenated messages |
| Provider model | Broad `Provider` trait spans direct model APIs and external harnesses | Better config/runtime/model separation, but wire abstraction remains Responses-shaped | Use narrow native `ProviderAdapter`; model profile separate; external harness adapter separate |
| Tools | External MCP and Goose platform tools share `McpClientTrait`; dynamic cache/version | Canonical runtime registry + request-specific exposure/router; MCP is one source | Keep MCP behind Cerebro-owned catalog/planner/runtime |
| Large tool catalogs | Dynamic tool list/cache; no equivalent deferred-search architecture confirmed in examined Goose paths | Direct/deferred/hidden exposure with searchable deferred catalog | Adopt deferred exposure when catalog size requires it |
| Permissions | Explicit inspector chain: security/egress/adversary/permission/repetition; approval modes | Request-scoped sandbox/permissions, runtime checks, approval hooks | Policy must be independent from provider/tool transport |
| Shell/files | Built-in developer MCP extension; shell timeout/cancel/output spill; optional container | Structured exec pipeline with environment/sandbox/permission resolution; verified `apply_patch` | Build a structured Cerebro executor, not raw shell calls |
| Tool terminal results | Errors/denials/unknown calls can become model-visible tool results | Strong invariant: every admitted call reaches success/failure/denied/aborted terminal state | Make terminal `ToolResult` durable and identity-preserving |
| Retry/recovery | Typed provider errors; recipe verification retries; experimental retry metadata persists across reset | Distinct HTTP/stream/network/context/cancel/suspend-recover layers | Keep retry, recovery, context migration and acceptance separate |
| Completion | `ends_turn` plus max-turn/goal/grind/retry/error operations | Follow-up loop plus stop hooks/completion gates/review tasks | Provider `completed` is only an inference event; harness owns acceptance |
| Subagents | Fresh persisted `SubAgent` sessions; sync/background; default 25 turns; no recursive delegation | Durable child threads; parent/root turn lineage; V2 mailbox/residency/execution limiter | Child runs should be explicit durable tasks; collaboration messages need not trigger inference |
| UI/runtime | CLI/core/ACP server; Electron launches same `goose serve` backend | Multiple clients/app-server around shared headless core | Keep Cerebro UI/API outside harness core |
| Events/telemetry | Small `AgentEvent` stream + explicit effects + OpenTelemetry | Rich SQ/EQ typed lifecycle + durable rollout + status projections | Separate transient stream events, durable execution events, projections and telemetry |

## 1. Core control loop: different emphasis, compatible lessons

### Goose

Confirmed upstream paths:

- `crates/goose/src/agents/agent.rs`
- `crates/goose/src/agents/state_machine/mod.rs`
- `crates/goose-agent/src/machine.rs`
- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/session.rs`

The pinned Goose snapshot has two loop paths. The newer generic path remains explicitly experimental behind `GOOSE_STATE_MACHINE`.

Its key architectural idea is that each operation:

- checks whether it applies to current persisted state;
- returns explicit effects;
- those effects are persisted by a product-owned effect handler;
- the machine reloads state and starts another selection pass;
- operations can persist metadata notes to make behavior reconstructable after re-entry.

The operation list represents policy directly: steering, compaction, approval, tool execution, retries, commands, hooks, max turns and inference are peers in one ordered pipeline.

### Codex

Durable Cerebro sources read:

- `docs/research/codex-harness/ARCHITECTURE_MAP.md`
- `docs/research/codex-harness/RECOVERY_AND_VERIFICATION.md`

Codex's `run_turn` is a more conventional explicit outer model/tool/follow-up loop, but it captures a strong immutable `StepContext` for a particular sampling request. The exact model-visible tools and environment used for execution are frozen with the request that advertised them.

### Synthesis

These solve different failure classes.

Goose's re-entry/effect model improves **process reconstruction and policy composability**.

Codex's request snapshot improves **time-of-check/time-of-use consistency inside a single model step**.

Cerebro should use both invariants:

```text
load durable turn state
  > choose next harness transition
  > build immutable StepSnapshot
  > infer
  > execute resulting calls only against that snapshot
  > persist terminal effects/events
  > re-enter from durable state
```

## 2. Durable history and model context: strong independent convergence

### Goose

Confirmed paths:

- `crates/goose/src/context_mgmt/mod.rs`
- `crates/goose-context-management/src/*`
- `crates/goose/src/conversation/*`

Goose compaction does not simply delete history. Older messages can remain user-visible while becoming agent-invisible; an agent-only summary/continuation replaces them in active context. Tool-pair summarization separately compresses old tool traffic.

### Codex

Durable source: `docs/research/codex-harness/CONTEXT_AND_PROMPTS.md`.

Codex likewise separates durable rollout/history from the request view, but goes further with typed context fragments and persisted/diffed World State. Compaction is a history/state checkpoint that must reconcile governing context, not only produce a summary.

### Synthesis

This convergence is high-confidence evidence for Cerebro's architecture:

> **Persist the facts/events. Derive the provider context.**

Cerebro should not use the model-visible prompt/history as its durable source of truth.

Goose contributes a practical two-audience visibility model (`user` versus `agent`) and independent tool-output compaction.

Codex contributes typed mutable World State, provenance/versioning and explicit add/replace/remove synchronization.

A Cerebro `ContextManager` should combine both ideas independently: typed sections and provenance/version IDs, plus explicit UI/model visibility and compaction checkpoints.

## 3. Provider abstraction: both upstreams expose a caution

### Goose

Confirmed paths:

- `crates/goose-provider-types/src/base.rs`
- `crates/goose-provider-types/src/model.rs`
- `crates/goose/src/providers/*`
- `crates/goose/src/acp/provider.rs`

Goose genuinely accommodates heterogeneous backends. But its `Provider` contract can also represent another complete agent harness. ACP providers can own context, approvals and external sessions.

That makes the interface practical, but it merges two abstraction levels:

- model inference provider;
- sessionful external agent runtime.

### Codex

Durable source: `docs/research/codex-harness/PROVIDER_ABSTRACTION.md`.

Codex separates provider configuration, runtime behavior, model metadata, session-scoped client state and turn-scoped transport state more cleanly. However, at its pinned baseline the normalized wire contract is still fundamentally OpenAI Responses-shaped.

### Synthesis

Neither provider boundary should be copied directly.

Cerebro should independently define:

- `ProviderAdapter` — direct native inference API/engine;
- `ModelProfile` — model capabilities and harness policy;
- optional provider/account/session/turn adapter lifetimes;
- `ExternalAgentAdapter` — ACP/CLI/vendor harness when Cerebro deliberately delegates context/tool/session ownership to another harness.

That preserves Goose's backend diversity without collapsing external harness ownership into the direct-model interface, and preserves Codex's lifecycle separation without inheriting its Responses-shaped wire model.

## 4. Tool architecture: same layers, different protocol center

### Goose

Confirmed paths:

- `crates/goose/src/agents/mcp_client.rs`
- `crates/goose/src/agents/extension_manager.rs`
- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/agents/platform_extensions/*`

Goose centers MCP as the common interface. Its own developer tools implement the same client trait used by external MCP servers. `ExtensionManager` handles discovery, ownership metadata, name normalization, cache invalidation, transports and process lifecycle.

### Codex

Durable sources:

- `docs/research/codex-harness/TOOLS_AND_EXECUTION.md`
- `docs/research/codex-harness/MCP_TOOL_SEARCH_AND_OUTPUTS.md`

Codex centers a harness-owned canonical `ToolRegistry` / exposure plan / `ToolRouter`, with MCP as one tool source. It freezes exact bindings in `StepContext`, supports deferred/searchable catalogs and separates raw full output from bounded model-visible output.

### Synthesis

For Cerebro, Codex's center of gravity is a better fit:

```text
Cerebro ToolCatalog / ToolRuntime
        ^
        |
core tools | MCP tools | provider-hosted tools | collaboration tools
```

MCP should be an interoperability adapter, not Cerebro's internal universal object model. Goose still demonstrates that built-ins and MCP can share a uniform execution lifecycle, which is valuable.

The combined rules are:

- canonical structured tool identity;
- source/owner provenance;
- dynamic catalog version;
- request-scoped exposure and binding;
- no external shadowing of privileged tools;
- approval/policy above transport;
- one terminal result per admitted call;
- raw/artifact output separate from model-context representation;
- deferred/searchable exposure when catalogs are too large.

## 5. Permissions and safety: independent runtime enforcement

### Goose

Confirmed paths:

- `crates/goose/src/tool_inspection.rs`
- `crates/goose/src/permission/permission_inspector.rs`
- `crates/goose/src/security/security_inspector.rs`
- `crates/goose/src/security/egress_inspector.rs`

Goose makes policy visibly modular. Security, egress, adversary, permission and repetition inspectors return actions combined conservatively. User permission modes and persistent allow/deny choices are independent from tool transport.

### Codex

Durable sources:

- `docs/research/codex-harness/TOOLS_AND_EXECUTION.md`
- `docs/research/codex-harness/RECOVERY_AND_VERIFICATION.md`

Codex strongly binds tool authorization to the captured execution environment and sandbox/permission profile. Hooks can rewrite/block/approve calls, but runtime permissions remain authoritative.

### Synthesis

Both reject “the prompt told the model not to do it” as a security boundary.

Goose contributes a clean **multi-inspector policy pipeline**.
Codex contributes **snapshot-bound execution authorization and sandbox semantics**.

Cerebro should evaluate a call using policy modules against the immutable step snapshot, then send only a normalized execution grant to the tool runtime.

## 6. Filesystem and shell: Codex is more structured; Goose is operationally pragmatic

Goose's first-class developer extension provides write/edit/tree/image/shell, with working-directory scoping, timeouts, cancellation, live output, login-shell PATH handling and output spill-to-temp-file behavior.

Codex's durable research maps a more structured shell/edit pipeline: environment selection, sandbox/permissions, structured process lifecycle and a dedicated parse/validate/authorize/apply/diff path for `apply_patch`.

For Cerebro, the useful conclusion is not “copy Codex shell.” It is that a mature coding harness needs a Cerebro-owned execution service beneath tools. Goose's cross-platform/path/process details are useful operational evidence; Codex's structured permission/edit semantics are the safer architecture target.

## 7. Recovery: Goose makes retry a pipeline operation; Codex has richer lifecycle layers

### Goose

Confirmed paths:

- `crates/goose-provider-types/src/errors.rs`
- `crates/goose/src/agents/state_machine/ops_retry.rs`
- `crates/goose/src/agents/state_machine/ops_exit_on_error.rs`
- `crates/goose/src/agents/state_machine/ops_maxturns.rs`

Provider errors are typed. Recipe verification retry is a separate semantic layer. In the newer state machine, retry attempt metadata is persisted before a conversation reset so reconstruction does not lose the attempt count.

### Codex

Durable source: `docs/research/codex-harness/RECOVERY_AND_VERIFICATION.md`.

Codex more fully separates HTTP retry, sampling-stream retry, connection-wait behavior, transport fallback, compaction, cancellation, explicit unfinished-turn suspension/recovery and persistence flush semantics.

### Synthesis

Cerebro should keep a typed recovery decision layer. A durable loop transition should say what changed:

- retry same semantic sample after transient transport loss;
- back off rate limit;
- rebuild after compaction;
- yield for approval;
- suspend for worker handoff;
- abort/cancel permanently;
- retry task after failed completion evidence;
- fail terminally.

A generic “retry count” is not enough.

## 8. Completion and verification: strong convergence

Goose's `ends_turn` is only an initial condition. Goal/grind operations, recipe success checks, max-turn policy and errors can keep the machine running or yield.

Codex similarly allows stop hooks to block completion and inject feedback; reviewer workflows are explicit rather than automatically equated with normal completion. Its research explicitly distinguishes prompt advice to test from harness-enforced acceptance.

Cerebro should therefore model a provider's end event as **inference completion**, then invoke a separate `CompletionPolicy` that can return something like:

- `allow`;
- `continue_with_feedback`;
- `yield_to_user`;
- `fail`.

This is one of the clearest independent convergences across the two harnesses.

## 9. Sessions/events: Codex is richer today; Goose's experimental loop is simpler to extract

### Goose

Confirmed paths:

- `crates/goose/src/session/session_manager.rs`
- `crates/goose-agent/src/events.rs`
- `crates/goose-agent/src/operation.rs`

Goose has durable SQLite sessions plus a small runtime `AgentEvent` surface. The state machine's explicit effects contain more semantic transition detail than the event stream itself.

### Codex

Durable source: `docs/research/codex-harness/SESSIONS_EVENTS_AND_MULTIAGENT.md`.

Codex separates durable thread, live session/runtime, turn, typed command/event protocol, rollout replay and status projections. It also represents rollback/fork/suspend/recover as durable lifecycle concepts.

### Synthesis

Cerebro's collaborative product makes the richer distinction necessary:

- durable `AgentTask` / `AgentTurn` identity;
- append-only or replayable execution events/checkpoints;
- query-efficient status projections;
- transient provider deltas/UI events;
- telemetry traces/metrics as a separate plane.

Goose's explicit effect model can be used as the reducer input; Codex's event/replay distinction shows how much state should survive process loss.

## 10. Multi-agent: both make children real; Codex moves closer to Cerebro's collaboration model

### Goose

Confirmed paths:

- `crates/goose/src/agents/subagent_task_config.rs`
- `crates/goose/src/agents/subagent_handler.rs`
- `crates/goose/src/agents/platform_extensions/summon.rs`

Goose child tasks are persisted `SubAgent` sessions with selected provider/model/extensions/working directory and bounded turn count. Delegation can be synchronous or background. Recursive delegation is explicitly blocked in the examined path.

### Codex

Durable source: `docs/research/codex-harness/SESSIONS_EVENTS_AND_MULTIAGENT.md`.

Codex also uses real child threads, but its V2 architecture additionally separates:

- agent identity from runtime residency;
- mailbox delivery from triggering a provider turn;
- queued existence from active execution capacity;
- parent/root causal lineage;
- message/follow-up/interrupt/resume lifecycle.

### Synthesis

The independent convergence is that subagents should **not** be hidden nested calls with no durable identity.

For Cerebro, Codex V2's communication/scheduling split is especially relevant because the product is Slack-like: an agent message can be persisted and displayed without automatically consuming a model turn. Goose's explicit depth/budget/extension inheritance is useful policy input.

## 11. UI/server boundaries: same architectural direction

Goose desktop runs the same backend by launching `goose serve` and connecting over ACP/WebSocket. The CLI and desktop therefore share core agent/session behavior.

Codex exposes its core through an app-server/protocol boundary used by multiple clients.

Cerebro already wants a web collaborative interface. Both upstreams support the same rule: **the visible client owns presentation and interaction, not the agent loop's source of truth**.

## 12. What appears Goose-specific rather than generally convergent

These are useful Goose design choices but should not be treated as consensus simply because Goose implements them:

- a single `Provider` interface spanning direct inference APIs and external agent harnesses;
- MCP as the common internal client trait even for first-party platform tools;
- the exact inspector order/modes (`Auto`, `Approve`, `SmartApprove`, etc.);
- one-level delegation restriction;
- hiding old transcript messages using user/agent visibility flags as the primary compaction representation;
- the exact ordered operation list in the experimental state machine.

They are evidence/options, not requirements.

## 13. What appears Codex-specific rather than generally convergent

From the durable issue #202 research:

- OpenAI Responses-shaped canonical wire/event/history types;
- exact World State section catalog and AGENTS.md conventions;
- exact `apply_patch` grammar/runtime;
- Code Mode;
- Codex V1/V2 collaboration tool names and lifecycle protocol;
- exact deferred-search BM25 implementation;
- exact sandbox/permission model.

Again, take the boundary or invariant, not the implementation.

## 14. High-confidence convergence set for Cerebro

These conclusions are independently supported by both mined harnesses and fit Cerebro's stated direction:

1. **Cerebro owns durable task/turn/session state.** Provider SDK/process state is replaceable.
2. **Model context is derived from durable state.** Compaction changes the derived view/checkpoint, not the historical truth.
3. **Every inference uses an explicit model capability profile.** Provider identity alone is insufficient.
4. **Every tool call has canonical identity, runtime policy and one terminal outcome.**
5. **Tool exposure is not equivalent to tool installation/connection.** It is a request/policy decision.
6. **Approvals, permissions and sandbox/egress checks are runtime-enforced.** Prompts are not authority.
7. **Cancellation and recovery are lifecycle states.** They are not merely exceptions/future cancellation.
8. **Provider completion is not task acceptance.** Completion/evidence policy is separate.
9. **Child agents/tasks have durable lineage, budgets and explicit execution configuration.**
10. **UI/client surfaces observe/control a headless harness.** They do not own execution truth.
11. **Raw tool/runtime results and model-visible bounded representations should be different objects.**
12. **Transient streaming events, durable execution events/state and telemetry should be distinct planes.**

## 15. The architecture that the two research passes jointly suggest

Conceptually, not as a copied implementation:

```text
Cerebro product / workspace / channels
             |
       TurnCoordinator
             |
       durable AgentTurn
             |
        Harness reducer
  ordered policy/state transitions
             |
      immutable StepSnapshot
   context + model + tools + grants
             |
       ProviderAdapter
             |
      InferenceEvents
             |
       ToolPlanner/Runtime
             |
 terminal ToolResults / durable events
             |
        re-enter reducer
             |
       CompletionPolicy
             |
     final workspace result
```

This preserves the best convergence while remaining independently designed and model-agnostic.
