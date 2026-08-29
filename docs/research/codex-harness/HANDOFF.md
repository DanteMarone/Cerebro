# Codex Harness Research Handoff

This file exists so a fresh ChatGPT session or another AI agent can resume this research without relying on chat history.

## Purpose

Cerebro is evolving from a Slack-shaped interface around externally harnessed agents into a model-agnostic agent runtime that can call model-provider APIs directly. The goal of this research is to mine the public `openai/codex` repository for harness engineering ideas that can inform a Cerebro-native harness.

Primary tracker: GitHub issue #202 (`Research: map OpenAI Codex harness for Cerebro`).

Research branch: `research/codex-harness-mining`.

## Current architectural direction

Cerebro should remain the source of truth for channel/shared conversation state, agent identity/persona, provider/model selection, tool permissions/execution, context/compaction, task/session state, collaboration, persistence, budgets, telemetry, recovery and verification.

The intended end state is that GPT, Claude, Gemini, DeepSeek and local models can all act as Cerebro-native agents through direct provider APIs while sharing Cerebro's collaboration environment and tool layer. Existing CLI harnesses (Codex CLI, Claude Code, Antigravity, etc.) may remain temporarily as reference/senior-agent implementations during development.

Do not assume raw provider APIs reproduce vendor-harness quality. The research target is the engineering around the model: prompts/instructions, context assembly, tool design, filesystem behavior, sandbox/permissions, recovery, compaction, verification, sessions/events, subagents and observability.

## Research strategy and Apache-2.0 provenance

Use Codex as a reference/donor implementation, not as a wholesale base for Cerebro.

For every relevant mechanism, classify later use as one of:

- conceptual inspiration only
- independently reimplemented
- adapted from upstream
- copied substantially/verbatim

The current research phase MUST NOT copy Codex implementation code into Cerebro. Documentation, architectural descriptions, source-path references and small identifiers/signatures are allowed.

For anything that could later influence implementation, retain:

- upstream repository (`openai/codex`)
- exact upstream path and pinned commit SHA
- license/NOTICE status
- engineering idea/code under consideration
- intended Cerebro component if known
- usage classification
- attribution/license requirement
- modifications if code is later adapted/copied

If actual upstream code is copied or adapted later, preserve applicable Apache-2.0 notices and document lineage before merging. Do not imply OpenAI endorsement or use OpenAI/Codex trademarks as Cerebro branding.

## Pinned upstream baseline

All current source claims use:

- repository: `openai/codex`
- commit: `0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- tree: `d34870b6840652fab00b2b7f35799aa495e8fae8`
- observed commit time: 2026-08-29 03:59:21 UTC
- commit title: `Preserve permissions when updating session metadata (#41464)`

Root `LICENSE` is Apache-2.0. Root `NOTICE` exists and includes OpenAI Codex attribution plus Ratatui-derived-code MIT notices. Do not silently move the baseline to a newer Codex commit; record/reason about any future rebase explicitly.

## Durable research artifacts completed

Under `docs/research/codex-harness/`:

- `README.md` — research landing/provenance policy.
- `UPSTREAM_BASELINE.md` — pinned commit, license/NOTICE baseline, high-priority crate map.
- `ARCHITECTURE_MAP.md` — confirmed client > app-server > CodexThread > Session > `run_turn` > sampling > tool follow-up > completion path.
- `CONTEXT_AND_PROMPTS.md` — base instructions, model metadata, typed context fragments, World State, AGENTS.md hierarchy/diffs, StepContext and compaction semantics.
- `TOOLS_AND_EXECUTION.md` — tool registry/exposure/router separation, per-step planning, failure/abort semantics, parallelism, apply_patch and shell execution pipelines.
- `RECOVERY_AND_VERIFICATION.md` — retry layers, typed failures, transport fallback, compaction/context failure, cancellation/suspend/recover, hooks, completion gates and reviewer semantics.
- `SESSIONS_EVENTS_AND_MULTIAGENT.md` — SQ/EQ protocol, thread persistence/reconstruction, rollback/fork/resume, agent control, V1/V2 collaboration, lineage, residency and execution limits.
- `RESEARCH_LOG.md` — chronological durable checkpoint log.

Remaining planned design artifacts:

- `CODEX_TO_CEREBRO_GAP.md`
- `CEREBRO_HARNESS_V1.md`

Additional research slices still required before those design artifacts:

- provider abstraction;
- MCP/tool search/output truncation.

## Key confirmed findings so far

### Headless runtime boundary

`codex-core` is explicitly the reusable business-logic runtime beneath multiple UIs. `app-server` exposes thread/turn/item lifecycle for rich clients. This strongly supports Cerebro keeping a headless harness with the Slack-shaped UI as a client/subscriber rather than coupling UI to inference logic.

### Core control loop

The confirmed high-level path is:

```text
client turn/start
  > app-server validates/translates
  > CodexThread / Session admits turn
  > run_turn
      > pre-sampling compaction if needed
      > capture request-scoped StepContext
      > update World State/context
      > inject user/skill/plugin context
      > clone model-visible history
      > build prompt from base instructions + history + exact ToolRouter specs
      > ModelClientSession.stream
          > record assistant/reasoning output
          > execute tool calls
          > persist terminal tool outcomes
          > track usage/events
      > follow-up sample when tools/input/provider require it
      > compact mid-turn if continuation would overflow
      > run stop hooks
      > complete turn
```

### Request-scoped StepContext

`StepContext` freezes the exact settings, model-related token budget, environment snapshot, capability roots, executor capability discovery, MCP binding/catalog, ToolRouter and effective AGENTS.md value for one sampling request. Tool execution retains that same StepContext even if it completes later.

This is a strong Cerebro Harness v1 candidate: the model should execute against the exact state that advertised its tools/context, not mutable global state observed later.

### World State

Codex models mutable harness context as typed World State sections with stable IDs, persisted compact snapshots and add/replace/remove diff semantics. Current sections cover model/personality, token/context guidance, AGENTS.md, permissions, collaboration/persistent mode, environment/date, apps/plugins/tools, multi-agent mode and managed developer instructions.

This avoids endlessly duplicating unchanged context while still explicitly telling the model when governing state changes.

### AGENTS.md

Project instructions are discovered from project root to cwd, using `AGENTS.override.md` before `AGENTS.md` plus configured fallbacks. Discovery is root-bounded, byte-budgeted, provenance/environment-aware, skipped for untrusted projects and cached by environment/trust state. Changed/removed AGENTS.md state is explicitly synchronized to the model through World State diffs.

### Model-specific behavior

Model metadata is much richer than a name/context window. It carries model instruction templates/messages, reasoning settings, tool modes, truncation policy, context/compaction settings, modalities, apply-patch/web-search behavior, multi-agent behavior and other capability flags. Base instructions resolve from explicit override > persisted session history > selected model template.

This supports a first-class Cerebro `ModelProfile`/harness capability layer separate from provider adapters.

### Compaction

The default compaction request is essentially a concise LLM handoff, but the runtime treats compaction as a state transition. It constructs replacement history, retains recent real user messages under a separate budget, appends a typed summary, manages compaction-window IDs, resets or reinjects canonical initial context depending on pre-turn versus mid-turn compaction, updates World State baselines and recomputes token usage.

Model switches can trigger reconciliation/compaction when compaction hashes differ or a new model has a smaller usable window.

### Tools

Codex separates the executable `ToolRegistry` from effective `ToolExposure` and the exact model-visible `ToolRouter` plan for one step. Tool availability can depend on model/provider capability, feature flags, environment, MCP policy, agent depth/mode and direct/deferred/code-mode exposure.

Every accepted tool call is intended to end in a model-visible terminal result. Ordinary failures, parse/validation feedback and cancellation are fed back into history rather than silently losing the call. Parallel model tool calling is separate from each runtime's own concurrency safety.

### apply_patch

`apply_patch` is a dedicated verified edit primitive: parse model patch > resolve captured environment > verify against filesystem > derive affected paths/permissions > sandbox/authorize > apply > track diff/lifecycle > feed correctness failures back to model. No Codex apply-patch implementation has been copied.

### Shell

`exec_command` is a structured execution pipeline rather than raw shell subprocess use: environment/cwd/shell resolution, local-vs-remote paths, permissions/approval, sandbox intent, patch interception, process identity, output limits, cancellation and model-visible sandbox/failure results.

### Recovery and verification

Recovery is intentionally layered rather than one generic retry loop. HTTP request retry, sampling-stream retry, offline/network waiting, WebSocket > HTTP fallback, context compaction, task cancellation and durable suspend/recover are distinct mechanisms with different replay semantics.

`ContextWindowExceeded` is a non-retryable hard error after the harness has had opportunities to compact. Cancellation is propagated through `CancellationToken`, with a short graceful completion window before forced task abort.

Verification is also layered: default instructions tell the model when/how to test, but ordinary completion is not hard-gated by proof that tests passed. Runtime-enforced checks cover narrower concerns such as tool authorization and edit verification. Stop hooks can explicitly block completion and feed continuation feedback back to the model. `/review` is an explicit reviewer sub-agent workflow rather than an automatic verifier on every normal turn.

Cerebro should therefore separate evidence collection, acceptance policy and completion gating.

### Sessions, persistence and event reconstruction

Codex explicitly uses a submission-queue/event-queue session protocol. Durable thread identity is separated from live in-memory runtime. Thread persistence records stable identity, parent/fork lineage, history mode, model/provider metadata, instructions and context-window information.

Rollout reconstruction is not chat replay: it rebuilds model-visible history plus previous-turn settings, context baselines, World State and context-window identity while understanding compaction, interruption, rollback and inter-agent communication. Stored turn projections separately expose completed/interrupted/failed/in-progress status.

Rollback is itself a durable replay event, and resume is distinct from fork. This strongly supports Cerebro using durable events/checkpoints plus a deterministic reducer instead of storing only rendered messages.

### Multi-agent

A sub-agent is a real thread with parent/root turn lineage, persistent identity and its own lifecycle. `AgentControl` is root-tree scoped and shared across root/sub-agents, carrying registry, budgets, residency and execution-capacity state.

Child spawn deliberately inherits the effective live parent turn: provider/model, reasoning, instructions/provenance, approval/permission state, cwd and the exact request-scoped environment selection. Optional role/model overrides are layered and validated afterward.

V2 moves toward canonical task paths plus mailbox semantics: `send_message` communicates without necessarily starting inference, while `followup_task` communicates and triggers work when appropriate. Agent identity, runtime residency and active execution are distinct; persisted V2 agents can be known without all runtimes being loaded, and V2 sub-agent turns have separate execution-capacity limits.

This aligns closely with Cerebro's Slack-like collaboration direction: durable messages should not automatically equal provider calls.

## Division of labor

ChatGPT is the primary source archaeologist and documentation/provenance keeper because it can read public GitHub source and write directly to Cerebro without consuming paid coding-agent credits.

Use harnessed agents later for:

- cloning/building/running Codex locally
- dynamic tracing/runtime probes
- compiling/testing hypotheses
- independent review of important conclusions

## Exact next research targets

A fresh session should continue in this order:

1. **Provider abstraction**
   - inspect `model-provider`, `client`, `model-provider-info`, provider/session construction and Responses normalization;
   - map what the provider adapter owns: auth, endpoint/headers, wire API, transport, retries, streaming events, response IDs/caching and feature support;
   - distinguish reusable harness contracts from OpenAI Responses-specific assumptions.
2. **MCP/tool search/output truncation**
   - finish MCP naming/collision/exposure rules, deferred tool search/Code Mode economics and request-scoped binding behavior;
   - map model-visible output truncation/budget behavior versus durable full logs/artifacts.
3. **Codex > Cerebro gap**
   - write `CODEX_TO_CEREBRO_GAP.md` after provider/MCP research is durable;
   - classify each candidate as conceptual inspiration, independent reimplementation, adaptation or copy; current classification remains conceptual only.
4. **Harness v1**
   - only after the gap is explicit, write `CEREBRO_HARNESS_V1.md` with the smallest architecture that preserves the important boundaries.

## Important constraint

Do not modify Cerebro runtime behavior on this research branch unless Dante explicitly changes scope. Research/design/provenance artifacts first. No Codex implementation source has been copied or adapted into Cerebro so far.
