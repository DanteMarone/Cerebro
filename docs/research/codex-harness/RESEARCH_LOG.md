# Codex Harness Research Log

Pinned upstream: `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

## 2026-08-29 — Initial mining session

Completed:

- established Apache-2.0 + upstream NOTICE baseline;
- pinned immutable upstream source commit;
- mapped app-server > CodexThread > Session > `run_turn` > model sampling > tool execution > follow-up/completion;
- mapped request-scoped `StepContext` and exact tool/context snapshot behavior;
- mapped model-specific base instructions and capability metadata;
- mapped World State diff architecture;
- mapped hierarchical/provenance-aware AGENTS.md loading and replacement/removal semantics;
- mapped local compaction as a history/state transition, including retained user-message budget and initial-context reinjection behavior;
- mapped ToolRegistry vs ToolExposure vs ToolRouter separation;
- mapped tool failure/abort feedback, per-tool parallelism, verified `apply_patch`, and structured `exec_command` policy pipeline.

Artifacts:

- `UPSTREAM_BASELINE.md`
- `ARCHITECTURE_MAP.md`
- `CONTEXT_AND_PROMPTS.md`
- `TOOLS_AND_EXECUTION.md`
- refreshed `HANDOFF.md`

All upstream-derived findings remain classified as **conceptual inspiration only**. No Codex implementation source has been copied or adapted into Cerebro.

## 2026-08-29 — Recovery, persistence, and multi-agent continuation

Completed:

- confirmed typed retryability and separated HTTP request retries from sampling-stream retries;
- mapped connection-wait behavior and Responses WebSocket > HTTP fallback;
- confirmed hard context-window failure is non-retryable after proactive/mid-turn compaction paths;
- mapped task cancellation, bounded graceful interruption, Stop-hook completion blocking, suspend/recover handoff, and transcript flush behavior;
- separated prompt-level validation guidance from hard harness completion gates and explicit reviewer-agent workflow;
- mapped SQ/EQ session protocol, thread store persistence, rollout reconstruction, rollback replay and fork/resume semantics;
- mapped multi-agent V1/V2 communication, lineage, child config inheritance, task paths, mailbox-vs-trigger-turn semantics, residency and execution capacity limits.

Artifacts:

- `RECOVERY_AND_VERIFICATION.md`
- `SESSIONS_EVENTS_AND_MULTIAGENT.md`

Key design direction strengthened by this slice:

- retry, recovery, acceptance and persistence are separate harness policies;
- durable thread/task identity must be independent of a live provider/worker runtime;
- persisted state needs a deterministic reducer, not only rendered chat history;
- multi-agent collaboration should use durable messages plus explicit scheduling rather than treating every message as an inference call;
- agent identity, runtime residency and active execution should be separate states.

All upstream-derived findings remain classified as **conceptual inspiration only**. No Codex implementation source has been copied or adapted into Cerebro.

## 2026-08-29 — Provider, MCP/output, gap analysis, and Harness v1

Completed:

- mapped `ModelProviderInfo` versus runtime `ModelProvider`, provider-owned auth/account recovery, endpoint/header policy, provider catalogs, capability upper bounds and session/turn client lifetime;
- confirmed the current Codex wire abstraction is still effectively OpenAI Responses-shaped despite a useful runtime provider trait;
- identified provider continuation/response IDs as adapter optimizations rather than durable harness truth;
- mapped MCP canonical tool identity, model-visible namespace specs, legacy flattened hook naming and collision behavior;
- mapped direct/deferred/Code Mode/hidden exposure policy and tool-search indexing/loading;
- confirmed external tools fail closed on collisions and cannot silently replace core privileged tools;
- mapped request-scoped MCP binding/preparation, approval/lifecycle/cancellation path and read-only concurrency hints;
- mapped raw/log output versus model-visible bounded output, head+tail/middle truncation and typed multimodal budgeting;
- reviewed Code Mode enough to classify it as an alternate execution surface worth deferring from Harness v1;
- grounded the Codex comparison against current Cerebro `AgentRuntime`, context builder, provider protocol, OpenAI-compatible adapter, MCP registry, Delta union and TurnGuard;
- wrote the prioritized Codex-to-Cerebro gap analysis;
- wrote a smallest viable Harness v1 architecture and incremental migration/test plan.

Artifacts:

- `PROVIDER_ABSTRACTION.md`
- `MCP_TOOL_SEARCH_AND_OUTPUTS.md`
- `CODEX_TO_CEREBRO_GAP.md`
- `CEREBRO_HARNESS_V1.md`
- refreshed `README.md`
- refreshed `RESEARCH_LOG.md`
- final handoff checkpoint follows this entry.

Research conclusion:

- Cerebro should keep its shared-channel collaboration/product state and evolve the harness underneath it;
- the highest-value foundational additions are canonical provider-neutral inference types, `ModelProfile`, immutable per-sample snapshots, canonical tool identities/results, durable agent-turn/event/checkpoint state, typed recovery, stateful context/compaction and explicit completion policy;
- native provider adapters should translate native APIs into Cerebro-owned semantic events rather than all impersonating one OpenAI wire protocol;
- large tool catalogs should be planned per request and eventually support deferred discovery;
- model-visible output truncation must not delete the durable full result;
- Code Mode and more elaborate Codex mechanisms are not Harness v1 requirements.

All Codex-derived recommendations remain **conceptual inspiration only**. No Codex implementation source has been copied or adapted into Cerebro, so no new upstream NOTICE material is required by this research phase.

The planned open-ended Codex mining pass is complete enough to stop. The next recommended work is implementation design/Phase 1 from `CEREBRO_HARNESS_V1.md`, validated against at least one materially non-OpenAI native provider protocol before the generic contract is frozen.
