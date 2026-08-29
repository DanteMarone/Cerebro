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
- Root `LICENSE` inspected at the pinned commit: Apache License 2.0, with appendix copyright notice `Copyright 2024 Block, Inc.`.
- Root contents inspected. No root `NOTICE` file is present. GitHub filename search for `NOTICE` at the then-current baseline returned only an application source file named `SecureStorageNotice.tsx`, not a legal NOTICE file. Third-party attribution/licensing material still needs a conservative deeper inspection (notably `vendor/`, dependency manifests/lockfiles, package metadata, and any generated distribution notices).
- Repository root includes major areas `crates/`, `documentation/`, `services/`, `ui/`, `vendor/`, `examples/`, `evals/`, `workflow_recipes/`, plus Rust workspace `Cargo.toml`/`Cargo.lock`.

## Next actions

1. Complete legal/provenance baseline: inspect `deny.toml`, workspace/package license metadata, `vendor/`, UI package manifests/lockfiles, and any third-party notice generation/distribution paths. Record in `UPSTREAM_BASELINE.md`.
2. Map exact repository structure at the pinned commit, especially `crates/` and runtime boundaries.
3. Mine the core agent/control loop first, retaining exact upstream paths and marking confirmed source behavior versus inference.
4. Proceed through providers/models, prompts/context/compaction, tools/MCP/execution/permissions, sessions/recovery/delegation, runtime surfaces, observability/event state.
5. Only after Goose research is durable, read the Codex artifacts from issue #202 for `GOOSE_VS_CODEX.md`.
6. Keep this file current after each substantial research increment.

## Required deliverables

- `UPSTREAM_BASELINE.md`
- `ARCHITECTURE_MAP.md`
- `PROVIDERS_AND_MODELS.md`
- `CONTEXT_AND_PROMPTS.md`
- `TOOLS_MCP_AND_EXECUTION.md`
- `SESSIONS_RECOVERY_AND_DELEGATION.md`
- `GOOSE_VS_CODEX.md`
- `CEREBRO_TAKEAWAYS.md`
- `HANDOFF.md`
