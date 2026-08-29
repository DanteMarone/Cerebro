# Goose harness research handoff

Issue: #203 — `Research: mine Goose harness architecture for Cerebro`

Research branch: `research/goose-harness-mining`

Upstream repository: `aaif-goose/goose`

Pinned upstream baseline: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification for all implementation-relevant findings in this phase: **conceptual inspiration only**. Do not copy or adapt Goose implementation code into Cerebro. Do not modify Cerebro runtime code on this branch.

## Current state

- Issue #203 read and confirmed as the governing research plan.
- Cerebro research branch verified at task start: `57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`.
- Upstream Goose commit `8ae4e4ba02836529790f47109b8785e8b42843a7` verified to exist and deliberately selected as the immutable research baseline.
- At verification time, upstream `main` also resolved to that exact commit. Do not silently move the baseline if upstream advances.
- Baseline commit metadata: commit message `fix(ui): render untagged fenced code blocks as proper code blocks (#11653)`, authored 2026-08-28 20:09:13Z; tree `48a4b32772024ee400fed1489b646ab6f611fb06`.
- `UPSTREAM_BASELINE.md` now records the legal/provenance and repository baseline.
- Root `LICENSE` is Apache License 2.0 with appendix copyright `Copyright 2024 Block, Inc.`. Root README and Rust workspace metadata corroborate Apache-2.0; `ui/desktop/package.json` also declares Apache-2.0.
- No legal root `NOTICE` file was found in the pinned tree. Do not infer from this that dependency-specific attribution obligations are absent.
- `deny.toml` enforces a Rust dependency-license allowlist and explicit exceptions; this is policy/check configuration, not an exhaustive distribution-attribution artifact.
- `vendor/v8` is a local compatibility crate that depends on/re-exports `v8-goose = "=139.0.0"`; no separate LICENSE/NOTICE file was present in that directory.
- There is no root `package.json` in the pinned snapshot. JavaScript package roots include `ui/package.json`, `ui/desktop/package.json`, and `documentation/package.json`.
- Repository root includes major areas `crates/`, `documentation/`, `services/`, `ui/`, `vendor/`, `examples/`, `evals/`, `workflow_recipes/`, plus Rust workspace `Cargo.toml`/`Cargo.lock`.

## Durable commits so far

- `b8b2c34fe8255ed3269edf655ffe889f6024e65a` — initialize `HANDOFF.md`.
- `52cb69747c69af63394dda94ebb0c8db4bfb344c` — add `UPSTREAM_BASELINE.md`.

## Next actions

1. Map exact Rust/runtime structure at the pinned commit, starting with `crates/goose`, `goose-llm`, `goose-providers`, `goose-mcp`, `goose-server`, `goose-cli`, and `goose-acp`.
2. Mine the core agent/control loop first, retaining exact upstream paths and marking confirmed source behavior versus inference.
3. Proceed through providers/models, prompts/context/compaction, tools/MCP/execution/permissions, sessions/recovery/delegation, runtime surfaces, observability/event state.
4. Commit each substantial research increment into the appropriate required deliverable.
5. Only after Goose research is durable, read the Codex artifacts from issue #202 for `GOOSE_VS_CODEX.md`.
6. Keep this file current throughout.

## Required deliverables

- `UPSTREAM_BASELINE.md` — created
- `ARCHITECTURE_MAP.md`
- `PROVIDERS_AND_MODELS.md`
- `CONTEXT_AND_PROMPTS.md`
- `TOOLS_MCP_AND_EXECUTION.md`
- `SESSIONS_RECOVERY_AND_DELEGATION.md`
- `GOOSE_VS_CODEX.md`
- `CEREBRO_TAKEAWAYS.md`
- `HANDOFF.md` — created, keep current
