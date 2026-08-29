# OpenAI Codex Upstream Baseline

## Pinned source snapshot

All Codex source analysis in this research set begins from this immutable upstream snapshot unless a document explicitly says otherwise.

- Repository: `openai/codex`
- Branch observed: `main`
- Pinned commit: `0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- Commit time: 2026-08-29 03:59:21 UTC (committer timestamp)
- Commit title: `Preserve permissions when updating session metadata (#41464)`
- Tree SHA: `d34870b6840652fab00b2b7f35799aa495e8fae8`

Do not silently update this SHA as upstream moves. If later research intentionally rebases to a newer Codex snapshot, record a new baseline and explain why.

## License baseline

Upstream root `LICENSE` at the pinned commit is the Apache License, Version 2.0 and contains the appendix notice `Copyright 2025 OpenAI`.

Relevant Apache-2.0 obligations for later source-code reuse include:

- distribute a copy of the Apache-2.0 license with redistributed Work/Derivative Works;
- mark modified upstream files prominently as changed;
- retain applicable copyright, patent, trademark and attribution notices in distributed source derivatives;
- carry applicable `NOTICE` attribution when the upstream Work includes a NOTICE file;
- do not treat the license as a grant of OpenAI trademark/product-name rights.

The root `NOTICE` file exists at this snapshot and contains:

- `OpenAI Codex`
- `Copyright 2025 OpenAI`
- attribution for code derived from Ratatui under the MIT license, including the Ratatui copyright notices.

Therefore any later Cerebro distribution that actually contains applicable Codex-derived material must evaluate both the Apache `LICENSE` requirements and the upstream `NOTICE` attribution. The research phase itself does not copy Codex implementation code into Cerebro.

Upstream references:

- `LICENSE` at `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- `NOTICE` at `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`
- root `README.md` explicitly states the repository is Apache-2.0 licensed.

## Repository shape

The repository is much larger than a CLI wrapper. The Rust workspace (`codex-rs/Cargo.toml`) contains more than one hundred members spanning the harness, protocols, UI clients, execution, sandboxing, tools, providers, memory and collaboration.

For Cerebro harness research, the highest-priority areas initially appear to be:

| Upstream area | Initial relevance to Cerebro |
| --- | --- |
| `codex-rs/core` | Primary Codex business logic / agent runtime. Its README explicitly says it implements the business logic used by Codex UIs. |
| `codex-rs/core-api` | Boundary/API abstractions around core behavior; useful for identifying what Codex considers a stable runtime contract. |
| `codex-rs/app-server` | Headless application-server interface used by rich clients. Documents threads, turns, items, streaming events and approvals. |
| `codex-rs/app-server-protocol` | Typed client/server protocol and event shapes. |
| `codex-rs/protocol` | Core event/config/input/output protocol structures. |
| `codex-rs/model-provider` / `model-provider-info` / `models-manager` | Model/provider capability and selection abstractions. |
| `codex-rs/prompts` and prompt files under `core` | Harness/model instruction material. |
| `codex-rs/context-fragments` and `core/src/context` | Context construction and world-state fragments. |
| `codex-rs/skills` / `ext/skills` | Skills discovery and presentation to the model. |
| `codex-rs/tools` plus `core/src/tools` | Tool definitions, routing and model-facing tool behavior. |
| `codex-rs/apply-patch` | Constrained file-edit primitive. |
| `codex-rs/shell-command`, `exec`, `exec-server*` | Shell/process execution mechanisms. |
| `codex-rs/sandboxing`, `linux-sandbox`, `bwrap`, `execpolicy`, `shell-escalation` | Permission and execution boundaries. |
| `codex-rs/rmcp-client`, `codex-mcp`, `mcp-server`, `ext/mcp` | MCP integration. |
| `codex-rs/thread-store`, `state`, `history`, `rollout`, `rollout-trace` | Durable session/thread/history state and replay/telemetry. |
| `codex-rs/agent-*`, `collaboration-mode-templates`, `ext/agent` | Agent identities, roles, graphs and collaboration/subagent behavior. |
| `codex-rs/memories/*`, `ext/memories` | Persistent memory mechanisms. |
| `codex-rs/otel`, `analytics`, `diagnostics` | Observability/telemetry. |

This is a triage map, not yet a claim that each crate participates in the normal interactive harness path.

## First architectural fact: the UI is not the harness

`codex-rs/core/README.md` states:

> This crate implements the business logic for Codex. It is designed to be used by the various Codex UIs written in Rust.

That separation is important for Cerebro. Codex is not architected as "a terminal UI that happens to call a model"; the core runtime is reusable beneath multiple interfaces.

`codex-rs/app-server/README.md` separately describes `codex app-server` as the interface used to power rich clients such as the VS Code extension. It exposes a bidirectional protocol rather than embedding runtime behavior in the client.

Conceptual implication for Cerebro (classification: **conceptual inspiration only**): keep the Cerebro harness headless and make the Slack-shaped interface a client/subscriber of durable runtime events.

## App-server interaction primitives

At this snapshot, the app-server documentation defines three user/agent interaction primitives:

- **Thread**: conversation between user and Codex, containing multiple turns.
- **Turn**: one conversational turn, normally user input through agent completion, containing multiple items.
- **Item**: individual persisted user inputs and agent outputs, including messages, reasoning, shell commands and file edits.

The documented lifecycle is roughly:

1. client initializes a connection;
2. client starts/resumes/forks a thread;
3. client starts a turn with user input and optional runtime overrides;
4. app-server streams item/tool/output events;
5. turn completes or is interrupted and returns final state/token usage.

This is currently only a protocol-level map. The next research stage must trace these protocol operations into `codex-core` and then through context construction, model invocation and the tool loop.

Conceptual implication for Cerebro (classification: **conceptual inspiration only**): Cerebro already has analogous channel/turn/tool-event concepts, but Codex's explicit item/event model may expose useful separation between durable transcript state and transient execution state.

## Execution/sandbox baseline

`codex-rs/core/README.md` makes clear that local execution policy is a first-class harness concern rather than merely prompt text. Examples at this snapshot include:

- macOS Seatbelt enforcement;
- Linux Landlock/bubblewrap routing depending on policy semantics;
- Windows sandbox backends and split filesystem policies;
- a virtual `apply_patch` CLI entrypoint available to the core runtime.

Conceptual implication for Cerebro: tool authorization and filesystem safety need to be code-enforced. Prompt instructions alone are not an adequate security boundary.

## Provenance ledger entries created by this baseline

| Finding | Upstream path | Usage classification | Current Cerebro use |
| --- | --- | --- | --- |
| Separate reusable core runtime from UI clients | `codex-rs/core/README.md`, `codex-rs/app-server/README.md` | conceptual inspiration only | Supports existing Cerebro headless-runtime direction |
| Thread/turn/item protocol split | `codex-rs/app-server/README.md` | conceptual inspiration only | Candidate vocabulary/data-model comparison |
| Sandbox enforcement belongs below prompts | `codex-rs/core/README.md` | conceptual inspiration only | Compare against Cerebro journals/permissions/MCP execution |
| `apply_patch` is a dedicated execution primitive | `codex-rs/core/README.md`, workspace member `apply-patch` | conceptual inspiration only for now | Investigate before deciding whether to independently implement/adapt |
| Model/provider behavior is split into dedicated crates | `codex-rs/Cargo.toml` | conceptual inspiration only | Compare with Cerebro `Provider` protocol and future capability profiles |

No Codex implementation code has been copied or adapted into Cerebro by this document.

## Next trace

Trace the normal interactive request path at the pinned commit:

`app-server turn/start (or CLI equivalent)`

> thread/session runtime

> context construction and instruction assembly

> model request construction/provider call

> streamed response parsing

> tool dispatch/execution

> tool results added back to context

> repeat inference/tool loop

> persistence/events/completion

The resulting map belongs in `ARCHITECTURE_MAP.md` and should distinguish protocol/UI plumbing from actual harness intelligence.
