# Codex Recovery and Verification Semantics

**Status:** Initial confirmed map of model/request retries, context-limit recovery, cancellation/suspension, lifecycle hooks, and verification boundaries.

**Pinned upstream:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

No Codex implementation code is copied into Cerebro by this document. Findings are currently **conceptual inspiration only**.

## Main conclusion

Codex does not treat recovery as one generic retry loop, and it does not treat verification as one generic "run tests before done" mechanism.

Recovery is split across distinct layers:

- HTTP request retry policy;
- streaming/sampling retry policy;
- transport fallback;
- context-window compaction;
- task cancellation/abort lifecycle;
- explicit suspend/recover handoff for an unfinished turn;
- durable transcript flushing and lifecycle events.

Verification is similarly split:

- ordinary testing/building/formatting guidance is primarily **model/prompt behavior**;
- tool permissions, sandbox checks and edit verification are **runtime-enforced**;
- Stop hooks can **hard-gate completion** and feed continuation feedback back to the model;
- `/review` is a separate reviewer-agent workflow, not an automatic proof that every normal turn is correct.

For Cerebro, the important design lesson is to make failure classes and completion gates explicit. Do not hide all failures behind `retry()`, and do not confuse model instructions to verify work with harness-enforced acceptance criteria.

## 1. Retryability is typed

`CodexErr` carries semantic `CodexErrorDetails`, an optional server/provider retry delay, and an `is_retryable()` decision.

Examples classified retryable include stream disconnects, in-stream rate limits, request/operation timeouts, retryable unexpected HTTP status, response-stream failures, connection failures, internal server errors and several internal I/O/agent failures.

Examples classified non-retryable include cancellation/turn abort, context-window exhaustion, quota/usage failures, invalid requests, tool-name collisions, sandbox failures, unsupported operations and explicit policy failures.

This typed classification is important because downstream retry loops do not blindly replay every failure.

**Cerebro implication:** define canonical provider/runtime failure categories such as `transient_transport`, `rate_limited`, `context_exhausted`, `cancelled`, `policy_denied`, `invalid_request`, `tool_failure`, and `fatal_internal`, with retryability and user/model visibility determined centrally rather than by string matching.

Upstream:
- `codex-rs/protocol/src/error.rs`

## 2. HTTP request retries and sampling-stream retries are separate

The lower-level Codex client has an explicit `RetryPolicy` for ordinary HTTP requests. Policy independently selects retries for:

- HTTP 429;
- HTTP 5xx;
- timeout/connection/network transport errors.

Backoff is exponential with jitter and is recorded as retry telemetry.

The model sampling loop has a separate `ResponsesStreamRetryState`. A response stream that disconnects before `response.completed` is replayed as a sampling request when the error is retryable and the provider's stream retry budget allows it.

Tests explicitly cover an incomplete SSE response followed by a successful replay.

**Cerebro implication:** provider adapters should separate request establishment/retry policy from an in-progress streaming inference retry policy. They have different replay risks, telemetry and UX.

Upstream:
- `codex-rs/codex-client/src/retry.rs`
- `codex-rs/core/src/responses_retry.rs`
- `codex-rs/core/src/session/turn.rs`
- `codex-rs/core/tests/suite/stream_no_completed.rs`

## 3. Connection loss can use a different budget from ordinary stream failures

When the `UnboundedConnectionRetries` feature is enabled, sampling requests with `ConnectionFailed` can enter a special reconnect path that does not consume the normal finite stream retry counter.

At the pinned baseline this path is restricted to sampling, excludes internal sessions and Amazon Bedrock, emits a "waiting for network" stream error, begins at a 5-second delay, doubles up to 60 seconds, and keeps retry telemetry separate.

The test suite confirms a provider can be unreachable, later come back, then proceed into the ordinary stream retry path and complete the turn.

**Cerebro implication:** distinguish "provider rejected/failed this request" from "network is currently unavailable." A collaborative long-lived agent may reasonably pause for connectivity without burning its semantic retry budget, but that policy should be configurable and never literally unbounded without task/deadline/budget controls.

Upstream:
- `codex-rs/core/src/responses_retry.rs`
- `codex-rs/core/tests/suite/stream_no_completed.rs`

## 4. WebSocket failure can fall back to HTTP

A `ModelClientSession` can switch from Responses WebSocket transport to HTTP after the configured stream retry budget is exhausted. The retry state is reset after switching transports and the sampling request is replayed.

The test suite also covers an immediate fallback case for an upgrade-required WebSocket connection and confirms that fallback can remain sticky across later turns.

This is recovery within a provider/model session, not a model-level decision.

**Cerebro implication:** provider transport selection should be behind the provider adapter and may have ordered fallbacks. The harness should receive normalized streaming events regardless of whether the adapter is using WebSocket, SSE/HTTP, a local socket or another transport.

Upstream:
- `codex-rs/core/src/responses_retry.rs`
- `codex-rs/core/tests/suite/websocket_fallback.rs`

## 5. Context exhaustion is mostly avoided by compaction, not retried blindly

The turn loop proactively checks whether compaction is needed before sampling and can also compact mid-turn before continuing a tool/model loop. Context-limit compaction is recorded separately from model-switch/comp-hash compaction.

If the provider still reports `ContextWindowExceeded`, the sampling path marks token usage as full and returns the error. `ContextWindowExceeded` is explicitly non-retryable in `CodexErr::is_retryable()`.

This is a good separation of concerns:

```text
approaching context limit
  > compact/reconcile history
  > continue with a new request view

hard provider context-window failure
  > mark window full
  > surface non-retryable failure
```

**Cerebro implication:** context recovery should be a harness state transition with a fresh request snapshot, not "retry the exact oversized prompt N times." Hard overflow after compaction should become a typed terminal/recoverable-at-higher-level condition.

Upstream:
- `codex-rs/core/src/session/turn.rs`
- `codex-rs/protocol/src/error.rs`
- local/remote compaction modules mapped in `CONTEXT_AND_PROMPTS.md`

## 6. Turn cancellation is a task lifecycle, not just dropping a future

Every `SessionTask` receives a `CancellationToken`. The task contract explicitly says implementations should observe cancellation and terminate quickly, and may implement task-specific `abort(...)` cleanup.

Starting a replacement task first aborts currently active tasks with `TurnAbortReason::Replaced`.

The abort path gives the running task a short graceful-interruption window (`GRACEFULL_INTERRUPTION_TIMEOUT_MS`, currently 100 ms at the pinned baseline) and then aborts the Tokio task handle if it has not finished. Core also has interrupt hooks and optional model-visible interrupted-turn history markers so a later continuation can know that prior work was interrupted.

**Cerebro implication:** task cancellation needs a durable semantic state (`cancelled`, reason, last persisted point), cancellation propagation into provider/tool calls, bounded graceful cleanup, and eventual forced termination. Merely cancelling an HTTP request is insufficient.

Upstream:
- `codex-rs/core/src/tasks/mod.rs`
- `codex-rs/core/src/hook_runtime.rs`
- `codex-rs/protocol/src/error.rs`

## 7. Codex has an explicit unfinished-turn suspend/recover handoff

`CodexThread` exposes a recovery mechanism distinct from ordinary cancellation:

- `suspend_turn_and_shutdown()` stops an active unfinished **root** turn without writing normal `TurnAborted` or `TurnComplete` terminal lifecycle;
- successful suspension requires stopping execution, flushing history and closing the writer before ownership can transfer;
- recovery is refused/limited around active descendants and some queued/waiting state is explicitly best-effort;
- `recover_turn_if_idle()` starts no new user input and preserves the original interrupted turn ID.

This is effectively an ownership-transfer protocol for an unfinished durable turn.

**Cerebro implication:** this is highly relevant to agent residency, worker replacement and crash recovery. Cerebro should distinguish:

- cancel the task permanently;
- worker died unexpectedly;
- suspend/lease handoff while preserving task identity;
- resume/recover from the last durable checkpoint.

The durable state transition should belong to Cerebro, not to any provider SDK.

Upstream:
- `codex-rs/core/src/codex_thread.rs`
- `codex-rs/protocol/src/turn_input.rs`
- related abort/recovery tests

## 8. Transcript persistence is part of completion/recovery hygiene

After a task run finishes, the spawn wrapper attempts to flush the rollout before final task completion lifecycle is emitted. A flush failure produces a warning rather than silently pretending persistence succeeded.

The explicit suspension API is stricter: its contract requires history flush and writer shutdown before callers should transfer ownership.

**Cerebro implication:** define a durable checkpoint boundary. UI-visible completion, provider completion and persistence completion are different facts. Worker handoff must require persistence acknowledgement, while an ordinary transient persistence warning may use a retrying writer/outbox without losing the live session.

Upstream:
- `codex-rs/core/src/tasks/mod.rs`
- `codex-rs/core/src/codex_thread.rs`
- rollout/thread-store modules to be mapped further in the sessions/events artifact

## 9. Hooks are runtime policy gates with model-visible feedback

Codex's hook runtime includes session/user-prompt lifecycle hooks, `PreToolUse`, permission hooks, `PostToolUse`, interrupt hooks and Stop/SubagentStop hooks.

Confirmed control effects include:

- `PreToolUse` can rewrite tool input or block a call;
- permission hooks can return an approval decision;
- `PostToolUse` observes a successful tool result;
- Stop hooks can stop processing or **block completion**;
- a blocking Stop hook can return continuation feedback which is recorded into the conversation and causes the model loop to continue rather than ending the turn.

Stop hook aggregation gives `should_stop` precedence over `should_block`. Hook handlers are source-aware, and only handlers allowed to apply control effects can actually block/stop/rewrite.

**Cerebro implication:** treat lifecycle policy hooks as a typed extension interface around the harness, not arbitrary prompt text. A completion gate should return structured `{allow, block_with_feedback, stop}`-style outcomes and preserve provenance of which policy produced the decision.

Upstream:
- `codex-rs/core/src/hook_runtime.rs`
- `codex-rs/hooks/src/events/stop.rs`
- `codex-rs/core/src/session/turn.rs`

## 10. "Run tests before done" is mostly prompt behavior

The default Codex base instructions tell the model to consider tests/build/run/formatting when a codebase supports them, with guidance about narrow-to-broad validation and approval-mode behavior.

That is **not** equivalent to the runtime proving that tests ran or passed before every normal turn may complete. A normal turn can complete when the model produces no further tool calls unless another hard mechanism, such as a Stop hook or other policy layer, blocks completion.

Runtime-enforced verification does exist elsewhere for narrower concerns, for example filesystem-aware `apply_patch` verification, sandbox/permission enforcement and structured tool outcomes. Those are different from semantic task acceptance.

**Cerebro implication:** Cerebro Harness v1 should explicitly separate:

1. model instruction: "verify your work";
2. evidence collection: test/build/lint/tool results;
3. acceptance policy: what evidence is required for this task;
4. completion gate: whether the turn may be considered done.

Do not rely on a strong system prompt as the only acceptance controller for important coding tasks.

Upstream:
- `codex-rs/protocol/src/prompts/base_instructions/default.md`
- runtime tool verification sources mapped in `TOOLS_AND_EXECUTION.md`

## 11. `/review` is an explicit reviewer-agent workflow

`ReviewTask` starts a one-shot sub-Codex conversation with a dedicated review rubric, selects a review model (or the current model), disables selected capabilities such as web search/collaboration, uses `AskForApproval::Never`, consumes the reviewer events, parses structured review output when possible, and records the result back into the parent conversation.

If interrupted, review mode emits an interrupted result rather than treating a missing review as success.

This is valuable, but it is opt-in review orchestration rather than an automatic verifier attached to every normal completion.

**Cerebro implication:** keep reviewer/critic agents as an explicit orchestration primitive. Harness v1 can support task policies such as `review_required`, but the reviewer should produce evidence/findings into Cerebro state rather than being conflated with the worker's own inference loop.

Upstream:
- `codex-rs/core/src/tasks/review.rs`
- review prompt/format modules referenced there

## 12. Candidate Cerebro Harness v1 recovery model

A minimal model-agnostic design should probably preserve these boundaries:

```text
ProviderAdapter
  classify provider/transport errors
  bounded HTTP retry
  bounded stream retry
  optional transport fallback

TurnRuntime
  request-scoped context/tool snapshot
  context budget + compaction
  cancellation token
  durable lifecycle events

ToolRuntime
  timeout/cancel
  one terminal result
  runtime-enforced authorization/verification

CompletionPolicy
  inspect evidence/state
  allow completion
  or block with model-visible continuation feedback

TaskStore / WorkerLease
  durable checkpoints
  cancel vs suspend vs crash
  recover same task/turn identity
```

The key point is that retry, recovery, verification and acceptance are separate policies even when they interact.

## Open questions carried forward

- exact rollout/thread-store reconstruction rules after process restart;
- what history/event facts are sufficient to recover active vs completed turns;
- detailed interrupt hook ordering relative to task cancellation and tool cancellation;
- persistence writer retry guarantees after ordinary flush warnings;
- whether any additional completion gates exist outside hooks/Guardian/review modes;
- provider-specific retry normalization and which errors should remain adapter-local;
- multi-agent parent/child recovery behavior and descendant constraints.

These now feed directly into the next artifact: `SESSIONS_EVENTS_AND_MULTIAGENT.md`.

## Provenance ledger additions

| Finding | Upstream source | Classification | Candidate Cerebro use |
| --- | --- | --- | --- |
| Typed retryability/error categories | `protocol/src/error.rs` | conceptual inspiration only | Canonical harness error taxonomy |
| Separate HTTP and stream retry layers | `codex-client/src/retry.rs`, `core/src/responses_retry.rs` | conceptual inspiration only | Provider adapter contract |
| Connection-wait retry distinct from stream budget | `core/src/responses_retry.rs` | conceptual inspiration only | Optional offline/network recovery policy |
| WebSocket to HTTP transport fallback | retry code + `websocket_fallback.rs` tests | conceptual inspiration only | Provider transport fallback |
| Compaction before hard context failure | `core/src/session/turn.rs` | conceptual inspiration only | Strong Harness v1 candidate |
| Cancellation token + bounded graceful abort | `core/src/tasks/mod.rs` | conceptual inspiration only | Strong Harness v1 candidate |
| Suspend/recover same unfinished turn identity | `core/src/codex_thread.rs` | conceptual inspiration only | Worker lease/handoff design |
| Stop hook as completion gate with continuation feedback | hooks + turn loop | conceptual inspiration only | Strong CompletionPolicy candidate |
| Prompt-level validation guidance distinct from acceptance enforcement | default base prompt + runtime | conceptual inspiration only | Explicit evidence/acceptance separation |
| Reviewer sub-agent task | `core/src/tasks/review.rs` | conceptual inspiration only | Optional reviewer/critic orchestration |

No Codex implementation source has been copied or adapted into Cerebro.
