# Codex Context and Prompt Architecture

**Status:** Initial confirmed map; more ordering/reconstruction tests still to inspect.

**Pinned upstream:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

No Codex implementation code is copied into Cerebro by this document. Findings are currently **conceptual inspiration only**.

## Main conclusion

Codex does not appear to construct one giant static system prompt. The model-visible request is assembled from several distinct mechanisms with different lifetimes:

1. model/session-level **base instructions**;
2. separately typed developer/user/internal context fragments;
3. a persisted/diffed **World State** describing currently relevant harness/environment state;
4. ordinary conversation/tool history;
5. per-turn skill/plugin/extension injections;
6. a request-scoped tool catalog from `StepContext`;
7. compaction checkpoints that rewrite history while preserving enough user/state context to continue.

That separation is a major candidate design principle for Cerebro Harness v1.

## 1. Base instructions are model-specific session state

During `Session::spawn_internal`, base instructions resolve in this priority order:

1. explicit configuration override;
2. base instructions persisted in resumed conversation/session history;
3. the selected model's instruction template rendered for the selected personality.

The resolved base instructions remain session state and are passed to each model `Prompt` separately from ordinary history items.

Upstream:
- `codex-rs/core/src/session/mod.rs`
- `codex-rs/models-manager/src/model_info.rs`
- `codex-rs/protocol/src/openai_models.rs`

### Model metadata owns more than a model name

`ModelInfo` carries behavioral metadata including, at this snapshot:

- reasoning defaults/options;
- shell tool mode;
- model-specific messages/instruction template;
- whether skills/plugins/apps usage instructions should be included;
- reasoning-summary support;
- verbosity support/default;
- apply-patch mode;
- web-search tool mode;
- output truncation policy;
- input modalities;
- context and maximum-context windows;
- auto-compaction threshold;
- compaction compatibility hash;
- effective usable-context percentage/headroom;
- supported experimental tools;
- search/code-mode/multi-agent behavior and related settings.

`ModelMessages` separately carries model-owned instruction/message material for personality, persistent mode, tools, approvals, collaboration modes, auto-review, permissions, multi-agent behavior, token budgets and confirmation policies.

**Cerebro implication:** the provider adapter should not be the only model-specific abstraction. Cerebro should eventually have a first-class model/harness capability profile containing instruction, tool, context, compaction and behavioral policy.

## 2. The shipped coding prompt is operational behavior, not just persona

The repository contains model-specific/fallback instruction material such as `codex-rs/core/gpt_5_codex_prompt.md` and the model-manager prompt/template machinery.

The inspected GPT-5 Codex prompt contains operational guidance in categories such as:

- preferred repository search methods;
- editing discipline and constrained use of `apply_patch`;
- preserving unrelated dirty-worktree changes;
- prohibitions on destructive git operations without explicit authorization;
- when planning is and is not useful;
- review-task behavior;
- response/output conventions.

This confirms that some Codex quality is prompt policy rather than hard-coded runtime behavior. But the runtime independently enforces many other concerns such as sandboxing, tool routing, context snapshots, cancellation, persistence and compaction.

**Cerebro implication:** maintain composable operating-manual modules per model/task instead of assuming all desired behavior can be enforced in code or all of it belongs in one universal prompt.

Upstream:
- `codex-rs/core/gpt_5_codex_prompt.md`
- `codex-rs/models-manager/src/model_info.rs`

## 3. Context fragments are typed

`codex-rs/core/src/context/mod.rs` exposes many distinct model-visible context fragment types rather than one undifferentiated string. Current categories include concepts for:

- developer instructions;
- user/project instructions;
- environment context;
- permissions;
- model-switch instructions;
- personality;
- realtime mode;
- plugins/apps;
- multi-agent role/mode/usage hints;
- current-time reminders;
- token/rollout-budget context;
- inter-agent messages/completion;
- compaction summaries;
- hook-supplied additional context;
- user shell commands and other runtime notices.

Each fragment can carry a model-facing role/content kind. For example, `DeveloperInstructions` is a developer-role context fragment; compaction summaries are represented as a typed user-role fragment.

**Cerebro implication:** preserve semantic types/roles until the provider serialization boundary. Avoid flattening all harness state into a preformatted text transcript like the current CLI adapter does.

Upstream:
- `codex-rs/core/src/context/mod.rs`
- `codex-rs/core/src/context/developer_instructions.rs`
- `codex-rs/core/src/context/compaction_summary.rs`

## 4. World State is persisted comparison state, not repeatedly duplicated prose

Codex's World State system is one of the strongest context-engineering ideas found so far.

`WorldState` is composed of stable typed sections. Each section owns:

- a stable persisted ID;
- a compact snapshot containing only data needed to compare state;
- rules for deciding whether a model-visible update is required;
- rendering of a full initial fragment or a diff against previous state;
- compatibility hooks for older retained history when exact snapshots are unavailable.

World-state snapshots are persisted and can be advanced with merge-patch semantics. The runtime can render:

- full state when no previous state exists;
- exact diffs against a persisted previous snapshot;
- history-aware diffs when only retained model history is available.

The system also fingerprints rendered fragments, helping distinguish state identity from arbitrary conversation text.

**Why this matters:** a long-running coding agent should not repeatedly resend a giant description of cwd, permissions, project instructions, model mode, etc. But when those facts change, the model must be explicitly told that the old state is no longer valid. Codex treats this as a state synchronization problem.

Upstream:
- `codex-rs/core/src/context/world_state/mod.rs`

## 5. World State currently covers a wide set of harness facts

`Session::build_world_state_for_step` assembles sections in a deliberate sequence including:

- model instruction/state changes;
- personality;
- token-budget/context-window guidance;
- realtime mode;
- AGENTS.md instructions;
- permissions/approval/exec policy;
- collaboration mode;
- persistent mode;
- current environment/date/cwd-related context;
- environment usage instructions;
- apps/plugins usage state;
- deferred tool namespaces;
- extension-contributed sections;
- multi-agent mode/usage hints;
- managed developer instructions.

Not every section is always enabled. Feature flags, provider/model metadata, session source and current runtime configuration determine what is added.

**Cerebro implication:** Cerebro Harness v1 should probably have its own canonical `WorldState`/`ExecutionContext` abstraction with stable sections and state-diff semantics. This is more promising than rebuilding a giant context string on every model call.

Upstream:
- `codex-rs/core/src/session/world_state.rs`

## 6. AGENTS.md discovery is hierarchical, provenance-aware and bounded

`codex-rs/core/src/agents_md.rs` documents the discovery algorithm directly.

Confirmed behavior:

1. determine project root by walking upward from cwd until configured project-root markers are found (default includes `.git`);
2. do not traverse above that project root;
3. inspect each directory from project root down to cwd;
4. in each directory, prefer `AGENTS.override.md`, then `AGENTS.md`, then configured fallback filenames;
5. concatenate discovered instructions in root-to-cwd order;
6. enforce a configured total byte budget and truncate when required;
7. track project/environment/file provenance for discovered instruction entries;
8. combine project instructions with host-provided user instructions;
9. for multiple project environments, label the instruction groups by environment;
10. skip project-file instruction loading when the active project is untrusted.

`AgentsMdManager` caches the effective result and invalidates/reloads it when the environment selections or active-project trust state change.

Upstream:
- `codex-rs/core/src/agents_md.rs`
- `codex-rs/core/src/agents_md_manager.rs`

## 7. AGENTS.md changes are explicit World State transitions

`AgentsMdState` stores the effective model-visible instructions as a World State section.

If the effective AGENTS.md content is unchanged, no new fragment is emitted. If it changes, Codex renders an explicit replacement message plus the new instructions. If instructions disappear, it explicitly tells the model that the previously provided AGENTS.md instructions no longer apply.

This avoids two bad failure modes:

- wasting context by re-injecting unchanged repository instructions every step;
- silently changing/removing instructions while the model continues to act as if the old ones remain authoritative.

**Cerebro implication:** repository instructions, tool permissions and similar mutable operating state should be synchronized with explicit add/replace/remove semantics, not merely appended forever.

Upstream:
- `codex-rs/core/src/context/world_state/agents_md.rs`

## 8. StepContext freezes the state used for one sampling request

`StepContext` is explicitly documented as request-scoped state that may change between model sampling requests.

At this snapshot it contains:

- the enclosing `TurnContext`;
- one immutable resolved settings version;
- request-specific token-budget configuration;
- request/model-tagged telemetry;
- an environment snapshot;
- selected capability roots;
- executor capability-discovery state;
- the exact MCP binding/catalog for the request;
- the finalized ToolRouter advertised/executed for the request;
- the canonical AGENTS.md value observed with that environment snapshot.

That means AGENTS instructions, environment, MCP and tools are captured together rather than independently racing against one another.

**Cerebro implication:** `ContextBuilder` should eventually return something richer than `list[Message]`: a frozen request packet/snapshot that includes the exact state against which tools and provider behavior will execute.

Upstream:
- `codex-rs/core/src/session/step_context.rs`

## 9. Compaction is a history/state transition, not just summarization

The default local compaction prompt asks the model to produce a concise handoff containing progress, decisions, constraints/preferences, remaining work and critical continuation data.

But the surrounding code is more important than the prompt text.

### Local compaction behavior confirmed so far

- Compaction is itself a model request over current history plus the compaction instruction.
- It uses base instructions but does not advertise the normal turn tool set in the simple local-compaction request.
- It has its own stream retry behavior.
- If compaction itself exceeds context, Codex removes old history items and retries, preserving recent items.
- After the summary is generated, Codex constructs replacement history rather than merely appending the summary forever.
- It retains the most recent genuine user messages up to a separate token budget (currently 20,000 tokens in this implementation), truncating the oldest selected message if necessary.
- It appends the compaction summary as a typed user-context fragment.
- It advances an explicit auto-compaction window identity and recomputes token usage.

### Initial context treatment depends on when compaction occurs

Pre-turn/manual compaction can omit the initial context from the replacement history and clear the reference-context baseline so the next real turn performs a fresh full reinjection.

Mid-turn compaction needs different semantics: Codex re-injects canonical current context into the replacement history before the last genuine user message/summary so the ongoing model-tool continuation has the correct operating state immediately after compaction.

**Cerebro implication:** compaction must define how durable task state, mutable World State, retained user intent and ongoing tool-loop continuity survive the rewrite. A generic `summarize(messages)` helper is insufficient.

Upstream:
- `codex-rs/prompts/templates/compact/prompt.md`
- `codex-rs/core/src/compact.rs`
- `codex-rs/core/src/context/compaction_summary.rs`

## 10. Model switches can force context reconciliation

The turn loop stores previous-turn model information, including a model compaction-compatibility hash. Before a new turn it can compact when:

- the previous and current models advertise incompatible compaction hashes;
- a switch moves to a smaller context window and the current history would violate the new model's usable limit.

Codex can select local or provider-supported remote compaction based on provider capabilities.

**Cerebro implication:** switching a channel agent from DeepSeek to Claude/GPT/Gemini cannot safely be treated as changing one model-name field. Model changes may require a context migration/reconciliation step.

Upstream:
- `codex-rs/core/src/session/turn.rs`
- `codex-rs/protocol/src/openai_models.rs`

## 11. Strong candidate design for Cerebro

A Cerebro-native request packet should eventually look conceptually like:

```text
HarnessRequestSnapshot
  agent identity/persona
  model capability profile
  base operating instructions
  current typed World State
    repository instructions
    workspace/environment
    permissions
    collaboration mode
    memory/task state
    tool availability
  canonical recent/compacted conversation history
  turn-specific context
  exact tool catalog + permissions
  provider request settings
  provenance/version IDs for all mutable pieces
```

The provider adapter's job should be to serialize this canonical snapshot into OpenAI/Anthropic/Gemini/DeepSeek/LM-Studio wire formats, not to invent context policy independently.

## Open questions still being mined

- exact capture/build order for `StepContext` and its model/tool/MCP snapshots;
- how user-level host instructions are sourced before AGENTS.md composition;
- exact ordering of initial World State fragments relative to user input/history;
- how `reference_context_item` and World State snapshots survive resume/fork/reconstruction;
- remote/provider-side compaction semantics;
- prompt caching strategy and which parts are intentionally stable prefixes;
- model-specific instruction catalogs received remotely versus fallback prompts shipped in the repo;
- how subagent role instructions and parent context are assembled.

## Provenance ledger additions

| Finding | Upstream source | Classification | Candidate Cerebro use |
| --- | --- | --- | --- |
| Model-specific base instruction resolution | `core/src/session/mod.rs`, `models-manager/src/model_info.rs` | conceptual inspiration only | Model/harness profiles |
| Typed context fragments | `core/src/context/*` | conceptual inspiration only | Canonical provider-independent context objects |
| Persisted/diffed World State | `core/src/context/world_state/*`, `core/src/session/world_state.rs` | conceptual inspiration only | Strong Harness v1 candidate |
| Hierarchical bounded AGENTS.md loading | `core/src/agents_md.rs`, `agents_md_manager.rs` | conceptual inspiration only | Repository instruction resolver |
| AGENTS.md replacement/removal semantics | `core/src/context/world_state/agents_md.rs` | conceptual inspiration only | Mutable context synchronization |
| Request-scoped StepContext | `core/src/session/step_context.rs` | conceptual inspiration only | Frozen inference/execution snapshot |
| Compaction as history/state rewrite | `core/src/compact.rs` | conceptual inspiration only | Compaction/checkpoint subsystem |
| Per-model compaction compatibility metadata | `protocol/src/openai_models.rs`, `core/src/session/turn.rs` | conceptual inspiration only | Model switching/context migration |

No Codex implementation source has been copied or adapted into Cerebro.
