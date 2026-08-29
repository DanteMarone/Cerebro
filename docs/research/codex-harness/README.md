# Codex Harness Mining

This directory contains the research used to understand the public `openai/codex` harness and decide what Cerebro should copy conceptually, independently reimplement, adapt under Apache-2.0, or reject.

Tracking issue: #202
Research branch: `research/codex-harness-mining`

## Ground rules

1. This phase is research and design first. Do not transplant Codex implementation code into Cerebro while mapping the system.
2. Every material finding must point to the exact upstream repository path and a pinned upstream commit SHA.
3. If later implementation copies or adapts Codex source, classify and record that provenance before the code is merged.
4. Preserve all applicable Apache-2.0 copyright, license, NOTICE, patent, and attribution obligations for copied/adapted material.
5. Do not imply OpenAI sponsorship or use Codex/OpenAI trademarks as Cerebro product branding.
6. Prefer independently written Cerebro implementations when the value is the engineering idea rather than the exact upstream code.

## Provenance classification

Each implementation-relevant finding should be classified as one of:

- **Conceptual inspiration only** — architecture/behavior learned from Codex; Cerebro implementation written independently.
- **Independent reimplementation** — behavior intentionally reproduced without copying substantial implementation expression.
- **Adapted from upstream** — Codex implementation was used as a starting point and modified.
- **Copied substantially/verbatim** — substantial upstream implementation is retained.

For the last two categories, retain applicable notices and document modifications.

## Required provenance record

```text
Codex component:
Upstream repository: openai/codex
Upstream commit:
Upstream path(s):
License/NOTICE notes:

Finding:

Cerebro component/destination:
Usage classification:
Attribution required:
Modifications, if adapted/copied:
Reviewer:
```

## Research map

The investigation should trace these areas end-to-end rather than treating them as isolated files:

1. Request/session lifecycle
2. System/developer/model instructions
3. Repository instruction discovery and scoping (`AGENTS.md` and related behavior)
4. Context construction and token budgeting
5. Provider/model capability abstraction
6. Tool registration and tool schemas
7. Shell/process execution
8. File reading/search/editing and `apply_patch`
9. Git behavior
10. MCP/web/external tools
11. Approval, sandbox, and permission boundaries
12. Agent loop and tool-result reinjection
13. Failure handling, retry, timeout, cancellation, and recovery
14. Compaction/checkpointing
15. Completion/verification behavior
16. Session persistence, event model, and observability
17. Multi-agent/subagent collaboration
18. Tests and historical GitHub issues/PRs that explain design decisions

## Planned artifacts

- `00-upstream-snapshot.md` — exact Codex commit/license/NOTICE baseline used for the study.
- `01-architecture-map.md` — end-to-end harness flow.
- `02-context-and-instructions.md`
- `03-tools-and-execution.md`
- `04-state-compaction-recovery.md`
- `05-sandbox-permissions.md`
- `06-multi-agent.md`
- `07-cerebro-gap-analysis.md`
- `08-harness-v1-proposal.md`
- `PROVENANCE.md` — implementation-relevant upstream provenance ledger.

## Current implementation boundary

Cerebro already owns an `AgentRuntime`, a provider abstraction, context construction, MCP/tool execution, persistence, collaboration channels, usage tracking, and turn controls. The purpose of this research is not to replace those blindly with Codex. It is to identify which Codex harness ideas improve those existing seams and where Cerebro's multi-provider, multi-agent goals require a different design.
