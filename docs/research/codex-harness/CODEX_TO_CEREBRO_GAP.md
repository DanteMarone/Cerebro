# Codex-to-Cerebro Harness Gap

**Status:** Design synthesis after completing the planned Codex source-mining slices.

**Cerebro baseline:** `research/codex-harness-mining` at/through `b451997785b6e9f71d3a4ae4d6e91b5d97146eae` before this document.

**Codex reference baseline:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

All Codex-derived recommendations in this document remain **conceptual inspiration only**. No Codex implementation source has been copied or adapted into Cerebro.

## Executive conclusion

Cerebro does **not** need to become Codex.

Cerebro already has product/runtime primitives Codex is not trying to provide: persistent shared channels, team/agent identity, autonomous polling, a Slack-like collaboration model, tasks, leases, budgets, an event hub, MCP allowlists, and completion-ordered shared chat persistence.

The actual gap is narrower and more important: `AgentRuntime` is still a relatively thin tool-calling chat loop whose durable state is primarily conversation rows. To support GPT, Claude, Gemini, DeepSeek and local models as first-class Cerebro-native agents with vendor-harness quality, Cerebro needs a **provider-neutral harness substrate between shared workspace state and the provider API**.

The highest-value missing boundaries are:

1. a request-scoped immutable execution/context/tool snapshot;
2. a canonical provider-native inference request/event/error contract;
3. model profiles/capability negotiation separate from provider identity;
4. durable turn/task execution state and replayable events/checkpoints;
5. context/world-state synchronization plus real compaction;
6. structured tool identities/results with raw-vs-model output separation;
7. typed recovery/cancellation/suspend/resume semantics;
8. explicit evidence/acceptance/completion policy;
9. scalable direct/deferred tool planning for large MCP catalogs.

These can be added without replacing Cerebro's collaboration model.

## 1. What Cerebro should keep

Several current Cerebro choices align well with the useful Codex architecture and should be treated as assets, not rewritten reflexively.

### Shared workspace is already Cerebro-owned

Cerebro owns agents, teams, channels, membership, messages, tasks, audit/budget records and attribution. The provider is not the owner of the conversation.

That is exactly the right direction for a model-agnostic harness.

Current sources:
- `README.md`
- `docs/CEREBRO_V2_ARCHITECTURE.md`
- `cerebro/models.py`
- `cerebro/db.py`

### The UI is already downstream of a headless runtime/event hub

The v2 architecture separates browser/WebSocket presentation from `Hub`, `AgentRuntime`, providers and tools. In-flight status/deltas are ephemeral while final chat messages are persisted completion-ordered.

That matches the important Codex lesson that a harness should be reusable beneath multiple clients and that transient stream activity is not identical to durable conversation state.

Current sources:
- `cerebro/hub.py`
- `cerebro/runtime.py`
- `README.md`

### Cerebro already normalizes provider streaming

The current `Delta` union has semantic events for text, reasoning, tool-call fragments, usage and completion. `OpenAICompatibleProvider` translates SSE chunks into those events before `AgentRuntime` consumes them.

This is the correct abstraction *shape*. It needs to become richer/provider-neutral enough for native Claude/Gemini/OpenAI APIs, not be discarded.

Current sources:
- `cerebro/models.py`
- `cerebro/providers/base.py`
- `cerebro/providers/openai_compatible.py`

### Tool execution is already Cerebro-controlled

`AgentRuntime` receives tool specs from Cerebro and dispatches calls through a Cerebro executor. `CompositeToolExecutor` checks whether an MCP tool was actually offered to the agent before executing it.

This is a strong starting point for making the tool layer request-scoped and policy-complete.

Current sources:
- `cerebro/runtime.py`
- `cerebro/mcp.py`
- `cerebro/tools.py`

### Loop and spend controls already exist

`TurnGuard`, provider semaphores, maximum tool iterations, usage accounting, distributed leases and agent rate limits already constrain common runaway patterns.

Codex adds richer lifecycle/recovery, but the product-level instinct in Cerebro is already correct: autonomy requires explicit runtime limits rather than merely asking the model to behave.

Current sources:
- `cerebro/turnguard.py`
- `cerebro/runtime.py`
- budget/usage/lease modules and README documentation

### CLI-backed agents are a useful migration bridge

Cerebro currently supports external harnesses through CLI-agent integration while native provider support grows. That is valuable during the transition because it lets Cerebro compare its own harness quality against Codex/Claude/other mature harnesses without blocking the shared collaboration product.

Current sources:
- `cerebro/providers/cli_agent.py`
- `scripts/poll_channels.py`
- README CLI-agent section

## 2. Gap: Provider protocol is too small and too chat-row-shaped

Current `Provider.stream(...)` takes:

```text
messages: list[Message]
tools: list[ToolSpec]
params: Params
```

and produces the current `Delta` union.

This works for an OpenAI-compatible Chat Completions adapter, but the generic harness is already leaking its database model into the provider layer. `openai_compatible.to_chat_messages(...)` explicitly notes that tool-call protocol state has to be smuggled through `Message.meta_json` because database conversation rows cannot natively express it.

There is also no first-class generic place for:

- system/developer distinction;
- structured/multimodal content parts;
- provider-native reasoning controls/state;
- output schemas;
- provider cache/continuation hints;
- model/provider capability negotiation;
- normalized retry/error details;
- provider metadata/rate-limit updates;
- native prompt-cache/session semantics.

**Gap severity:** critical for native multi-provider support.

**Recommendation:** introduce Cerebro-owned `InferenceRequest`, `InferenceEvent`, `InferenceError`, `ProviderAdapter`, and `ModelProfile` contracts. Keep `Message` as workspace/chat storage, not as the provider protocol AST.

Codex reference:
- `PROVIDER_ABSTRACTION.md`

Classification: **conceptual inspiration; independently implement the Cerebro contract.**

## 3. Gap: No real model-profile layer

Current agent configuration contains `provider`, `model`, and generic parameters. The generic `Params` surface is currently temperature/max_tokens/stop.

The harness therefore lacks a normalized place to say that a particular model/provider combination:

- supports native tools or parallel tools;
- has a context window/usable compaction threshold;
- supports images/audio/files;
- supports structured output;
- has reasoning controls or opaque reasoning state;
- can use prompt caching/continuation IDs;
- needs model-specific base instructions;
- prefers one tool-exposure mode or truncation policy;
- supports native web search or other hosted capabilities.

**Gap severity:** critical for quality parity across heterogeneous models.

**Recommendation:** add a `ModelProfile` resolved from provider discovery + Cerebro overrides. Effective capability should be the intersection of provider, model, agent/workspace policy and the current turn.

Codex reference:
- `CONTEXT_AND_PROMPTS.md`
- `PROVIDER_ABSTRACTION.md`

Classification: **conceptual inspiration; independent implementation.**

## 4. Gap: A turn has no immutable request/execution snapshot

`AgentRuntime.run_turn()` currently builds a transcript, asks `tools_for(agent)`, and then carries mutable Python objects/functions through the tool loop. MCP execution later recomputes `specs_for(...)` to verify availability.

There is not yet a durable/request-scoped object equivalent to the useful Codex `StepContext` boundary that freezes:

- agent/model/provider settings;
- system/developer/context instructions;
- current workspace/environment/cwd;
- permissions;
- tool catalog version and exact exposed schemas;
- executable tool bindings;
- context/world-state baseline;
- model/token budgets;
- trace/causal metadata.

That creates race and reproducibility risk as live configuration, MCP servers, permissions or agent profiles change during a long turn.

**Gap severity:** critical for correctness/recovery.

**Recommendation:** create `TurnSnapshot`/`StepSnapshot` as an immutable object used to construct the inference request and execute every tool call produced by that request. Later model samples in the same logical turn may create new snapshots after applying explicit state changes.

Codex reference:
- `ARCHITECTURE_MAP.md`
- `CONTEXT_AND_PROMPTS.md`
- `TOOLS_AND_EXECUTION.md`

Classification: **strong conceptual inspiration; independent implementation.**

## 5. Gap: Context is packet assembly, not state management

Current `ContextBuilder` is useful but intentionally simple:

- system identity/manual/channel frame;
- scratchpad;
- recent memory notes;
- recent channel history;
- approximate four-characters-per-token budgeting;
- oldest-history trimming.

It does not yet model mutable harness state as typed/versioned sections, preserve a baseline and send diffs, detect project instruction changes, or perform semantic compaction.

It also has no provider/model-specific usable context accounting. A provider `length` failure is currently explained to the user rather than becoming a harness recovery transition.

**Gap severity:** critical for long-running agents and coding work.

**Recommendation:** evolve context in two stages:

1. introduce typed `ContextSection`s / `WorldState` with stable IDs, provenance and version/hash;
2. add `ContextManager` with accurate enough model-specific budgeting, compaction checkpoints, retained recent user turns and state reinjection.

Do not make full Codex-style world-state diffing a prerequisite for the first provider adapter, but make the storage/request schema capable of it.

Codex reference:
- `CONTEXT_AND_PROMPTS.md`

Classification: **conceptual inspiration; independent implementation.**

## 6. Gap: Durable workspace messages are not sufficient durable harness history

Cerebro persists final chat messages and has separate `tool_calls`/audit concepts, but the active inference/tool-loop state is not a replayable durable execution log.

`TurnGuard` is explicitly in-memory. If the process disappears during a turn, Cerebro does not have a generic reducer capable of reconstructing:

- whether the turn was queued/running/waiting on a tool;
- the exact request/tool snapshot that caused a pending call;
- which tool calls reached a terminal state;
- compaction/context checkpoints;
- cancellation/interruption state;
- provider cache hints;
- worker ownership/lease state;
- acceptance/review state.

The current collaboration `turn_id` is valuable causal lineage, but it is not yet a durable inference-turn record.

**Gap severity:** critical for crash recovery/resident autonomous agents.

**Recommendation:** add durable `agent_turns` plus append-only `turn_events` (or equivalent event records) and indexed projections. Shared channel messages remain completion-ordered product history; harness events remain execution history. Do not put every token delta in SQLite.

Codex reference:
- `SESSIONS_EVENTS_AND_MULTIAGENT.md`
- `RECOVERY_AND_VERIFICATION.md`

Classification: **conceptual inspiration; independent event model.**

## 7. Gap: Cancellation exists, recovery does not

Current runtime correctly handles `asyncio.CancelledError` and emits terminal cancellation UI events. Provider connection/read failures become user-facing errors. This prevents orphaned UI state.

What is missing is a canonical recovery model differentiating:

- transient network/provider failure;
- rate limit/retry-after;
- provider authentication failure;
- context exhaustion;
- tool timeout/failure;
- explicit user cancellation;
- forced kill;
- worker/service crash;
- intentional suspend/handoff;
- resumable versus terminal failure.

There are no layered request/stream retry policies or durable suspend/resume semantics comparable to the useful Codex separation.

**Gap severity:** high.

**Recommendation:** define typed `InferenceError`/`TurnFailure` categories and a recovery policy before adding aggressive retries. Add a worker/task lease or ownership field so an interrupted durable turn can be re-queued/recovered rather than inferred from an empty UI state.

Codex reference:
- `RECOVERY_AND_VERIFICATION.md`

Classification: **conceptual inspiration; independent implementation.**

## 8. Gap: Completion means “provider stopped,” not “task acceptance passed”

Current coding/agent quality depends mainly on prompts, model behavior and whatever tools the agent voluntarily invokes. `AgentRuntime` knows whether the provider stopped, ran out of tool rounds, returned empty output or produced `PASS`, but there is no generic completion-policy layer that can require evidence.

For coding tasks this matters: “model says done” is different from “required tests/lint/build/review evidence passed.”

**Gap severity:** high for coding-agent parity, medium for ordinary chat.

**Recommendation:** introduce a small `CompletionPolicy` seam:

```text
allow
block_with_feedback
fail
```

with evidence from tool results/checks. Keep default chat policy permissive. Let task types opt into required tests, reviewer agent, artifact checks or other acceptance gates.

Codex reference:
- `RECOVERY_AND_VERIFICATION.md`

Classification: **conceptual inspiration; independent implementation.**

## 9. Gap: Tool identity is flattened and output is string-only

Current MCP tools are model/runtime-addressed as `server__tool`. `ToolSpec` carries only name/description/parameters. `StdioMCPClient.call_tool()` collapses MCP content into text where possible and `ToolExecutor` returns `str`.

This loses or complicates:

- structured canonical source/server/name identity;
- provider-specific name encoding;
- output schemas;
- multimodal content;
- full raw result versus model-facing result;
- original size/truncation metadata;
- artifacts/files;
- read-only/destructive/open-world/concurrency annotations;
- exact catalog version/binding.

It also means external collision rules are mostly an emergent property of flattened names rather than a structured registry invariant.

**Gap severity:** high.

**Recommendation:** introduce `ToolKey`, `ToolDefinition`, `ToolBinding`, `ToolCall`, and typed `ToolResult`. Generate flattened provider names late. Store raw/artifact result separately from the bounded model representation.

Codex reference:
- `TOOLS_AND_EXECUTION.md`
- `MCP_TOOL_SEARCH_AND_OUTPUTS.md`

Classification: **conceptual inspiration; independent implementation.**

## 10. Gap: MCP catalog exposure is eager and global per agent

Current `MCPRegistry` starts servers, fetches their entire tool lists, flattens names and filters them against per-agent globs. `CompositeToolExecutor.specs_for(...)` then returns all allowed core + MCP specs directly to the model.

That is fine for a small catalog but will become expensive and confusing once Cerebro connects filesystem, GitHub, browser, calendars, databases, Obsidian, custom agent tools and future plugin ecosystems simultaneously.

**Gap severity:** medium now; high at intended scale.

**Recommendation:** preserve allowlists, then add per-request exposure planning:

- `direct`: small/high-frequency tools;
- `deferred`: allowed but discoverable through `search_tools`;
- `hidden`: connected but unavailable to this request.

Start with lexical search; do not add embeddings until evidence says they help.

Codex reference:
- `MCP_TOOL_SEARCH_AND_OUTPUTS.md`

Classification: **conceptual inspiration; independent implementation.**

## 11. Gap: MCP transport implementation is intentionally minimal

Current `StdioMCPClient` implements a useful narrow JSON-RPC-over-stdio subset itself. It serializes requests behind one lock, has one request timeout, lazily restarts a process and supports `initialize`, `tools/list`, `tools/call`.

As Cerebro's MCP reliance increases, it will need to decide whether to keep hardening this client or adopt/encapsulate a standards-complete MCP client library for:

- notifications/server-initiated traffic;
- HTTP/SSE/streamable transports;
- resources/prompts/elicitation/auth;
- tool-list changes;
- cancellation/progress;
- reconnect/session behavior;
- richer content types.

**Gap severity:** medium, growing with MCP usage.

**Recommendation:** hide transport behind a `ToolSource`/`McpConnection` interface now. Standards-complete implementation choice can change later without affecting the harness tool model.

This is a Cerebro-local observation; it does not require copying Codex's MCP stack.

## 12. Gap: Native provider coverage has not reached the intended target

On the research branch, `cerebro/providers/` currently contains the generic protocol, fake provider, CLI agent, LM Studio wrapper and OpenAI-compatible provider. There is no native Gemini/Anthropic/OpenAI Responses adapter in that directory at this checkpoint.

The OpenAI-compatible adapter can cover LM Studio, OpenRouter, DeepSeek, GLM and compatible OpenAI endpoints, which is useful, but routing every future provider through Chat Completions compatibility would recreate the same abstraction limitation identified in Codex's Responses-oriented provider layer.

**Gap severity:** critical to the stated product direction.

**Recommendation:** after the provider-neutral contract lands, implement one genuinely different native provider (Gemini or Anthropic) before declaring the abstraction stable. A second wire protocol is the quickest way to expose hidden OpenAI assumptions.

Codex reference:
- `PROVIDER_ABSTRACTION.md`

Classification: **Cerebro design recommendation informed by conceptual comparison.**

## 13. Gap: Agent collaboration is product-strong but execution lineage can be richer

Cerebro already has a better end-user collaboration shape for its goals than Codex's sub-agent tree: agents occupy shared channels and independently decide whether to speak. `turn_id` and depth propagate causal conversation lineage.

What is missing below that is task/execution lineage for delegated work:

- parent task/turn;
- root task/turn;
- child execution ownership;
- durable queued/running/waiting/completed state;
- mailbox/message versus “wake and execute” semantics for programmatic delegation;
- capacity/residency state when many durable agents exist.

**Gap severity:** medium now, high for autonomous delegated workloads.

**Recommendation:** do not replace the Slack-like collaboration model with Codex's agent tree. Add the useful causal fields to Cerebro tasks/turns and let a delegated task point back to its originating channel/message/turn.

Codex reference:
- `SESSIONS_EVENTS_AND_MULTIAGENT.md`

Classification: **selective conceptual inspiration only.**

## 14. Important Codex mechanisms Cerebro should *not* copy into v1

### Responses as the generic wire model

Rejected. Cerebro's main differentiator is model/provider neutrality.

### Full Code Mode runtime

Defer. It is useful but not foundational. Direct + deferred tools first.

### Codex's exact prompt/base-instruction text

Do not copy. Cerebro needs its own operating manual and model-specific profiles.

### Codex's exact history/ResponseItem data model

Do not copy. It is tightly coupled to Responses protocol semantics. Cerebro needs a canonical provider-neutral inference AST plus its existing workspace messages.

### Codex's exact MCP namespace strings or BM25 implementation

Not important. Preserve structured identity and the discover/load behavior, not the spelling or source code.

### A single-root hidden sub-agent UX

Not a fit. Cerebro's shared-channel collaboration is intentional and should remain visible/auditable.

## 15. Prioritized gap closure

### P0 — foundational correctness

1. canonical inference/provider/model contracts;
2. immutable per-sample `StepSnapshot`;
3. canonical typed tool model + request-scoped `ToolPlanSnapshot`;
4. durable `agent_turns` + sparse execution events/checkpoints;
5. typed errors/cancellation/recovery states.

### P1 — harness quality

6. typed context/world-state sections + model-aware budgets;
7. compaction/reconstruction;
8. raw-vs-model tool output + artifact storage/truncation;
9. completion/evidence policy;
10. first native non-OpenAI-shaped provider.

### P2 — scale/efficiency

11. deferred tool search;
12. provider cache/session hints;
13. agent runtime residency/worker leasing;
14. richer reviewer/delegation policies;
15. optional Code Mode-like programmable tool orchestration.

## 16. Migration principle

The safest path is evolutionary:

```text
existing Hub / channels / messages / polling / tasks
  KEEP

existing AgentRuntime orchestration role
  SPLIT internally into request snapshots + inference loop + tool runtime + completion policy

existing Provider protocol
  REPLACE behind compatibility adapters

existing MCP/core tools
  WRAP into canonical ToolCatalog/ToolRuntime

existing final chat persistence
  KEEP

add durable harness turn/event state alongside chat
  ADD, do not overload message rows
```

This avoids a second ground-up Cerebro rewrite while still creating the seams needed for model-agnostic harness quality.

## 17. Definition of “gap closed enough” for Harness v1

Harness v1 does not need every Codex capability. It is sufficient when Cerebro can demonstrate all of the following:

- the same durable Cerebro task/turn can run through two materially different native provider protocols;
- each model request executes against an immutable context/tool snapshot;
- a tool call cannot execute a tool definition different from the one advertised to the model;
- large outputs retain a durable full representation while the model receives a bounded one;
- a worker/process loss leaves enough durable state to classify/recover or cleanly fail the turn;
- context can compact without losing governing instructions/tool/task state;
- transient provider failures and hard context/policy/tool failures are distinguishable;
- a task can require acceptance evidence independently of the worker model saying it is done;
- external tools cannot shadow privileged Cerebro tools;
- shared channel/message semantics continue to work unchanged above the harness.

That is the target for `CEREBRO_HARNESS_V1.md`.

## Provenance classification summary

No Codex implementation source is proposed for copying/adaptation in Harness v1.

| Area | Current recommendation |
| --- | --- |
| Request-scoped snapshot | conceptual inspiration > independent Cerebro implementation |
| Context/world-state model | conceptual inspiration > independent Cerebro implementation |
| Compaction lifecycle | conceptual inspiration > independent Cerebro implementation |
| Tool registry/exposure/router separation | conceptual inspiration > independent Cerebro implementation |
| MCP namespacing/collisions/search | conceptual inspiration > independent Cerebro implementation |
| Output truncation/raw separation | conceptual inspiration > independent Cerebro implementation |
| Provider normalization | conceptual inspiration > independent Cerebro implementation |
| Retry/recovery/cancellation | conceptual inspiration > independent Cerebro implementation |
| Event/replay model | conceptual inspiration > independent Cerebro implementation |
| Completion gates/reviewer | conceptual inspiration > independent Cerebro implementation |
| Shared-channel collaboration | Cerebro-native; keep Cerebro design |
| Leases/budgets/attribution | Cerebro-native; keep Cerebro design |

No Apache-2.0 NOTICE material needs to be added to Cerebro from this research phase because no Codex implementation code has been copied or adapted.
