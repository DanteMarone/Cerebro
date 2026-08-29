# Goose sessions, recovery and delegation

Upstream: `aaif-goose/goose`

Pinned commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification: **conceptual inspiration only**.

## Session persistence

Confirmed source:

- `crates/goose/src/session/session_manager.rs`
- `crates/goose/src/session/*`

Goose persists sessions in SQLite (`sessions.db`). The pinned schema version is 16.

A persisted session can carry:

- id and working directory;
- generated/user-set name;
- session type;
- created/updated timestamps;
- extension state;
- current/accumulated usage and cost;
- schedule and recipe state;
- persisted conversation;
- provider name and model configuration;
- Goose mode;
- project/archive metadata;
- parent session id;
- summary/snippet metadata.

Session types at the pinned commit are:

- `User`
- `Scheduled`
- `SubAgent`
- `Hidden`
- `Terminal`
- `Gateway`
- `Acp`

This is more than chat-history persistence. Session state is also the durable execution envelope used by the newer control loop.

## Re-entrant persisted state machine

Confirmed source:

- `crates/goose-agent/src/machine.rs`
- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/session.rs`

In the experimental state-machine path, the machine does not assume it owns a continuously live mutable session object. Instead:

1. load session state;
2. choose the first applicable operation/inference step;
3. produce explicit effects;
4. apply/persist effects through the product `SessionManager`;
5. reload session state;
6. continue or yield.

Conversation effects include appending messages, replacing the conversation, patching tool-request metadata and changing user/model visibility. Goose-specific effects additionally update product session fields such as recipe/extension/usage state.

Operations can store notes in persisted message metadata so reconstruction of the operation pipeline can recognize that a prior action was already performed.

This architecture makes approval, retry and compaction state reconstructable from durable data instead of relying only on an in-memory coroutine stack.

Important qualification: at the pinned commit this state-machine path is still explicitly experimental behind `GOOSE_STATE_MACHINE`; the legacy reply loop remains the normal fallback/default path.

## Local session resume versus provider session resume

Confirmed source:

- `crates/goose/src/agents/mod.rs`
- `crates/goose/src/agents/agent.rs`
- `crates/goose-provider-types/src/base.rs`
- `crates/goose/src/acp/provider.rs`

Goose separates local-session continuity from optional backend-session continuity.

Inference metadata on messages can record the provider and provider-owned session id. When resuming with the same provider, `latest_provider_session_id()` finds the newest matching external session id and the agent calls `provider.resume()`.

If provider resume fails, Goose logs the failure and continues with a handoff rather than abandoning the local session. This means the durable Goose transcript remains authoritative even when an external harness session has disappeared.

ACP providers implement true external-session resume: they load the saved ACP session, replace the provider wrapper's current backing session and then close the old one. Failed loads restore the previous active ACP session state.

## Provider failures are typed

Confirmed source: `crates/goose-provider-types/src/errors.rs`.

`ProviderError` distinguishes:

- not configured;
- authentication;
- context length exceeded;
- rate limit with optional retry delay;
- server error;
- network error;
- generic request failure;
- invalid input value;
- execution error;
- usage-data error;
- unsupported operation;
- endpoint not found;
- credits exhausted with optional top-up URL;
- provider refusal with optional category.

These categories also have stable telemetry labels.

HTTP/request conversion sanitizes credentials, query strings and fragments from URLs before placing them into user/runtime error text, preventing secret-bearing request URLs from being copied verbatim into normal provider errors.

## Tool and provider failure versus task retry

Goose has two different recovery layers.

### Operational/model failures

Provider errors and MCP/tool execution failures are represented as typed runtime or tool-result errors. Recoverable tool errors are inserted into the conversation so the model can react on the next inference step.

### Task-level recipe retries

Confirmed source:

- `crates/goose/src/agents/retry.rs`
- `crates/goose/src/agents/state_machine/ops_retry.rs`

Recipes can define success checks, maximum retries and an optional `on_failure` shell command. Current success checks in the examined code are shell commands with mandatory timeouts.

The legacy `RetryManager` resets the conversation to the initial messages and tracks its retry counter in memory.

The newer state-machine retry operation improves reconstructability: it stores the attempt count as metadata on the kickoff message because that message survives a conversation reset. A failed success check can execute `on_failure`, replace the conversation with the kickoff state and re-enter the machine. Exhausted attempts append a durable assistant error instead of looping forever.

This is an important distinction: recipe retry is verification of task success after an apparently finished agent turn, not automatic retry of every provider/network error.

## Completion is policy-driven

Confirmed source:

- `crates/goose-agent/src/operation.rs`
- `crates/goose/src/agents/state_machine/ops_retry.rs`
- `crates/goose/src/agents/state_machine/ops_maxturns.rs`
- `crates/goose/src/agents/state_machine/ops_exit_on_error.rs`

A normal assistant message only qualifies as an end-of-turn candidate when it has no trailing error, tool request or action-required content. Additional operations can still prevent completion:

- a configured goal can inject a hidden model-visible nudge to verify the goal before finishing;
- grind mode can keep nudging the model to continue;
- recipe success checks can reset/retry;
- max-turn enforcement can stop autonomy and ask the user whether to continue;
- a trailing error causes an immediate yield.

The max-turn operation also contributes a model-oriented turn-budget hint after at least half of the budget has been consumed.

Therefore provider finish reasons are inputs to the harness, not the harness's final definition of completion.

## Cancellation and yielding

Confirmed source:

- `crates/goose-agent/src/machine.rs`
- `crates/goose-agent/src/operation.rs`
- tool/MCP/shell execution paths.

Cancellation is carried by a shared `CancellationToken`. Operations and inference can observe it, and the generic machine forces a client yield if cancellation is present after an applied transition.

The state machine distinguishes **yield** from **finish**. Yield means control returns to the client/UI for user action or cancellation even though the durable session remains resumable. Approval requests, maximum-turn boundaries and errors all use this distinction.

## Delegation is implemented as child sessions

Confirmed source:

- `crates/goose/src/agents/subagent_task_config.rs`
- `crates/goose/src/agents/subagent_handler.rs`
- `crates/goose/src/agents/platform_extensions/summon.rs`

A delegated task creates a fresh persisted Goose session of type `SubAgent`, normally in `GooseMode::Auto`. It is not merely an inline prompt sent through the parent's provider call.

`TaskConfig` carries the selected:

- provider;
- model config;
- parent session id;
- effective parent/child working directory;
- extension set;
- max turns.

The default subagent turn budget is 25, configurable with `GOOSE_SUBAGENT_MAX_TURNS`.

The subagent constructs a fresh `Agent`, configures its provider/model, adds selected extensions, applies recipe/structured-output components, renders a dedicated `subagent_system.md` prompt and then runs the normal agent reply machinery against its own session.

The result can be the structured final-output value when a response schema is present or extracted response text otherwise.

## Delegation depth is deliberately bounded

Confirmed source: `crates/goose/src/agents/platform_extensions/summon.rs`.

The summon extension checks the current session type. If the current session is already `SubAgent`, a request to delegate again fails with `Delegated tasks cannot spawn further delegations`. The model-facing summon tool set for a subagent omits the delegate tool while retaining load behavior.

So the examined delegation path has an explicit one-level depth boundary rather than allowing uncontrolled recursive agent trees.

## Synchronous and background delegation

Confirmed source: `crates/goose/src/agents/platform_extensions/summon.rs`.

Delegate parameters can specify instructions/source, parameters, extensions, provider, model, temperature, max turns, reference context, working directory and an `async` flag.

Synchronous delegation waits for the subagent result as part of the current tool call.

Asynchronous delegation creates a tracked background task with:

- task id/description;
- start time;
- turn/activity counters;
- join handle;
- cancellation token;
- notification buffering/routing.

Completed background tasks retain their result/error, turns and duration for later retrieval.

Subagent tool activity can be surfaced to the parent/client as MCP logging notifications tagged with the subagent id and proposed tool call.

## Discoverable named agents and recipes

Confirmed source: `crates/goose/src/agents/platform_extensions/summon.rs`.

Summon discovers reusable agent/recipe definitions from both project-local and user/global paths. Observed directories include:

- `.goose/recipes`
- `.agents/recipes`
- `.goose/agents`
- `.claude/agents`
- `.agents/agents`
- corresponding home/config directories
- paths from `GOOSE_RECIPE_PATH`.

It also incorporates subrecipes referenced by an active recipe. Named agents are Markdown files with frontmatter; recipes use Goose's recipe formats.

This is delegation discovery, not dynamic recursive planning: the parent chooses a named source or constructs an ad hoc delegated task, which then runs in a bounded child session.

## Parent/child inheritance is selective

Confirmed source:

- `crates/goose/src/agents/subagent_task_config.rs`
- `crates/goose/src/agents/platform_extensions/summon.rs`
- `crates/goose-provider-types/src/model.rs`

The child receives an explicitly resolved provider/model/extension/working-directory configuration. Delegate parameters can override several of those choices. Model inheritance deliberately avoids blindly copying arbitrary provider-specific request parameters across model/provider changes.

This is safer than handing a child the parent's entire mutable runtime object: the child gets a concrete execution configuration and its own durable session.

## Cerebro implications

The strongest reusable session idea is that durable execution state should be independently resumable from provider process/session state. Cerebro should be able to reconstruct “what happened and what should happen next” even if a provider connection, UI process or external agent session disappears.

For delegation, Goose reinforces a useful model: a subagent should be a child run/session with explicit parentage, provider/model/tool scope, working directory and budget. That provides a natural place for Cerebro to attach collaborative UI state, audit trails, cancellation and permissions.

Goose's one-level delegation restriction is a product policy rather than a universal requirement, but the existence of an explicit depth boundary is worth retaining. Cerebro should make recursion/depth a first-class policy rather than letting nested delegation emerge accidentally.

No Goose implementation code should be copied or adapted during this phase.
