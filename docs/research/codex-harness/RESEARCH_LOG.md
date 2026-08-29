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

Next research target: recovery/verification semantics, followed by session persistence/events/multi-agent behavior and provider abstraction.

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
- refreshed `RESEARCH_LOG.md`
- handoff checkpoint follows this entry.

Key design direction strengthened by this slice:

- retry, recovery, acceptance and persistence are separate harness policies;
- durable thread/task identity must be independent of a live provider/worker runtime;
- persisted state needs a deterministic reducer, not only rendered chat history;
- multi-agent collaboration should use durable messages plus explicit scheduling rather than treating every message as an inference call;
- agent identity, runtime residency and active execution should be separate states.

All upstream-derived findings remain classified as **conceptual inspiration only**. No Codex implementation source has been copied or adapted into Cerebro.

Next research target: provider abstraction, then MCP/tool-search/output-budget behavior, then the Codex-to-Cerebro gap and Harness v1 proposal.
