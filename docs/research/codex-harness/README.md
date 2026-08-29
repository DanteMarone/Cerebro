# Codex Harness Mining

This directory contains the research used to understand the public `openai/codex` harness and decide what Cerebro should copy conceptually, independently reimplement, adapt under Apache-2.0, or reject.

Tracking issue: #202  
Research branch: `research/codex-harness-mining`

## Status

The planned Codex source-mining pass is complete enough to move from open-ended archaeology into Cerebro Harness v1 implementation design.

Pinned upstream baseline for all current Codex source claims:

- repository: `openai/codex`
- commit: `0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- tree: `d34870b6840652fab00b2b7f35799aa495e8fae8`

Root Codex `LICENSE` is Apache-2.0 and root `NOTICE` was reviewed. No Codex implementation source has been copied or adapted into Cerebro during this research phase; all current upstream-derived recommendations remain **conceptual inspiration only**.

## Ground rules

1. Do not transplant Codex implementation code into Cerebro merely because it was studied here.
2. Every material source-level finding must retain the exact upstream repository path and pinned commit.
3. If later implementation copies or adapts Codex source, classify and record that provenance before the code is merged.
4. Preserve all applicable Apache-2.0 copyright, license, NOTICE, patent, and attribution obligations for copied/adapted material.
5. Do not imply OpenAI sponsorship or use Codex/OpenAI trademarks as Cerebro product branding.
6. Prefer independently written Cerebro implementations when the value is the engineering idea rather than exact upstream expression.

## Provenance classification

- **Conceptual inspiration only** — architecture/behavior learned from Codex; Cerebro implementation written independently.
- **Independent reimplementation** — behavior intentionally reproduced without copying substantial implementation expression.
- **Adapted from upstream** — Codex implementation used as a starting point and modified.
- **Copied substantially/verbatim** — substantial upstream implementation retained.

For the last two categories, retain applicable notices and document modifications.

## Completed artifacts

- `UPSTREAM_BASELINE.md` — exact pinned Codex commit, license/NOTICE baseline, high-priority crate map.
- `ARCHITECTURE_MAP.md` — app-server > CodexThread > Session > turn loop > model > tools > follow-up/completion.
- `CONTEXT_AND_PROMPTS.md` — model instructions/profiles, StepContext, World State, AGENTS.md discovery/diffs, token budgets and compaction.
- `TOOLS_AND_EXECUTION.md` — ToolRegistry/Exposure/Router separation, tool outcomes, parallelism, apply_patch and shell pipelines.
- `RECOVERY_AND_VERIFICATION.md` — retries, transport fallback, context failure, cancellation/suspend/recover, hooks, completion gates and reviewer workflow.
- `SESSIONS_EVENTS_AND_MULTIAGENT.md` — SQ/EQ protocol, thread persistence/reconstruction, rollback/fork/resume, V1/V2 multi-agent semantics and residency.
- `PROVIDER_ABSTRACTION.md` — provider config/runtime/model separation, auth/catalog/transport state, Responses-specific limitations and proposed provider-neutral boundary.
- `MCP_TOOL_SEARCH_AND_OUTPUTS.md` — MCP identities/exposure/collisions, deferred tool search, request-scoped binding, raw-vs-model outputs and truncation.
- `CODEX_TO_CEREBRO_GAP.md` — grounded comparison against current Cerebro runtime with prioritized gaps and explicit mechanisms not to copy.
- `CEREBRO_HARNESS_V1.md` — smallest proposed model-agnostic harness architecture and migration/test plan.
- `RESEARCH_LOG.md` — chronological checkpoints.
- `HANDOFF.md` — current resume point and constraints.

## Research conclusion

The strongest reusable boundaries are:

- immutable request/step snapshots;
- provider adapter + model profile separation;
- provider-neutral inference events/errors;
- typed/versioned context state plus compaction;
- canonical tool identity, request-scoped exposure and terminal results;
- raw tool output separated from bounded model-visible output;
- durable agent-turn/event/checkpoint state independent of final workspace messages;
- typed recovery/cancellation/suspend/resume semantics;
- completion/evidence policy separate from model self-report;
- durable communication separated from scheduling/wake semantics.

Cerebro should keep its own Slack-like shared-channel collaboration, agent identity, attribution, leases, budgets, polling and final-message persistence rather than replacing those with Codex's product model.

## Current implementation boundary

Cerebro already owns an `AgentRuntime`, provider streaming abstraction, context construction, MCP/tool execution, persistence, collaboration channels, usage tracking and turn controls. Harness v1 should evolve those seams incrementally rather than create a parallel application.

The recommended next engineering slice is Phase 1 from `CEREBRO_HARNESS_V1.md`: introduce canonical Cerebro inference/provider/error types and adapt the current OpenAI-compatible provider behind them, with behavior-preserving tests. Before freezing that contract, validate it against one materially different current native provider API such as Gemini or Anthropic so it does not become OpenAI Chat Completions renamed.
