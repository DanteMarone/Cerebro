# Cerebro takeaways from Goose harness research

Goose upstream baseline: `aaif-goose/goose@8ae4e4ba02836529790f47109b8785e8b42843a7`

Codex comparative research source: Cerebro `research/codex-harness-mining@3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`, whose upstream baseline is `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`.

All implementation-relevant ideas in this document are classified **conceptual inspiration only**. No Goose or Codex implementation code has been copied or adapted into Cerebro by this research branch.

## Main recommendation

Cerebro should own a durable, provider-neutral execution state machine/reducer beneath the Slack-like product layer, but it should not copy Goose's state machine or Codex's turn loop.

The combined research suggests this invariant:

> A Cerebro agent is a durable Cerebro identity operating on durable Cerebro task/workspace state. Each provider inference is a replaceable step over an immutable snapshot. Tools, approvals, recovery and completion are Cerebro-owned transitions whose outcomes are durably recorded before the next step.

The most useful synthesis is:

- **Goose direction:** re-enter the harness from persisted state after explicit effects;
- **Codex direction:** freeze the exact context/model/tool/permission view for one inference and every tool call produced by it;
- **Cerebro direction:** combine both while keeping direct model adapters and external-agent adapters separate.

## Tier 1: architecture invariants to carry forward

### 1. Durable turn state should be the source of truth

Goose evidence:

- `crates/goose-agent/src/machine.rs`
- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/session.rs`
- `crates/goose/src/session/session_manager.rs`

At the pinned commit the generic state-machine path is experimental, but its direction is important: operations return effects, effects are persisted, the session reloads, and the loop re-enters from durable state.

Cerebro should independently implement durable `AgentTurn` state plus sparse execution events/checkpoints. The in-memory coroutine, WebSocket, worker process or provider session must not be the only thing that knows what happens next.

### 2. Add an immutable request-scoped `StepSnapshot`

Goose's new loop does not by itself provide the strongest time-of-check/time-of-use invariant found in Codex. Cerebro should add one explicitly.

A step snapshot should freeze at least:

- durable turn/version id;
- effective provider + model profile;
- canonical model-visible context version;
- exact tool catalog/exposure/binding version;
- working directory/environment;
- effective permission/safety grants;
- output/reasoning policy;
- trace/causal ids.

Any tool call emitted by that inference must execute against the snapshot that advertised the tool, not a newer mutable catalog or permission state.

### 3. Persist history; derive context

Goose evidence:

- `crates/goose/src/context_mgmt/mod.rs`
- `crates/goose-context-management/src/*`
- `crates/goose/src/conversation/*`

Goose preserves old transcript history while changing model visibility and inserts agent-only summary/continuation content. Codex independently treats compaction as a state/history transition.

Cerebro should have a `ContextManager` that derives provider-specific model context from durable events/history. It should support:

- independent human/UI versus model visibility;
- typed mutable world/execution state;
- compaction checkpoints;
- tool-output summarization/truncation;
- model-switch context reconciliation;
- provenance/version ids for injected instructions/state.

Do not make a provider's current serialized prompt the canonical task history.

### 4. Separate direct model providers from external agent runtimes

Goose evidence:

- `crates/goose-provider-types/src/base.rs`
- `crates/goose-provider-types/src/model.rs`
- `crates/goose/src/acp/provider.rs`

Goose's `Provider` abstraction can represent both a direct model API and an external ACP agent that owns context, approvals and session state. That flexibility is useful evidence, but it makes ownership ambiguous.

Cerebro should instead define separate contracts:

```text
ProviderAdapter
  native model inference API/engine
  provider auth + wire format + streaming + error translation

ExternalAgentAdapter
  another harness/runtime
  may own context/tool/session/approval semantics explicitly
```

Both can emit Cerebro-normalized lifecycle events, but the second should not masquerade as a stateless model provider.

### 5. Keep `ModelProfile` separate from provider identity

Goose evidence:

- `crates/goose-provider-types/src/model.rs`
- `crates/goose-provider-types/src/base.rs`

Capabilities affecting harness behavior include context limits, output limits, reasoning, thinking preservation, vision, cache control and provider request parameters. Goose also protects against provider-specific parameters leaking when models/providers change.

Cerebro's model profile should normalize capabilities independently of auth/endpoint/provider runtime configuration. Effective behavior should be a capability/policy intersection, not scattered provider-name checks.

### 6. Make tools a Cerebro-owned catalog/planner/runtime system

Goose evidence:

- `crates/goose/src/agents/mcp_client.rs`
- `crates/goose/src/agents/extension_manager.rs`
- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/agents/platform_extensions/*`

Goose proves that built-ins and MCP tools can share a common lifecycle. Codex's research provides the stronger center: a canonical runtime registry and request-specific exposure/binding plan, with MCP as one source.

Cerebro should own:

```text
ToolKey
  structured source/namespace/name identity

ToolCatalog
  connected executable capabilities + provenance

ToolPlanSnapshot
  exact direct/deferred/hidden set for one StepSnapshot

ToolRuntime
  validate > authorize > execute/cancel > terminal result
```

MCP should be an interoperability adapter behind this layer, not a bypass around Cerebro policy.

### 7. Tool policy should be modular and runtime-enforced

Goose evidence:

- `crates/goose/src/tool_inspection.rs`
- `crates/goose/src/permission/permission_inspector.rs`
- `crates/goose/src/security/security_inspector.rs`
- `crates/goose/src/security/egress_inspector.rs`
- `crates/goose/src/agents/agent.rs`

The Goose inspector chain separates security, egress, adversary, permission and repetition decisions and combines them conservatively.

Cerebro should independently implement a policy pipeline operating on a canonical proposed tool call plus immutable step state. Candidate policy modules include:

- agent/workspace allowlist;
- filesystem scope;
- network/egress;
- destructive-action classification;
- explicit user grants;
- repetition/loop policy;
- external policy/reviewer hooks.

Prompt instructions can explain policy; they must not be the authority.

### 8. Every admitted tool call needs one terminal durable outcome

Goose tool errors, unknown tools and denials can become conversation results. Codex independently enforces the stronger invariant that every admitted call ends succeeded/failed/aborted/denied.

Cerebro should make tool-call identity first-class and persist one terminal state before the harness moves on. Cancellation must not leave an unresolved model-visible call dangling in history.

### 9. Raw tool output and model output should be separate objects

Goose shell evidence:

- `crates/goose/src/agents/platform_extensions/developer/shell.rs`

Goose caps model/display output and spills oversized full output to a temporary file. Codex independently keeps full/log output separate from model-context truncation.

Cerebro should store:

- full/raw result or artifact reference;
- structured status/timing/exit metadata;
- bounded model-visible representation;
- truncation/original-size metadata.

A context limit must never require deleting the only complete tool result.

### 10. Cancellation, retry, recovery and task verification are different policies

Goose evidence:

- `crates/goose-provider-types/src/errors.rs`
- `crates/goose/src/agents/retry.rs`
- `crates/goose/src/agents/state_machine/ops_retry.rs`
- `crates/goose/src/agents/state_machine/ops_exit_on_error.rs`
- `crates/goose/src/agents/state_machine/ops_maxturns.rs`

Goose already distinguishes provider failure categories from recipe success-check retries. The experimental state machine also persists retry attempt metadata across conversation reset.

Cerebro should define typed decisions for at least:

- adapter-local safe transport retry;
- harness-level transient inference retry;
- rate-limit backoff;
- context compaction/migration;
- user approval yield;
- cancellation/abort;
- suspension/worker handoff;
- semantic task retry after failed evidence;
- terminal failure.

Do not build one generic retry counter around the whole agent loop.

### 11. Completion belongs to Cerebro, not the model provider

Goose evidence:

- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/ops_retry.rs`
- `crates/goose/src/agents/state_machine/ops_maxturns.rs`

Goose can continue after a normal assistant end because goal/grind/retry/max-turn/error policy still applies. Codex independently allows runtime stop hooks/completion gates to continue a seemingly finished turn.

Cerebro should normalize provider completion as `InferenceCompleted`, then invoke a separate `CompletionPolicy` with outcomes such as:

- allow;
- continue with model-visible feedback;
- yield to user;
- fail.

Evidence requirements (tests, reviewer, artifacts, task-specific checks) should feed this layer rather than living only in prompts.

### 12. Delegated agents should be durable child runs

Goose evidence:

- `crates/goose/src/agents/subagent_task_config.rs`
- `crates/goose/src/agents/subagent_handler.rs`
- `crates/goose/src/agents/platform_extensions/summon.rs`

Goose subagents have their own persisted sessions, parent id, provider/model/tools/working directory and turn budget. They can execute synchronously or as tracked background tasks. Recursive delegation is deliberately disabled in the examined path.

Cerebro should treat delegation as creation of a child task/turn with explicit:

- parent/root causal lineage;
- provider/model profile;
- context inheritance snapshot;
- tool/permission scope;
- budget/deadline/depth;
- working directory/environment;
- cancellation/ownership state.

Because Cerebro is Slack-like, agent-to-agent messages should be durable communications and scheduling policy should separately decide whether a message wakes a model turn.

### 13. Separate transient events, durable execution events and telemetry

Goose evidence:

- `crates/goose-agent/src/events.rs`
- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/gen_ai_telemetry.rs`

Goose has a small client event stream, richer explicit effects and OpenTelemetry. Codex independently has a rich command/event rollout protocol.

Cerebro should have three planes:

1. **durable execution events/checkpoints** — enough to reconstruct semantic state;
2. **transient stream/UI events** — token deltas, live progress, ephemeral notifications;
3. **telemetry** — traces/metrics/usage, with content capture governed separately.

Do not force all three into channel messages or one event schema.

## Tier 2: useful patterns, but validate before committing

### Deferred tool search

No equivalent deferred/searchable tool-catalog architecture was confirmed in the examined Goose paths at the pinned commit. Codex research shows clear value once MCP/tool catalogs become large.

Cerebro should design `ToolExposure` to permit `hidden | direct | deferred` even if v1 initially exposes tools directly. Add search when real catalog/context pressure justifies it.

### Background subagent tasks

Goose's async summon task manager is useful evidence for background execution. Cerebro already has a richer collaborative product model, so background child tasks should use Cerebro's own task/event/lease system rather than duplicating Goose's in-memory tracker design.

### Provider-owned context/session optimization

Goose ACP and Codex response/session state both demonstrate that some backends keep useful session/cache handles. Cerebro may persist opaque adapter hints, but its correctness rule should be:

> Loss of provider-owned continuation/cache state should normally degrade performance, not make the task unrecoverable.

If a provider-specific opaque object is required for correctness, mark and persist that requirement explicitly.

### Stable/cache-aware prompt prefixes

Goose's sorted extension info and rounded construction-time timestamp show careful prompt-cache thinking. Preserve deterministic composition and stable prefixes where possible, but do not freeze semantically changing context merely to improve cache hit rate.

## Tier 3: Goose choices not recommended as Cerebro defaults

### Do not use one interface for direct providers and external harnesses

The Goose `Provider` abstraction proves it can work, but the ownership flags (`manages_own_context`, provider-side permissions, provider session resume) demonstrate why it is conceptually overloaded for Cerebro's intended direct-provider architecture.

### Do not make MCP the canonical internal tool object model

Goose's common MCP client trait is elegant for unifying extension execution, but Cerebro needs first-party collaboration/control tools, provider-hosted tools, internal privileged tools and future non-MCP runtimes. A Cerebro canonical catalog above MCP is safer and more extensible.

### Do not copy Goose's exact approval modes or inspector order

`Auto`/`Approve`/`SmartApprove`, the exact inspector sequence and LLM read-only classifier are product policy. Cerebro should define its own permission model around its workspace, agents, user roles and execution environments.

### Do not make message visibility flags the whole execution event model

Goose's user/agent visibility distinction is valuable for context construction. It is not enough by itself for Cerebro's durable task/tool/approval/recovery history. Keep visibility as one property on canonical state/events.

### Do not assume one-level subagent depth forever

Goose's explicit non-recursive delegation is a good safety default, not a universal architecture rule. Cerebro should make maximum depth and concurrency explicit policy so it can remain one by default and evolve intentionally.

### Do not treat the experimental Goose state machine as settled upstream architecture

At `8ae4e4ba02836529790f47109b8785e8b42843a7`, the new state-machine path is behind `GOOSE_STATE_MACHINE`; the legacy loop remains relevant. The concepts are useful, but Cerebro should not infer that Goose has already validated every operational consequence of that design in its default path.

## Suggested Cerebro harness component boundaries

Conceptual independent design:

```text
TurnCoordinator
  product wake/lease/final workspace message

TurnStore
  AgentTurn + durable events/checkpoints + projections

HarnessReducer
  determines next state transition from durable turn state

ContextManager
  durable history/state > provider/model-visible context

StepSnapshot
  immutable exact context/model/tools/grants/environment for one inference

ProviderRegistry
  ProviderAdapter + ModelProfile

ExternalAgentRegistry
  ACP/CLI/vendor harness adapters with explicit ownership semantics

InferenceRunner
  provider-neutral events/errors/cancellation

ToolCatalog
  canonical tool identity/runtime/provenance

ToolPlanner
  exact per-step exposure/bindings

ToolPolicy
  permissions/security/egress/concurrency

ToolRuntime
  validation/execution/cancellation + terminal ToolResult

CompletionPolicy
  allow | continue | yield | fail
```

This is compatible with the Harness v1 direction already proposed by issue #202 research, while Goose adds stronger evidence for a re-entrant effect-oriented reducer and for explicit external-agent/backend ownership semantics.

## Suggested execution skeleton

Conceptual behavior only:

```text
load/reduce durable AgentTurn
  > if awaiting user/approval/dependency: yield
  > build next transition
  > derive ContextSnapshot
  > plan ToolPlanSnapshot
  > freeze StepSnapshot
  > run ProviderAdapter inference
  > persist normalized inference events/output
  > for each admitted tool call:
      > evaluate ToolPolicy against StepSnapshot
      > request approval if required and yield
      > execute/cancel
      > persist exactly one terminal ToolResult
  > re-enter reducer from durable state
  > apply compaction/recovery/retry policy when needed
  > run CompletionPolicy
  > continue | yield | fail | commit final product result
```

## Provenance ledger

All Goose rows below refer to pinned upstream commit `8ae4e4ba02836529790f47109b8785e8b42843a7` and remain **conceptual inspiration only**.

| Candidate Cerebro concept | Goose source evidence | Classification | Decision |
| --- | --- | --- | --- |
| Re-entrant durable control reducer | `crates/goose-agent/src/machine.rs`, `operation.rs`; `crates/goose/src/agents/state_machine/session.rs` | conceptual inspiration only | Strong candidate; independently design |
| Explicit effects over persisted state | same as above | conceptual inspiration only | Strong candidate |
| UI/model visibility separation | `crates/goose/src/context_mgmt/mod.rs`, conversation message types | conceptual inspiration only | Adopt concept as context attribute |
| Provider/model capability metadata | `crates/goose-provider-types/src/base.rs`, `model.rs` | conceptual inspiration only | Strong candidate |
| Direct provider versus external-harness distinction | `crates/goose/src/acp/provider.rs`, provider trait | conceptual inspiration only | Diverge intentionally: separate interfaces |
| MCP/platform tool common lifecycle | `agents/mcp_client.rs`, `extension_manager.rs`, platform extensions | conceptual inspiration only | Keep uniform runtime lifecycle; MCP as adapter |
| Dynamic tool-catalog invalidation/version | `agents/extension_manager.rs`, `mcp_client.rs` | conceptual inspiration only | Strong candidate |
| Inspector-based tool policy | `tool_inspection.rs`, permission/security/egress inspectors | conceptual inspiration only | Strong candidate; Cerebro policy names/rules independent |
| Approval/action-required state | `agents/tool_execution.rs` | conceptual inspiration only | Strong candidate |
| Structured shell cancellation/output spill | developer `shell.rs` | conceptual inspiration only | Strong operational requirement |
| Typed provider errors | `goose-provider-types/src/errors.rs` | conceptual inspiration only | Strong candidate for canonical error model |
| Persisted task retry metadata | `agents/state_machine/ops_retry.rs` | conceptual inspiration only | Strong candidate |
| Max-turn/goal policy outside provider completion | `ops_maxturns.rs`, `ops_retry.rs`, operation end-turn semantics | conceptual inspiration only | Strong completion-policy evidence |
| Subagent as persisted child session | `subagent_task_config.rs`, `subagent_handler.rs`, `platform_extensions/summon.rs` | conceptual inspiration only | Strong candidate |
| Small runtime event stream + separate telemetry | `goose-agent/src/events.rs`, `agents/gen_ai_telemetry.rs` | conceptual inspiration only | Use separate event planes, not exact schema |
| Shared backend across CLI/desktop/server | `crates/goose-cli/src/cli.rs`, `ui/desktop/src/gooseServe.ts` | conceptual inspiration only | Already aligned with Cerebro direction |

## Legal/provenance note

At the pinned Goose baseline:

- root project license is Apache-2.0;
- no legal root `NOTICE` file was found;
- the dependency graph still has its own license/attribution obligations and `deny.toml` should not be treated as a complete distributable notice inventory.

This research remains architecture-only. If a future implementation proposal wants to adapt or copy Goose code rather than independently reimplement a concept, that must be a new explicit provenance decision recording exact upstream path/commit, the code used, modifications and applicable license/attribution obligations before merge.
