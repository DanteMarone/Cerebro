# Codex Harness Research Handoff

This file exists so a fresh ChatGPT session or another AI agent can resume this research without relying on chat history.

## Purpose

Cerebro is evolving from a Slack-shaped interface around externally harnessed agents into a model-agnostic agent runtime that can call model-provider APIs directly. The goal of this research is to mine the public `openai/codex` repository for harness engineering ideas that can inform a Cerebro-native harness.

Primary research tracker: GitHub issue #202 (`Research: map OpenAI Codex harness for Cerebro`).

Research branch: `research/codex-harness-mining`.

## Current architectural direction

Cerebro should remain the source of truth for:

- channel/shared conversation state
- agent identity/persona
- provider/model selection
- tool permissions and execution
- context construction and compaction
- task/session state
- collaboration between agents
- persistence, budgets, telemetry, recovery and verification

The intended end state is that GPT, Claude, Gemini, DeepSeek and local models can all act as Cerebro-native agents through direct provider APIs while sharing Cerebro's collaboration environment and tool layer. Existing CLI harnesses (Codex CLI, Claude Code, Antigravity, etc.) may remain temporarily as reference/senior-agent implementations during development.

Do not assume raw provider APIs reproduce vendor harness quality. The research target is the engineering around the model: prompts/instructions, context assembly, tool design, filesystem behavior, sandbox/permissions, recovery, compaction, verification, sessions/events, subagents and observability.

## Research strategy

Use Codex as a reference/donor implementation, not as a wholesale base for Cerebro.

Preferred approach:

1. Understand and map Codex behavior from source.
2. Classify each relevant mechanism as:
   - conceptual inspiration only
   - independently reimplemented
   - adapted from upstream
   - copied substantially/verbatim
3. Decide what fits Cerebro's architecture.
4. Only after design review, implement selected pieces.

The current research phase MUST NOT copy Codex implementation code into Cerebro. Documentation, architecture analysis, small quoted identifiers/signatures, source-path references and descriptions are allowed.

## Apache-2.0 provenance policy

The upstream Codex repository is Apache-2.0 licensed. Treat provenance conservatively.

For any finding that could later influence Cerebro implementation, record:

- upstream repository (`openai/codex`)
- upstream file path
- exact upstream commit SHA used for analysis
- license/NOTICE status at that commit
- what engineering idea or code is being considered
- Cerebro destination/component, if known
- usage classification:
  - conceptual inspiration only
  - independently reimplemented
  - adapted from upstream
  - copied substantially/verbatim
- whether attribution/license notice is required
- modifications made if code is later adapted/copied

If actual upstream code is later copied or adapted, preserve applicable notices and document the lineage before merging. Do not imply OpenAI endorsement or use OpenAI/Codex trademarks as Cerebro branding.

A future `THIRD_PARTY_NOTICES.md` and/or provenance ledger may be appropriate once implementation begins.

## Research deliverables

Produce durable files under `docs/research/codex-harness/` covering:

1. `UPSTREAM_BASELINE.md`
   - pinned upstream commit
   - repository/license/NOTICE facts
   - important top-level crates/components
2. `ARCHITECTURE_MAP.md`
   - inbound request > session/turn > context assembly > model request > tool loop > completion
3. `CONTEXT_AND_PROMPTS.md`
   - system/developer instructions
   - project/repo instructions such as AGENTS.md
   - context budgeting, ordering, caching and compaction
4. `TOOLS_AND_EXECUTION.md`
   - tool registry/schema
   - shell/file editing/apply_patch/git/web/MCP
   - sandbox and approval boundaries
5. `RECOVERY_AND_VERIFICATION.md`
   - failed tool calls, retries, timeouts, cancellation, recovery, task completion and verification
6. `SESSIONS_EVENTS_AND_MULTIAGENT.md`
   - sessions/threads/turns/events
   - subagents/collaboration if present
7. `CODEX_TO_CEREBRO_GAP.md`
   - compare Codex mechanisms against Cerebro's current `AgentRuntime`, providers, context builder, MCP layer, persistence and collaboration model
8. `CEREBRO_HARNESS_V1.md`
   - proposed first implementation after mining is complete

Each claim should cite exact upstream paths and the pinned commit where practical. Prefer source and tests over assumptions. Use issues/PR history when it explains why something was designed a certain way.

## Division of labor

ChatGPT in this conversation is the primary source archaeologist and documentation/provenance keeper because it can read public GitHub source and write directly to the Cerebro repository without consuming paid coding-agent credits.

Harnessed agents should be used later for things ChatGPT cannot do well from chat alone:

- cloning/building/running Codex locally
- dynamic tracing
- runtime probes
- compiling/testing hypotheses
- independent review of important conclusions

## Current status

Completed before this handoff:

- Research branch `research/codex-harness-mining` created from Cerebro `main`.
- Issue #202 created with research questions, deliverables and provenance rules.
- `docs/research/codex-harness/README.md` created as the research landing page.

Next action after this handoff:

1. Resolve the current HEAD commit of public `openai/codex` and pin it.
2. Inspect `LICENSE`, any `NOTICE` files, root workspace structure and relevant top-level documentation at that exact commit.
3. Write `UPSTREAM_BASELINE.md`.
4. Begin tracing the request/session/turn path inward toward context construction and model invocation.

## Important constraint

Do not modify Cerebro runtime behavior on this research branch unless Dante explicitly changes the scope. This branch is for research/design/provenance artifacts first.
