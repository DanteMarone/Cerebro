# Codex Harness Architecture Map

**Status:** Initial confirmed trace; deeper context/tool/provider internals still being mined.

**Pinned upstream:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

This document maps the normal interactive Codex path from a rich-client `turn/start` request into the core agent loop. It deliberately separates protocol/UI plumbing from harness behavior.

No Codex implementation code is copied into Cerebro by this document. All findings are currently classified as **conceptual inspiration only**.

## Executive shape

```text
Rich client / TUI / app-server client
        |
        | turn/start (or equivalent submission)
        v
app-server request processor
        |
        | validate input + resolve per-turn overrides
        v
CodexThread
        |
        | TurnInputRequest
        v
SessionIo / Session submission loop
        |
        | create/capture TurnContext + StepContext
        v
run_turn
        |
        +--> pre-sampling compaction
        +--> hooks / user input persistence
        +--> world-state/context updates
        +--> skills/plugins/MCP requirements
        |
        v
clone model-visible history
        |
        v
build_prompt
        |
        | base instructions
        | request-scoped model-visible tool specs
        | output schema / model settings
        v
ModelClientSession.stream(...)
        |
        v
stream response events
        |
        +--> assistant/reasoning output > record/emit
        |
        +--> tool call > ToolCallRuntime > ToolRouter > execute
        |                    |
        |                    +--> result/failure/abort becomes model-visible history
        |
        +--> token/context state > compact if continuation would overflow
        |
        +--> retry transient sampling failures
        |
        v
needs follow-up?
   yes /       \ no
      /         \
rebuild next    stop hooks
sampling input     |
from history        v
      \          final assistant output
       \            |
        +-----------+
              |
              v
       durable history/events
       turn completion
```

## 1. UI/protocol boundary

### App server is not the agent runtime

`codex-rs/core/README.md` explicitly says `codex-core` implements Codex's business logic and is designed for use by multiple Codex UIs.

`codex-rs/app-server/README.md` describes app-server as a bidirectional interface for rich clients such as the VS Code extension. It defines three top-level interaction primitives:

- **Thread**: a conversation containing turns.
- **Turn**: one user-to-agent work cycle containing items.
- **Item**: persisted interaction/output units such as messages, reasoning, commands and file edits.

**Cerebro implication:** continue separating the headless harness/runtime from the Slack-shaped client UI. The UI should observe/control runtime state, not own the agent loop.

Upstream:
- `codex-rs/core/README.md`
- `codex-rs/app-server/README.md`

## 2. `turn/start` is validated and translated before Core owns it

`TurnRequestProcessor::turn_start` in `codex-rs/app-server/src/request_processors/turn_processor.rs` validates client input and delegates to `turn_start_inner`.

Confirmed responsibilities in `turn_start_inner` include:

- load the target `CodexThread`;
- verify direct input is allowed;
- enforce input/tool-output constraints and maximum text size;
- set app-server client metadata;
- resolve cwd, workspace roots and environment selections;
- map additional context;
- translate public input into Core `TurnInput`;
- construct validated per-turn/thread overrides for model, reasoning effort/summary, permissions/sandbox, approvals, collaboration mode and personality;
- call `CodexThread::start_or_steer_turn(...)` with a structured `TurnInputRequest`;
- return an in-progress public `Turn` after Core accepts or steers the work.

This layer does not itself sample the model or execute tools.

Upstream:
- `codex-rs/app-server/src/request_processors/turn_processor.rs`

## 3. `CodexThread` is a façade over a live `Session`

`CodexThread` in `codex-rs/core/src/codex_thread.rs` owns an `Arc<Session>` plus `SessionIo` endpoints.

`start_or_steer_turn` delegates to `submit_turn_input_with_mode(..., StartOrSteer)`. Before a new turn is started, Core can enforce execution-capacity constraints through `agent_control`. The actual turn input goes through `SessionIo` into the running session lifecycle.

The thread config snapshot is broad harness state rather than chat-only state. At this snapshot it includes model/provider, service tier, approval policy, permission profile, environment/workspace roots, ephemeral mode, reasoning settings, personality, collaboration mode, history/source/fork/parent metadata and originator.

Core also exposes explicit turn recovery/suspension operations. Recovery can preserve the original interrupted turn ID instead of pretending a recovered run is an unrelated new turn.

**Cerebro implication:** distinguish durable conversation identity from an individual inference or task attempt. Recovery should resume durable task/turn state where possible rather than creating misleading new chat events.

Upstream:
- `codex-rs/core/src/codex_thread.rs`

## 4. Session initialization resolves model-specific base instructions

`Session::spawn_internal` in `codex-rs/core/src/session/mod.rs` resolves base instructions with this priority:

1. explicit `config.base_instructions` override;
2. base instructions persisted in resumed conversation/session history;
3. the active model's rendered instruction template, including personality.

Developer instructions are retained separately in session configuration. The model provider is also constructed during session initialization.

This matters because the harness does not have one universal Codex prompt hardwired into the turn loop. Instruction selection is part of session/model resolution.

**Cerebro implication:** model-specific instruction profiles should be first-class data, not conditional text concatenation scattered through provider adapters.

Upstream:
- `codex-rs/core/src/session/mod.rs`

## 5. The core agent loop is `run_turn`

`codex-rs/core/src/session/turn.rs` describes and implements the central loop. The source comment states the core behavior plainly: each sampling request can yield tool calls and/or an assistant message; tool calls are executed and their results are supplied to the next sampling request; a response requiring no follow-up completes the turn.

The surrounding machinery is where most harness sophistication lives.

### Before the first sample

Confirmed order includes:

1. drain asynchronous hook results from prior work;
2. create or reuse a turn-scoped `ModelClientSession`;
3. run pre-sampling compaction when required;
4. inspect the new user input for required MCP/plugin/skill dependencies;
5. capture the first request-scoped `StepContext`;
6. record context/world-state changes and establish the reference context item;
7. build and inject skill/plugin/extension context;
8. run session-start/input hooks and persist accepted user input;
9. record previous-turn model/compaction settings;
10. enter the sampling/follow-up loop.

Upstream:
- `codex-rs/core/src/session/turn.rs`

## 6. `StepContext` is a request-scoped snapshot

Inside the sampling loop, Codex contains an unusually important comment:

> Capture once so context, advertised tools, and tool calls share one request view.

The same captured step context is then used while constructing model-visible state and servicing tool calls that originate from that request.

This prevents a race where a model is shown one tool/policy/context configuration but its later tool execution uses a newer configuration.

`ToolCallRuntime` explicitly retains the exact `Arc<StepContext>` whose tool list advertised the call because tool calls can finish later.

**Cerebro implication:** create an immutable/request-scoped execution snapshot containing at least model capabilities, tool catalog, tool permissions, workspace/environment and context-policy state. Tool execution must be authorized against the snapshot that advertised the tool, not whatever configuration happens to exist when the call finishes.

Upstream:
- `codex-rs/core/src/session/turn.rs`
- `codex-rs/core/src/tools/parallel.rs`

## 7. Model-visible history is reconstructed from durable history

Immediately before sampling, `run_turn` clones conversation history and projects it for the active model's input modalities. On retries/follow-ups, `run_sampling_request` can reconstruct the prompt input from history again rather than treating one serialized request body as the permanent source of truth.

Pending user input can also be drained into history between model samples according to turn state.

**Cerebro implication:** Cerebro's canonical event/history store should remain authoritative. Provider conversation IDs or one provider-specific request payload should be optimization state, not the canonical conversation.

Upstream:
- `codex-rs/core/src/session/turn.rs`

## 8. Prompt construction is structurally small

At this layer, `build_prompt(...)` combines:

- model-visible history/input;
- request-scoped `ToolRouter.model_visible_specs()`;
- parallel-tool-call capability enabled for the request;
- resolved base instructions;
- optional output schema and strictness;
- additional program metadata.

The complexity therefore lives upstream of `build_prompt`: instruction resolution, history/context maintenance, StepContext capture and tool-router construction.

**Cerebro implication:** do not build a giant monolithic "prompt builder" that owns every harness concern. Keep durable/context/tool state typed until the final provider-facing request assembly.

Upstream:
- `codex-rs/core/src/session/turn.rs`

## 9. One model-client session is reused across a turn and sampling retries

`run_sampling_request` uses a turn-scoped `ModelClientSession`. Provider-specific maximum stream retries are read from provider info. Retryable stream errors are retried through dedicated response-retry machinery; non-retryable errors return immediately.

Special cases include context-window exhaustion and usage-limit/rate-limit state updates.

The same turn-scoped client session is intentionally reused across retries so provider transport/sticky routing state can survive transient sampling failures.

**Cerebro implication:** provider adapters should expose provider-specific retry/capability policy, while the harness owns retry semantics. A transient network/stream failure should not necessarily become a new logical agent turn.

Upstream:
- `codex-rs/core/src/session/turn.rs`

## 10. Stream parsing drives durable events and tool work

`try_run_sampling_request` calls `ModelClientSession.stream(...)` and consumes structured response events.

Confirmed behavior includes:

- stream cancellation maps to a turn-aborted error;
- premature stream close before a completion event is treated as an error;
- model/reasoning/text/tool-argument events can stream to runtime clients;
- token usage, rate limits, server-model information and model verification metadata update session/runtime state;
- response completion records token usage and can request another follow-up sample when the provider says the turn has not ended;
- in-flight tool futures are drained before the sampling result is returned.

Upstream:
- `codex-rs/core/src/session/turn.rs`

## 11. Tool requests are persisted before execution

`handle_output_item_done` in `codex-rs/core/src/stream_events_utils.rs` asks `ToolRouter` to interpret completed model output as a tool call.

For a valid tool call, Codex:

1. records the model's tool-call item in conversation history immediately;
2. starts tool execution through the request-scoped `ToolCallRuntime`;
3. marks the model response as requiring follow-up.

That immediate persistence keeps history/rollout consistent even if the overall turn is later cancelled.

If a tool request can be corrected by the model, the error becomes a synthetic model-visible tool output and the turn continues. Fatal tool errors terminate the path.

**Cerebro implication:** model-visible failed tool execution is often recovery data, not an exception that should tear down the agent loop.

Upstream:
- `codex-rs/core/src/stream_events_utils.rs`

## 12. Parallelism is decided per tool, not globally

`ToolCallRuntime` asks the router whether each call supports parallel execution.

A shared read/write gate allows parallel-safe calls to coexist while a non-parallel call takes exclusive execution. This means the request may advertise parallel tool calling while individual tools still impose serialization where required.

**Cerebro implication:** tool metadata should declare concurrency semantics. "Provider supports parallel tool calls" is not enough to determine whether two actual operations may safely execute together.

Upstream:
- `codex-rs/core/src/tools/parallel.rs`

## 13. Cancellation and ordinary tool failures are turned into model-visible results

When a nonfatal tool handler fails, `ToolCallRuntime` converts the error into a failure output associated with the original call. When a running call is cancelled before reaching a terminal outcome, Codex aborts the underlying task, emits a tool-aborted lifecycle event, and constructs an aborted-tool result for the conversation/model.

This keeps the causal chain intact:

`model requested tool > harness attempted tool > tool failed/was aborted > model sees outcome`

rather than silently losing the call.

**Cerebro implication:** every accepted tool call should end in a terminal success/failure/aborted result with the same call identity, even when the human cancels the turn.

Upstream:
- `codex-rs/core/src/tools/parallel.rs`

## 14. Follow-up sampling is explicit

A sampling response sets `needs_follow_up` when, among other things:

- a tool call must be executed and returned to the model;
- the provider indicates the response did not end the turn;
- pending input needs another model pass.

After tool futures finish and their results are persisted, the outer `run_turn` loop rebuilds the next model-visible history and samples again.

When no follow-up remains, stop hooks run. A stop hook may:

- allow completion;
- stop the turn;
- block completion and inject continuation fragments, forcing another model sample.

So "the model emitted a final-looking answer" is not by itself the only completion criterion.

Upstream:
- `codex-rs/core/src/session/turn.rs`

## 15. Compaction is part of the control loop, including model switches

Compaction is not merely a manual summarize command.

Confirmed triggers/paths include:

- pre-turn context limit;
- changed model compaction-compatibility hash;
- downshifting to a model with a smaller context window;
- mid-turn continuation when context limits/new-context requests require rollover.

The harness chooses local vs provider-supported remote compaction based on provider capabilities and feature state.

**Cerebro implication:** compaction policy belongs in the harness plus model/provider capability profile. It should preserve logical turn continuity and understand model changes.

Upstream:
- `codex-rs/core/src/session/turn.rs`

## 16. The currently confirmed control loop

```text
client input
  > app-server validates/translates
  > CodexThread accepts start/steer
  > Session admits turn
  > run_turn
      > compact if needed
      > capture StepContext
      > update context/world state
      > inject user/skill/plugin context
      > clone model-visible history
      > build Prompt from history + base instructions + StepContext tool specs
      > ModelClientSession.stream
          > record assistant/reasoning output
          > detect tool calls
          > execute tools against same StepContext
          > record tool terminal outcomes
          > track usage/rate limits/events
      > if continuation needed:
          > compact if needed
          > rebuild model-visible history
          > sample again
      > otherwise run stop hooks
      > complete turn
```

## Still unresolved in this map

These are intentionally not guessed yet:

- exact `SessionIo` submission-loop route from `TurnInputRequest` to the task that invokes `run_turn`;
- exact `StepContext` construction and which state is frozen into it;
- complete instruction/context ordering, including developer/user/project/managed instructions;
- AGENTS.md discovery/scoping and how changes become world-state/context items;
- exact ToolRouter registry/spec construction and individual built-in tool semantics;
- model-provider abstraction and how OpenAI-specific Responses API items are normalized;
- exact compaction prompt and preserved state;
- persistence/rollout reconstruction details;
- subagent/multi-agent execution and context inheritance;
- completion verification beyond stop hooks (tests/diffs may largely be model instruction behavior rather than a generic hard-coded verifier).

Those questions are the next mining targets.

## Provenance ledger additions

| Finding | Upstream source | Classification | Cerebro decision status |
| --- | --- | --- | --- |
| Protocol/UI separated from Core runtime | `core/README.md`, `app-server/README.md` | conceptual inspiration only | Strong fit with existing architecture |
| Thread/turn/item separation | `app-server/README.md` | conceptual inspiration only | Compare with Cerebro channel/message/tool-call model |
| Request-scoped StepContext | `core/src/session/turn.rs`, `core/src/tools/parallel.rs` | conceptual inspiration only | Strong candidate for Harness v1 |
| Tool failures/aborts become model-visible outputs | `core/src/stream_events_utils.rs`, `core/src/tools/parallel.rs` | conceptual inspiration only | Strong candidate for Harness v1 |
| Per-tool parallelism gate | `core/src/tools/parallel.rs` | conceptual inspiration only | Strong candidate for tool metadata |
| Provider-aware sampling retries | `core/src/session/turn.rs` | conceptual inspiration only | Candidate provider capability/policy layer |
| Provider/model-aware compaction | `core/src/session/turn.rs` | conceptual inspiration only | Strong candidate for model capability profiles |
| Base-instruction selection is session/model-specific | `core/src/session/mod.rs` | conceptual inspiration only | Strong candidate for composable model instruction profiles |

No Codex implementation source has been copied or adapted into Cerebro.
