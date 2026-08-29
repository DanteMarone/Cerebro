# Goose harness research handoff

Issue: #203 — `Research: mine Goose harness architecture for Cerebro`

Research branch: `research/goose-harness-mining`

Upstream repository: `aaif-goose/goose`

Pinned upstream baseline: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification for all implementation-relevant findings in this phase: **conceptual inspiration only**. Do not copy or adapt Goose implementation code into Cerebro without a new explicit provenance decision. No Cerebro runtime code was modified by this research task.

## Status

The issue #203 open-ended Goose harness mining pass is complete enough to stop. All requested deliverables exist under `docs/research/goose-harness/` and the comparative Codex stage used only Cerebro's already-durable issue #202 research rather than re-mining upstream Codex.

The next useful work is harness design/implementation planning from the combined Codex + Goose findings, not another broad Goose source sweep. Re-open Goose source only for a specific unresolved implementation hypothesis, and keep using the immutable baseline below unless a new baseline is deliberately recorded.

## Pinned Goose baseline

- repository: `aaif-goose/goose`
- commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`
- tree: `48a4b32772024ee400fed1489b646ab6f611fb06`
- parent: `0257d0930fbaaf468e72cd555607310482526dce`
- commit title: `fix(ui): render untagged fenced code blocks as proper code blocks (#11653)`
- authored: `2026-08-28T20:09:13Z`

At baseline verification time upstream `main` resolved to that exact commit. Do not silently move the research baseline if upstream advances.

## Legal/provenance baseline

- Root project license at the pinned commit is Apache License 2.0.
- Root `LICENSE` appendix includes `Copyright 2024 Block, Inc.`.
- No legal root `NOTICE` file was found in the pinned repository tree.
- This does **not** imply third-party attribution obligations are absent. Dependency manifests/lockfiles and distribution packaging still govern third-party obligations.
- `deny.toml` is dependency-license policy/check configuration, not an exhaustive distributable attribution artifact.
- `vendor/v8` is a local compatibility package depending on/re-exporting `v8-goose = "=139.0.0"`; no separate license/notice file was present in that directory.
- All findings/recommendations in this pass remain `conceptual inspiration only`; no Goose code was copied or adapted.

## Important baseline correction already made

An early research checkpoint briefly recorded stale workspace metadata. It was corrected before the architecture findings were finalized.

The exact pinned root `Cargo.toml` uses:

- workspace members `crates/*` plus `vendor/v8`;
- edition `2021`;
- workspace version `1.48.0`;
- Rust `1.94.1`;
- authors `AAIF <ai-oss-tools@block.xyz>`;
- repository `https://github.com/aaif-goose/goose`.

There is no root `package.json` at the pinned snapshot and there is no `crates/goose-server` directory. Server behavior used by the desktop is exposed through the shared Goose CLI/core `serve` surface.

## Main Goose conclusions

All paths below refer to the pinned Goose commit.

### 1. Goose is in an agent-loop architectural transition

- `crates/goose/src/agents/agent.rs` remains the product-specific agent/orchestration layer.
- `crates/goose-agent/` contains a newer generic/GDK loop package.
- `crates/goose/src/agents/state_machine/*` adapts Goose product behavior into that generic loop.
- The new state-machine path remains explicitly experimental behind `GOOSE_STATE_MACHINE` at this commit; the legacy reply loop remains relevant/default.

The important direction is a re-entrant persisted-state machine:

- ordered operations decide applicability;
- operations return explicit effects;
- the product `SessionManager` persists effects;
- the machine reloads durable session state between steps;
- operation notes can persist enough metadata to avoid redoing already-applied work after reconstruction;
- cancellation and user interaction cause explicit yield rather than requiring the whole task to be considered complete.

This is one of the strongest conceptual findings, but it should not be described as a fully settled/default Goose architecture yet.

### 2. Provider abstraction is capability-rich but spans two abstraction levels

- `crates/goose-provider-types/src/base.rs`
- `crates/goose-provider-types/src/model.rs`
- `crates/goose/src/providers/*`
- `crates/goose/src/acp/provider.rs`

Goose supports direct APIs, local inference, OAuth/subscription paths, CLI-backed harnesses and ACP-backed external agents. Providers expose model/context/reasoning/tool/permission/session capabilities.

ACP demonstrates the architectural leak: a `Provider` can own context, approvals and external session continuity. For Cerebro, `PROVIDERS_AND_MODELS.md` and `CEREBRO_TAKEAWAYS.md` recommend keeping direct model `ProviderAdapter` and external-harness `ExternalAgentAdapter` contracts separate while preserving explicit capabilities.

### 3. Durable history and active model context are separate

- `crates/goose/src/context_mgmt/mod.rs`
- `crates/goose-context-management/src/*`
- `crates/goose/src/agents/prompt_manager.rs`
- conversation message/visibility types.

Compaction keeps history available to the human while making older material agent-invisible, inserts an agent-only summary/continuation, and can separately summarize old tool pairs. Provider-owned context disables Goose-owned compaction.

Prompt construction is structured/cache-aware: extension information is stable-sorted, dynamic contributions are separate from persistent extras, project hints are bounded/sanitized, and the manager deliberately stabilizes time information for prompt caching.

### 4. MCP is a common execution protocol, but Goose policy stays host-owned

- `crates/goose/src/agents/mcp_client.rs`
- `crates/goose/src/agents/extension_manager.rs`
- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/agents/platform_extensions/developer/*`

External MCP servers and Goose platform extensions share the same client trait. `ExtensionManager` manages ownership metadata, process/transports, dynamic tool cache/version and common tool-name repair.

Goose still owns execution policy: working directory, shell behavior, credential substitution, approval, safety/egress inspection, cancellation and output limits. MCP does not bypass host policy.

### 5. Tool permission/safety is a modular inspector pipeline

- `crates/goose/src/tool_inspection.rs`
- `crates/goose/src/permission/permission_inspector.rs`
- `crates/goose/src/security/security_inspector.rs`
- `crates/goose/src/security/egress_inspector.rs`
- `crates/goose/src/agents/agent.rs`

The examined agent installs security, egress, adversary, permission and repetition inspectors. Results are combined conservatively; one inspector's allow does not override another's deny/approval. Approval can persist explicit AlwaysAllow/NeverAllow decisions.

Inspector implementation/order/modes are Goose product choices. The reusable idea is a policy pipeline independent from tool transport/execution.

### 6. Recovery/completion is multi-layered

- `crates/goose-provider-types/src/errors.rs`
- `crates/goose/src/agents/retry.rs`
- `crates/goose/src/agents/state_machine/ops_retry.rs`
- `ops_maxturns.rs`
- `ops_exit_on_error.rs`

Provider failures are typed. Recipe task verification/retry is separate from provider failure retry. In the new state-machine path retry attempt metadata is stored on surviving persisted message metadata before conversation reset.

Normal model end-of-turn is not final task acceptance: goal/grind, success checks, max-turn policy and errors can continue/yield/fail afterward.

### 7. Subagents are real child sessions

- `crates/goose/src/agents/subagent_task_config.rs`
- `crates/goose/src/agents/subagent_handler.rs`
- `crates/goose/src/agents/platform_extensions/summon.rs`

Delegation creates a fresh persisted `SessionType::SubAgent` with parent id, provider/model/extensions/working directory and explicit turn budget. It supports synchronous and tracked background execution. The examined path prevents subagents from recursively delegating again.

The generalizable lesson is durable child identity + explicit execution inheritance/budgets, not Goose's exact one-level policy.

### 8. Desktop/CLI/server share the same backend runtime

- `crates/goose-cli/src/cli.rs`
- `ui/desktop/src/main.ts`
- `ui/desktop/src/gooseServe.ts`

Electron launches the Goose binary's loopback `serve` surface, injects a generated secret, health-checks it and connects over ACP/WebSocket. The desktop is therefore a client/process supervisor around the shared Rust harness rather than an independent agent implementation.

### 9. Events/effects/telemetry are different concepts

- `crates/goose-agent/src/events.rs`
- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/gen_ai_telemetry.rs`

The generic client event stream is intentionally small; explicit durable effects carry richer state transitions; OpenTelemetry separately records model/tool/usage details. Message/tool content capture is opt-in through the GenAI telemetry setting.

## Codex comparison source and conclusion

Codex issue #202 research was read only after Goose findings were durable.

Comparison source:

- Cerebro branch: `research/codex-harness-mining`
- branch head read: `3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- its pinned upstream baseline: `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- relevant durable files: `ARCHITECTURE_MAP.md`, `CONTEXT_AND_PROMPTS.md`, `TOOLS_AND_EXECUTION.md`, `RECOVERY_AND_VERIFICATION.md`, `SESSIONS_EVENTS_AND_MULTIAGENT.md`, `PROVIDER_ABSTRACTION.md`, `MCP_TOOL_SEARCH_AND_OUTPUTS.md`, `CEREBRO_HARNESS_V1.md`, `HANDOFF.md` under `docs/research/codex-harness/`.

Codex upstream was **not** re-mined.

The strongest combined conclusion is recorded in `GOOSE_VS_CODEX.md`:

> Codex-style immutable request-scoped snapshots (`StepContext` / exact tool router) fit naturally inside a Goose-style re-entrant durable effect loop. Cerebro should combine those invariants independently while keeping its provider/tool contracts more model-agnostic than either upstream.

## Durable deliverables

All requested issue #203 deliverables now exist:

- `UPSTREAM_BASELINE.md` — legal/provenance/repository baseline.
- `ARCHITECTURE_MAP.md` — surfaces > product agent > generic loop > providers > tools > state > observability.
- `PROVIDERS_AND_MODELS.md` — provider/model capabilities and ownership tradeoffs.
- `CONTEXT_AND_PROMPTS.md` — prompt composition, visibility, compaction/context ownership.
- `TOOLS_MCP_AND_EXECUTION.md` — MCP/extensions, filesystem/shell, approvals/safety/failure/cancellation.
- `SESSIONS_RECOVERY_AND_DELEGATION.md` — SQLite sessions, provider resume, retries, completion, child sessions.
- `GOOSE_VS_CODEX.md` — independent convergence/divergence against completed issue #202 research.
- `CEREBRO_TAKEAWAYS.md` — prioritized independent Cerebro architecture takeaways and provenance ledger.
- `HANDOFF.md` — this file.

## Important artifact commits

- `b8b2c34fe8255ed3269edf655ffe889f6024e65a` — initialize handoff immediately.
- `52cb69747c69af63394dda94ebb0c8db4bfb344c` — initial upstream baseline.
- `725dca055d010dfe1e8580eb89326fc65bf9fc3e` — correct exact pinned workspace metadata.
- `d742e6f8cfcfe36ee6b0abce84f062e904f097b2` — architecture map.
- `f7edd1cea758e9c77cd66c298e00969c211afd7e` — providers/models.
- `161cc52cad91a25641d27bf6c669b6e3716d0976` — context/prompts.
- `875a6a81b23a491297208a390c61d0e5fc62b327` — MCP/tools/execution.
- `794710bd60f04e4d9d594e72fc9b36a37cb73497` — sessions/recovery/delegation.
- `e956f8bd84d64a4d238a2f22a4d1aab156e68405` — Goose versus durable Codex comparison.
- `5105a7ade11be25b596c4148b57ffa1a2a31dbe6` — Cerebro takeaways/provenance ledger.

## Highest-confidence Cerebro takeaways

Read `CEREBRO_TAKEAWAYS.md` before implementation. The shortest summary is:

1. Cerebro owns durable agent/task/turn state; provider sessions are replaceable execution state.
2. Use a re-entrant durable reducer/effect loop plus an immutable `StepSnapshot` per inference/tool-call batch.
3. Persist complete history/events and derive provider-specific context views/compaction checkpoints.
4. Separate native model `ProviderAdapter` from external-agent/harness adapters.
5. Keep `ModelProfile` and capability policy separate from provider identity.
6. Own a canonical tool catalog/planner/runtime above MCP; plan exact exposure/bindings per step.
7. Enforce permissions/security/egress at runtime through policy modules, not prompt instructions.
8. Give every admitted tool call one durable terminal result and keep full/raw output separate from model-visible output.
9. Treat retry, context migration, cancellation, suspend/recover and semantic task verification as distinct policies.
10. Treat provider completion as inference completion; a separate `CompletionPolicy` decides task acceptance.
11. Represent delegated agents as durable child tasks/sessions with lineage, model/tool scope, budget and depth policy.
12. Separate durable execution events/checkpoints, transient stream/UI events and telemetry.

## Remaining uncertainty / caveats

- The Goose generic state-machine path is explicitly experimental at this baseline. Treat it as architectural direction/evidence, not proof that the exact operation ordering/API has fully replaced the legacy loop.
- The provider registry is broad and evolving; the research focused on ownership/capability architecture rather than exhaustively documenting every adapter.
- No Goose equivalent of Codex's deferred/searchable tool-catalog architecture was confirmed in the examined pinned paths. That is a “not found in this research slice” statement, not a permanent claim about all Goose versions/features.
- Some security/adversary behaviors are configuration-gated. The docs distinguish the existence of the inspector architecture from assuming every check is active in every runtime configuration.
- Dependency licensing/attribution was conservatively baselined but not transformed into a distribution bill of materials; that was outside this architecture-only scope.

## Exact next task for a fresh agent

Do not restart broad Goose archaeology.

The next project step should use the combined issue #202 + #203 research to refine the Cerebro Harness v1 implementation design, specifically reconciling:

- Codex research's `StepSnapshot` / canonical inference and tool model;
- Goose research's re-entrant durable effect/reducer architecture;
- the explicit split between native `ProviderAdapter` and external `ExternalAgentAdapter`;
- Cerebro's existing workspace/channel/task/event/lease product model.

Any implementation should be independently designed in Cerebro's own code and naming, with provenance classification maintained per change.
