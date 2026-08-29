# Goose upstream baseline

## Research boundary

Cerebro issue: #203 — `Research: mine Goose harness architecture for Cerebro`

Cerebro branch: `research/goose-harness-mining`

Upstream repository: `aaif-goose/goose`

Pinned upstream commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`

This SHA is the immutable source baseline for this research. It was verified to exist before source-level claims were made, and upstream `main` resolved to the same SHA at verification time. If upstream moves later, this research does not silently move with it.

All implementation-relevant findings in this research phase are classified as **conceptual inspiration only**. No Goose implementation code is to be copied or adapted into Cerebro as part of this work.

## Baseline identity

Confirmed from upstream commit metadata at the pinned SHA:

- commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`
- tree: `48a4b32772024ee400fed1489b646ab6f611fb06`
- parent: `0257d0930fbaaf468e72cd555607310482526dce`
- commit message: `fix(ui): render untagged fenced code blocks as proper code blocks (#11653)`
- authored timestamp: `2026-08-28T20:09:13Z`

## License and provenance baseline

### Project license

Confirmed at `LICENSE` on the pinned commit:

- Apache License 2.0 text is present at the repository root.
- The appendix contains `Copyright 2024 Block, Inc.`.
- Root `README.md` also identifies the project as Apache-2.0 licensed.
- Rust workspace metadata in root `Cargo.toml` sets `license = "Apache-2.0"` for workspace packages.
- `ui/desktop/package.json` declares `license: "Apache-2.0"`.

### NOTICE and attribution material

Confirmed from the pinned repository tree:

- No legal root `NOTICE` file was found.
- A repository-wide filename check found a UI source file named `SecureStorageNotice.tsx`; it is application UI and is not a legal NOTICE file.
- No claim is made that absence of a root NOTICE means there are no third-party attribution obligations. Dependency manifests and lockfiles identify a substantial third-party dependency graph.

### Dependency-license policy

Confirmed at `deny.toml` on the pinned commit:

- unlicensed Rust dependencies are denied;
- allowed SPDX licenses include Apache-2.0, MIT, BSD-3-Clause, ISC, Unicode-3.0, OpenSSL, and MPL-2.0;
- explicit exceptions include Unicode-DFS-2016 (`unicode-ident`), CDLA-Permissive-2.0 (`webpki-roots`), MIT for listed Redox crates, and Zlib (`foldhash`).

This is a dependency policy/check configuration, not an exhaustive distributable attribution inventory.

### Vendored/local compatibility material

Confirmed at `vendor/v8/Cargo.toml`:

- the repository carries a small local package named `v8`, version `139.0.0`;
- it depends on `v8-goose = "=139.0.0"` and exists to re-export that package under the expected crate name for Deno compatibility;
- no separate LICENSE/NOTICE file was present in `vendor/v8` in the pinned tree.

This research therefore treats third-party provenance conservatively: Goose's project license is clearly Apache-2.0, while dependency-specific obligations remain governed by the dependency graph and packaging process rather than being inferred away from the absence of a root NOTICE.

## Repository and packaging structure

Confirmed top-level areas at the pinned commit include:

- `crates/` — Rust workspace crates for the core harness and runtime surfaces;
- `ui/` — JavaScript/TypeScript workspaces, including the Electron desktop application;
- `documentation/` — Docusaurus documentation source and its own npm dependency graph;
- `services/` — service-side components;
- `examples/`, `evals/`, `workflow_recipes/` — examples, evaluation material, and workflow recipes;
- `vendor/` — local compatibility/vendor material;
- root `Cargo.toml` and `Cargo.lock` — Rust workspace and dependency lock.

There is **no root `package.json`** at this pinned snapshot. JavaScript package roots live below subdirectories such as `ui/` and `documentation/`.

The root Rust workspace lists these members:

- `crates/goose`
- `crates/goose-cli`
- `crates/goose-bench`
- `crates/goose-server`
- `crates/goose-mcp`
- `crates/goose-test`
- `crates/goose-acp`
- `crates/goose-telemetry`
- `crates/goose-scheduler`
- `crates/goose-certguard`
- `crates/goose-llm`
- `crates/goose-providers`
- `crates/goose-provider-custom`
- `crates/goose-notification`

Default Rust workspace members are `goose-cli`, `goose`, `goose-mcp`, and `goose-server`.

Workspace package metadata at the pinned commit reports edition 2024, version `1.14.0`, authors `Block <ai-oss@block.xyz>`, and Apache-2.0. Some historical package metadata still references the former `block/goose` repository; the pinned repository itself is `aaif-goose/goose` and the README states Goose is part of the Agentic AI Foundation at the Linux Foundation.

`ui/package.json` is a private workspace root covering `acp`, `text`, `desktop`, and `goose-binary/*`. `ui/desktop/package.json` identifies the Electron app as `goose-app`, product name `Goose`, version `1.48.0`, and depends on the workspace Goose SDK plus ACP/MCP-related client packages. `documentation/package.json` is a private Docusaurus site package with a separate npm lockfile/dependency graph.

## Documentation baseline

The pinned root `README.md` describes three public runtime surfaces: desktop app, CLI, and API. It describes Goose as a local general-purpose AI agent, states support for 15+ model providers, mentions ACP-based use of existing Claude/ChatGPT/Gemini subscriptions, and describes extensions through Model Context Protocol.

The `documentation/` tree is the source for the Docusaurus site and includes `documentation/docs/`, automation material, and contributor/agent guidance. Product documentation is useful as behavioral corroboration, but architecture claims in this research are confirmed against pinned source where possible.

## Source-of-truth rule for the remaining research

Every important source-level finding should name an exact path and implicitly refers to upstream commit `8ae4e4ba02836529790f47109b8785e8b42843a7` unless another immutable source is explicitly named. Behavioral claims are labeled or worded so confirmed source behavior is distinguishable from architectural inference.
