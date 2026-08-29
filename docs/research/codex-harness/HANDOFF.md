# Codex Harness Research Handoff

This file exists so a fresh ChatGPT session or another AI agent can resume without relying on chat history.

## Current state

Primary tracker: GitHub issue #202 (`Research: map OpenAI Codex harness for Cerebro`).

Research branch: `research/codex-harness-mining`.

The planned open-ended Codex source-mining pass is now **complete enough to stop**. The architecture map, source archaeology, Cerebro gap analysis and Harness v1 proposal are durable on this branch. The next recommended work is implementation design/Phase 1 from `CEREBRO_HARNESS_V1.md`, not another broad Codex sweep.

Do not modify Cerebro runtime behavior on this research branch unless Dante explicitly changes scope.

## Pinned upstream baseline

All current Codex source-level claims use exactly:

- repository: `openai/codex`
- commit: `0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- tree: `d34870b6840652fab00b2b7f35799aa495e8fae8`
- observed commit time: 2026-08-29 03:59:21 UTC
- commit title: `Preserve permissions when updating session metadata (#41464)`

Root Codex `LICENSE` is Apache-2.0. Root `NOTICE` exists and includes OpenAI Codex attribution plus Ratatui-derived-code MIT notices.

Do not silently move this baseline. Any future upstream rebase must be explicit and should state why the newer source is needed.

## Provenance status

All Codex-derived findings/recommendations in this research pass are currently classified as:

**conceptual inspiration only**

No Codex implementation source has been copied or adapted into Cerebro. Therefore this research phase itself does not require adding Codex NOTICE material to Cerebro.

If future implementation copies/adapts upstream code, record before merge:

- upstream repository/path/commit;
- exact code/idea used;
- classification: independent reimplementation / adapted / copied;
- applicable Apache-2.0/NOTICE obligations;
- modifications and reviewer.

## Durable artifacts

Under `docs/research/codex-harness/`:

- `README.md` — current research index/status and provenance ground rules.
- `UPSTREAM_BASELINE.md` — pinned commit, license/NOTICE baseline, high-priority source map.
- `ARCHITECTURE_MAP.md` — client > app-server > thread/session > `run_turn` > model > tools > follow-up/completion.
- `CONTEXT_AND_PROMPTS.md` — model instructions/profiles, StepContext, World State, AGENTS.md hierarchy/diffs, context budgets and compaction.
- `TOOLS_AND_EXECUTION.md` — ToolRegistry/Exposure/Router separation, terminal outcomes, parallelism, apply_patch and shell execution pipelines.
- `RECOVERY_AND_VERIFICATION.md` — retry layers, transport fallback, context failure, cancellation/suspend/recover, hooks, completion gates and reviewer workflow.
- `SESSIONS_EVENTS_AND_MULTIAGENT.md` — SQ/EQ protocol, durable thread reconstruction, rollback/fork/resume, V1/V2 multi-agent lineage, residency and execution limits.
- `PROVIDER_ABSTRACTION.md` — provider config/runtime/model separation, auth/catalog/transport state, Responses-specific limitation and proposed provider-neutral boundary.
- `MCP_TOOL_SEARCH_AND_OUTPUTS.md` — MCP tool identity/exposure/collisions, deferred search, request-scoped binding, raw/model output separation and truncation.
- `CODEX_TO_CEREBRO_GAP.md` — comparison against current Cerebro runtime, prioritized gaps, mechanisms to keep/reject/defer.
- `CEREBRO_HARNESS_V1.md` — proposed smallest viable model-agnostic harness, migration sequence and acceptance tests.
- `RESEARCH_LOG.md` — chronological research checkpoint.

## Main research conclusion

Cerebro should not become a Codex clone.

Cerebro already owns the product-level pieces that matter for its intended direction: persistent shared channels, agent identity/persona, attribution, autonomous polling/mentions, tasks, budgets, leases, an event hub, provider streaming, MCP/core tools and completion-ordered final chat persistence.

The missing layer is a stronger provider-neutral harness underneath that workspace.

Highest-priority boundaries for Harness v1:

1. canonical Cerebro-owned inference/provider/error types;
2. `ModelProfile` separate from provider identity;
3. immutable request-scoped `StepSnapshot` for each model sample and resulting tool calls;
4. canonical `ToolKey`/definition/binding/result types plus request-scoped `ToolPlanSnapshot`;
5. durable `AgentTurn` + sparse execution events/checkpoints independent of final channel messages;
6. typed retry/recovery/cancellation/suspend semantics;
7. stateful/versioned context + model-aware token budgets + compaction;
8. raw/full tool result separated from bounded model-visible output;
9. explicit completion/evidence policy distinct from the model saying it is done;
10. deferred/searchable tool exposure when MCP catalogs become large.

## Strong Codex findings worth carrying into implementation

### Immutable request state

Codex's request-scoped `StepContext` freezes the effective model/settings, token budget, environment, capability roots, MCP binding/catalog, exact model-visible tool router and instructions for one sample. Resulting tool calls execute against that same snapshot.

Cerebro should independently implement the same invariant: the tool definition a model saw must not mutate underneath a later tool call.

### Context as state, not concatenation

Codex uses typed World State, provenance-aware project instructions and compaction checkpoints rather than only recent-message trimming. Compaction is a history/state transition that reinjects governing context.

Cerebro's current `ContextBuilder` is a useful product packet assembler but still needs a stateful `ContextManager` layer for long-lived/native agents.

### Tool architecture

Codex separates the full executable registry from effective exposure and the exact request router. Large external/MCP catalogs can be deferred/searchable rather than dumped into every prompt. External collisions fail closed. Every admitted call should receive one terminal result.

Cerebro should preserve structured canonical tool identity and generate provider wire names only at the edge.

### Raw versus model-visible output

Codex keeps logging/runtime output and model-context output under different budgets. Log-like text is middle/head+tail truncated with explicit omission metadata for the model rather than destroying the only full result.

Cerebro should store full/raw/artifact output separately from the bounded context representation.

### Provider boundary

Codex has useful provider configuration/runtime/model separation, but its actual wire contract remains effectively OpenAI Responses-shaped at the pinned baseline.

Cerebro should take the structural lesson, not that limitation: native OpenAI, Anthropic, Gemini, DeepSeek and local adapters should translate into Cerebro-owned `InferenceRequest`/`InferenceEvent`/`InferenceError` semantics.

Provider cache/continuation IDs are optimization hints unless proven required for correctness. Another worker should be able to reconstruct a semantically equivalent request from Cerebro durable state without them.

### Recovery and completion

Retry, recovery, persistence and acceptance are separate policies. Context overflow is not solved by replaying the same oversized request. Cancellation is a lifecycle. Suspend/recover is distinct from permanent abort. Prompt instructions to “run tests” are not the same thing as a harness completion gate.

Cerebro should have typed failures plus a small `CompletionPolicy` capable of `allow`, `continue_with_feedback`, or `fail`.

### Sessions/events/multi-agent

Codex separates durable thread identity from live runtimes and reconstructs model/context state from persisted rollout rather than relying on rendered chat alone.

Its V2 multi-agent work also separates durable message delivery from scheduling a new inference turn and separates agent identity, runtime residency and active execution.

Cerebro should adopt those execution concepts without replacing its visible Slack-like shared-channel collaboration model.

## Current Cerebro gaps confirmed against source

Current research-branch sources reviewed include:

- `cerebro/runtime.py`
- `cerebro/context.py`
- `cerebro/models.py`
- `cerebro/providers/base.py`
- `cerebro/providers/openai_compatible.py`
- `cerebro/providers/lmstudio.py`
- `cerebro/providers/cli_agent.py`
- `cerebro/mcp.py`
- `cerebro/turnguard.py`
- `README.md`
- `docs/CEREBRO_V2_ARCHITECTURE.md`

The major confirmed gaps are documented in `CODEX_TO_CEREBRO_GAP.md`. In particular:

- current Provider protocol still consumes workspace `Message` rows directly;
- tool calls/results require protocol data in `Message.meta_json`;
- current generic tool result is effectively string-shaped;
- MCP names are eagerly flattened `server__tool` and all allowed schemas are exposed directly;
- current context budgeting is intentionally approximate/recent-history based;
- `TurnGuard` is live in-memory state, not durable execution recovery state;
- cancellation/UI cleanup exists, but layered typed recovery/suspend/resume does not yet;
- provider directory at this checkpoint contains OpenAI-compatible/LM Studio/CLI/fake paths but no native Gemini/Anthropic/Responses adapter;
- there is no generic hard completion/evidence gate.

These are architecture gaps, not a claim that current Cerebro collaboration/product behavior is wrong.

## Harness v1 recommendation

Read `CEREBRO_HARNESS_V1.md` before implementing.

The recommended incremental package is conceptually:

```text
AgentRuntime / TurnCoordinator
        |
        v
Harness runner
  AgentTurn + events/checkpoints
  ContextManager
  StepSnapshot
  ProviderAdapter + ModelProfile
  ToolCatalog/Planner/Runtime
  CompletionPolicy
        |
        v
final existing Cerebro message
```

Do not ship this as one mega-refactor.

Recommended implementation sequence:

1. canonical inference/error/provider types + compatibility adapter for current OpenAI-compatible provider;
2. canonical tool model + immutable step snapshot;
3. durable `AgentTurn`/event schema;
4. generic runner cutover;
5. typed retry/cancellation/recovery;
6. context sections/model-aware budgets;
7. compaction;
8. one materially non-OpenAI native provider;
9. completion/evidence policy;
10. deferred tool search/output-artifact enhancements.

## Exact next task for a fresh session

Do **not** restart Codex archaeology from the beginning.

Unless Dante changes scope, the next task is:

> Design/implement Harness v1 Phase 1: introduce canonical Cerebro inference/provider/error types and adapt the existing OpenAI-compatible provider behind them, with behavior-preserving tests.

Before freezing the canonical schema, validate it against current native Gemini or Anthropic API semantics so it does not become OpenAI Chat Completions with renamed classes.

If implementation questions later need another Codex look, use the pinned commit and investigate only the specific hypothesis. If a materially newer Codex design is intentionally studied, create an explicit new baseline rather than silently mixing revisions.

## Suggested dynamic follow-up after Phase 1/2

Once the new boundaries exist, harnessed coding agents can add value by running dynamic probes that static GitHub archaeology cannot:

- cancellation during streaming/tool execution;
- catalog mutation during an in-flight sample;
- tool side-effect duplication under retry;
- process restart at durable checkpoints;
- compaction fidelity;
- provider-native tool-call/reasoning edge cases.

Static research is no longer the bottleneck.

## Important constraint

No Codex implementation code has been copied or adapted into Cerebro so far. Preserve that fact unless a future explicit provenance decision changes it.
