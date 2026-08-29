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
