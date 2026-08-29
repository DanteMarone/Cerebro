# Goose harness research handoff

Issue: #203 — `Research: mine Goose harness architecture for Cerebro`

Research branch: `research/goose-harness-mining`

Upstream repository: `aaif-goose/goose`

Pinned upstream baseline: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification for all implementation-relevant findings in this phase: **conceptual inspiration only**. Do not copy or adapt Goose implementation code into Cerebro. Do not modify Cerebro runtime code on this branch.

## Current state

- Issue #203 read and confirmed as the governing research plan.
- Cerebro research branch verified at task start: `57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`.
- Upstream Goose commit `8ae4e4ba02836529790f47109b8785e8b42843a7` verified to exist and deliberately selected as the immutable research baseline. Upstream `main` resolved to this same SHA at verification time.
- `UPSTREAM_BASELINE.md` records the legal/provenance and repository baseline and was corrected against the exact pinned `Cargo.toml`: workspace members are `crates/*` plus `vendor/v8`; workspace package metadata is edition 2021, version 1.48.0, Rust 1.94.1, AAIF authorship, Apache-2.0, and the `aaif-goose/goose` repository URL.
- Root license is Apache-2.0. No legal root `NOTICE` file was found. Treat dependency attribution conservatively; `deny.toml` is dependency-license policy, not an exhaustive distribution notice.
- `vendor/v8` is a local compatibility crate depending on/re-exporting `v8-goose = "=139.0.0"`.
- No root `package.json`; JavaScript roots include `ui/` and `documentation/`.

## Core architecture findings already confirmed

All paths below are at the pinned upstream commit.

- `crates/goose/src/agents/agent.rs` remains the product-specific Goose agent and owns provider, extensions, prompt manager, approvals, retries, tool inspection, hooks, container state, and steering queues.
- There are two control-loop paths at this snapshot. The newer path is still explicitly experimental: `Agent::reply` dispatches to it when `GOOSE_STATE_MACHINE` is enabled (or for bang-shell handling); otherwise the legacy reply loop remains relevant.
- `crates/goose/src/agents/state_machine/mod.rs` describes the newer path as an ordered, re-entrant pipeline over persisted conversation state.
- `crates/goose-agent/` is the generic/GDK-facing loop package (`Cargo.toml` description: `The GDK's Agent Loop`). `machine.rs` defines generic `StateMachine`, `MachineSession`, `SessionLoader`, and `EffectHandler` seams; `operation.rs` defines composable operations/inference, effects, yield semantics, and persisted operation notes.
- The generic machine reloads durable session state between steps. Product Goose supplies concrete operations and a `SessionManager` effect handler (`crates/goose/src/agents/state_machine/session.rs`). This is a significant conceptual seam for Cerebro, but remains conceptual inspiration only.
- Operations can contribute inference tools, prompt parts, and MOIM parts. The inference step aggregates those contributions before calling the provider.
- Cancellation is represented by a shared `CancellationToken`; applied results during cancellation are forced to yield to the client.
- Product operations include steering, max turns, bang-shell, compaction, tool-pair compaction, approval, retry/error handling, tool execution, project/recipe/skills/slash commands, hooks, and unknown-tool handling.
- `goose-agent/src/events.rs` exposes a small event model: message, provider usage, per-message usage, MCP notification, and history replacement.

## Provider/context findings already confirmed

- `crates/goose-provider-types/src/base.rs` is the shared provider contract. Providers stream model output and expose metadata/capability hooks; a provider can declare `manages_own_context()`, which changes harness behavior.
- `supports_builtin_tools()` defaults to the inverse of `manages_own_context()`.
- Provider metadata carries known-model capability records, setup/config data, optional fast model, and deprecation information.
- Model capability data includes context limit, costs, cache-control support, reasoning, thinking-preservation representation, and request parameters.
- `crates/goose-provider-types/src/model.rs` separates model config from provider implementation and deliberately prevents provider-specific request parameters from bleeding across model switches/subagent delegation. Default context fallback is 128k when not resolved elsewhere.
- `crates/goose/src/context_mgmt/mod.rs` disables harness compaction when a provider owns context. Otherwise it performs threshold-based compaction and can separately summarize old tool-call pairs.
- Compaction preserves historical messages for the user while making old history agent-invisible, then inserts an agent-only summary/continuation. It therefore separates persisted conversation history from active model context instead of deleting history.
- `crates/goose/src/agents/prompt_manager.rs` composes a stable, cache-aware system prompt: extension info is sorted, current time is rounded/fixed at manager construction, project hints and operation contributions are added as prompt extras, and unusual Unicode tag characters are sanitized.

## Tool/session findings already confirmed

- `crates/goose/src/agents/tool_execution.rs` represents a tool call as a final result plus optional MCP-notification and action-required streams. Approval requests are surfaced as user-only action-required messages and can persist AlwaysAllow/NeverAllow decisions through the permission manager.
- `crates/goose/src/session/session_manager.rs` persists sessions in SQLite (`sessions.db`, schema version 16). Session state includes conversation, provider/model, mode, extensions, usage/cost, recipe/schedule data, project id, and `parent_session_id`.
- Session types include User, Scheduled, SubAgent, Hidden, Terminal, Gateway, and Acp.

## Durable commits so far

- `b8b2c34fe8255ed3269edf655ffe889f6024e65a` — initialize `HANDOFF.md`.
- `52cb69747c69af63394dda94ebb0c8db4bfb344c` — add initial `UPSTREAM_BASELINE.md`.
- `a2a93a4d4d6c94d592485087526a4704cbdeb52e` — provenance handoff checkpoint.
- `725dca055d010dfe1e8580eb89326fc65bf9fc3e` — correct exact pinned workspace metadata in baseline.

## Next actions

1. Finish provider capability and registry archaeology, including provider-owned context/session behavior and model differences.
2. Finish MCP/extensions/tool discovery, developer filesystem/shell behavior, permission/security inspectors, and tool failure semantics.
3. Finish retry/cancellation/completion and session resume semantics.
4. Mine subagent/delegation inheritance and parent/child session behavior.
5. Map CLI/desktop/server/SDK/ACP runtime boundaries and telemetry.
6. Write and commit the Goose deliverables as each topic closes.
7. Only after the Goose findings are durable, read issue #202's existing Codex research for the comparative `GOOSE_VS_CODEX.md`; do not redo Codex upstream archaeology.
8. Finish `CEREBRO_TAKEAWAYS.md` and update this handoff with all final commits and remaining uncertainty.

## Required deliverables

- `UPSTREAM_BASELINE.md` — created
- `ARCHITECTURE_MAP.md`
- `PROVIDERS_AND_MODELS.md`
- `CONTEXT_AND_PROMPTS.md`
- `TOOLS_MCP_AND_EXECUTION.md`
- `SESSIONS_RECOVERY_AND_DELEGATION.md`
- `GOOSE_VS_CODEX.md`
- `CEREBRO_TAKEAWAYS.md`
- `HANDOFF.md` — created and current through the core-loop pass
