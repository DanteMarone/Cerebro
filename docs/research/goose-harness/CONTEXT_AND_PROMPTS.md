# Goose context and prompts

Upstream: `aaif-goose/goose`

Pinned commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification: **conceptual inspiration only**.

## System prompt construction

Confirmed source: `crates/goose/src/agents/prompt_manager.rs`.

Goose does not construct the system prompt as one static string. `PromptManager` builds it from structured context and extras.

`SystemPromptContext` includes:

- extension information;
- current date/time;
- Goose mode/autonomy state;
- whether subagents are enabled;
- code-execution mode;
- whether extension instructions should be included;
- optional MOIM system content.

The manager can use a full system-prompt override or render the normal `system.md` template. It also adds stable persistent extras and per-build prompt contributions.

Important implementation behavior:

- extension information is sorted by name before rendering, making equivalent prompts stable across sessions and helping provider prompt caching;
- Unicode tag characters are sanitized from extension instructions, overrides and extras;
- the manager's current timestamp is fixed at construction and rounded to the hour, explicitly trading minute-level freshness for more cache-stable system prompts;
- Chat mode injects an instruction that no tools/system access are available;
- project hints can be imported as prompt extras;
- prompt contributions passed during a build are not retained for the next build;
- tests verify sensitive `.git/config` content is not imported into the system prompt by project-hint handling.

## Prompt contributions from the operation pipeline

Confirmed source:

- `crates/goose-agent/src/operation.rs`
- `crates/goose-agent/src/machine.rs`
- `crates/goose/src/agents/state_machine/*`

The newer generic state machine lets operations contribute three different inputs before inference:

- tools;
- prompt parts;
- MOIM parts.

The inference step aggregates these contributions. This means context/prompt policy can be attached to the operation that owns the behavior, instead of every feature modifying a central prompt builder directly.

This is particularly relevant to turn-budget warnings, skills/project context, extension instructions and similar conditional context.

## Durable history versus active model context

Confirmed source:

- `crates/goose/src/context_mgmt/mod.rs`
- `crates/goose-context-management/src/*`
- `crates/goose/src/conversation/*`

Goose treats the persisted transcript and the model-visible context as different views of the same conversation.

During compaction:

- prior messages remain in the stored conversation;
- compacted messages are changed to user-visible but agent-invisible;
- the generated summary is inserted agent-visible but user-hidden;
- continuation instructions are agent-visible/user-hidden;
- selected current-turn material can also be preserved agent-only as needed.

This allows the user interface and audit/history layer to retain what actually happened while the model receives a compressed working context.

That separation is more useful architecturally than a simple “delete old messages” queue.

## When automatic compaction applies

Confirmed source: `crates/goose/src/context_mgmt/mod.rs`.

Automatic compaction is bypassed when the active provider returns `manages_own_context() == true`.

Otherwise Goose resolves a threshold from explicit override, `GOOSE_AUTO_COMPACT_THRESHOLD`, or the context-management default. Values at or outside the effective 0..1 interval disable automatic threshold behavior.

Context pressure is computed from:

- provider/model context limit;
- current token usage from session metadata where available;
- otherwise a token estimate over agent-visible messages.

Compaction occurs when current usage exceeds the configured fraction of the effective context limit.

## Context-limit resolution

Confirmed source:

- `crates/goose-provider-types/src/model.rs`
- `crates/goose-provider-types/src/context_limit.rs`
- provider model metadata under `crates/goose-providers/` / `crates/goose/src/providers/`.

`ModelConfig` carries an optional resolved context limit. If no stronger model/provider source supplies one, the shared fallback is 128,000 tokens.

Deserialization intentionally clears the stored context-limit field rather than trusting an old persisted value. This makes context limits runtime-resolved capability data rather than durable user state.

## Summarization/compaction implementation boundary

Confirmed source:

- `crates/goose-context-management/src/lib.rs`
- `crates/goose-context-management/src/summarize.rs`
- `crates/goose-context-management/src/structured.rs`
- `crates/goose-context-management/src/provider.rs`
- `crates/goose/src/context_mgmt/mod.rs`

Goose has extracted context-management algorithms into a separate crate. The product crate adapts its own provider/message/token/template types to that generic package.

The product-specific layer decides when compaction applies, which messages are eligible, what continuation wording to use, and how visibility is represented. The generic crate owns summarization/structured-context mechanics.

This is another sign of the Goose/GDK direction: reusable harness primitives are being split out of the product crate while product policy remains in `goose`.

## Tool-pair summarization

Confirmed source: `crates/goose/src/context_mgmt/mod.rs`.

Goose separately manages tool-call pressure instead of relying only on whole-conversation compaction.

`GOOSE_TOOL_PAIR_SUMMARIZATION` controls the feature and defaults enabled. Old tool request/response pairs can be summarized in batches while recent tool calls remain intact. The cutoff scales with effective context limit and is clamped to a bounded range (10..500 tool calls), preventing an unbounded amount of raw tool I/O from dominating the window.

The state-machine pipeline only enables this harness-owned tool-pair compaction when the provider does not manage its own context.

## Compaction continuation semantics

Confirmed source: `crates/goose/src/context_mgmt/mod.rs`.

Goose distinguishes several compaction contexts:

- normal automatic compaction;
- compaction while in a tool loop;
- manual `/compact`.

The continuation prompt differs because the model needs different guidance depending on whether it should resume autonomous tool work or simply continue the conversation after a user-requested compaction.

The compaction input also excludes stale turn-context events that should not be summarized into durable semantic context.

## Provider-owned context and handoff

Confirmed source:

- `crates/goose-provider-types/src/base.rs`
- `crates/goose/src/acp/provider.rs`
- `crates/goose/src/agents/agent.rs`

ACP-backed providers own their own context and session. Goose therefore does not replay the complete local conversation on every model call in the same way as a direct stateless API path.

At provider-session transitions Goose has explicit handoff behavior. ACP constructs a bounded handoff context memo for the first prompt of a fresh external session; if that initial prompt fails in a way plausibly related to the memo, the code contains a fallback path that can retry without the memo. Authentication and exhausted-credit errors do not consume this fallback because dropping context would not plausibly fix them.

This is a concrete example of why context ownership should be modeled explicitly.

## Visibility as a context primitive

Confirmed source:

- `crates/goose/src/conversation/message.rs`
- `crates/goose-agent/src/operation.rs`
- compaction and state-machine operations.

Messages have independent user-visible and agent-visible treatment. Goose uses this for more than compaction:

- hidden retry/goal nudges;
- hidden summaries/continuations;
- user-visible approval/action messages that should not necessarily be replayed as ordinary model context;
- slash-command/system-notification handling.

For Cerebro, “visibility to human UI” and “visibility to model context” should remain distinct attributes rather than being inferred from message role or event type.

## Prompt/context failure modes worth retaining

The source shows several defenses that are architectural rather than provider-specific:

- stable ordering for cacheability;
- sanitization of unusual Unicode control/tag characters in injected instructions;
- explicit exclusion of sensitive project metadata from hint imports;
- separation of transient prompt contributions from persistent extras;
- context compaction that preserves audit history;
- bounded tool-output/tool-pair retention;
- capability-based disabling of harness compaction when another runtime owns context.

## Cerebro implications

The most generalizable pattern is to model context as a **derived view of durable state**, not as the durable state itself. Cerebro can keep a complete shared event/message history while building provider-specific context views with visibility, summaries and transient policy contributions.

The second useful pattern is to make context ownership a capability negotiated at the backend boundary. For Cerebro's direct-provider path, Cerebro should normally own context. External harness adapters may own it, but that should be represented as a different execution contract rather than hidden as a small provider quirk.

No Goose implementation code should be copied or adapted during this phase.
