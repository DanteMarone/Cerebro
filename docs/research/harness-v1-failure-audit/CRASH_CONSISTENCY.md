# Harness v1 crash consistency audit

Issue: #208

## Conclusion

Harness v1 should not promise generic exactly-once tool execution. It can guarantee exactly-once **durable Cerebro state transitions** and exactly-once **final channel publication**. It cannot infer exactly-once behavior for an arbitrary remote side effect after a process/network failure unless that executor provides idempotency or reconciliation.

The proposed architecture already contains the correct recovery instinct in `CEREBRO_HARNESS_V1.md`: on startup, recover only when the last durable boundary is safe and no side-effecting operation is indeterminate; otherwise stop in `suspended`/`failed_needs_attention` rather than guessing. That rule should be promoted into the execution schema and tests. The current proposed `ToolResult.status` (`success | error | cancelled | denied | timeout | unavailable`) cannot represent the indeterminate case truthfully.

The crash-consistency design therefore needs to answer one question at every external-effect boundary:

> After restart, what durable fact proves that repeating the next operation is safe?

If there is no such fact, recovery must not repeat it automatically.

## Durable boundary model

Names below are analytical labels, not a replacement architecture.

```text
B0  causal wake admitted / AgentTurn identity durable
B1  provider attempt admitted / stable attempt identity durable
B2  finalized provider semantic output checkpoint durable
B3  executable client-tool call checkpoint durable
    (call + native ref + required replay + StepSnapshot binding)
B4  external tool dispatch may have escaped process
B5  worker observes executor outcome in memory
B6  terminal/indeterminate tool outcome durable
B7  CompletionPolicy accepts final output
B8  final product publication + durable turn terminal state committed
```

The dangerous windows are not symmetrical:

- B0 > B1 is locally recoverable if provider request was never sent.
- B1 > B2 may have duplicated inference/cost if the request reached the provider.
- B2 > B3 is safe for client tools because no side effect is executable yet.
- B3 > B4 is safe if durable ownership still proves this worker is the sole authorized dispatcher.
- **B4 > B6 is inherently ambiguous for generic non-idempotent remote tools.**
- B6 > B7 is normally recoverable from durable semantic/tool history.
- B7 > B8 must be idempotent/atomic or users get duplicate/missing final chat.

## 1. Before provider dispatch

### Failure window

```text
compute StepSnapshot / request
  > process dies
  > no request sent
```

This is safe if request dispatch requires a durable attempt/admission record and the worker can prove the network call was not started.

### Required invariant

Provider attempt identity exists before network dispatch. The reducer never relies on an in-memory “about to call provider” state as a resumable boundary.

### Why this matters even for side-effect-free inference

Without attempt identity, duplicate requests are difficult to distinguish in logs/usage and a later stream retry can be attributed to the wrong snapshot. With provider-hosted tools, request duplication can become a correctness failure rather than only extra cost.

## 2. Provider request sent, no durable semantic checkpoint

### Failure window

```text
B1 attempt durable
  > request reaches provider
  > provider computes / may finish
  > process dies before B2
```

A replacement worker knows the attempt was admitted but not whether the provider performed semantic work.

For ordinary client-tool inference, a fresh request may be an acceptable **new attempt**, but it is not a transparent replay. The second model output can differ and cost twice. If the adapter uses provider idempotency/continuation primitives, those can narrow the ambiguity, but provider cache/session handles cannot be the sole correctness state.

For provider-hosted side effects, whole-request replay is unsafe unless the provider proves idempotency.

### Required invariant

`retryable transport failure` and `safe semantic replay` are separate decisions. A request may be safely retried by the adapter only while the adapter/harness knows no provider-managed semantic effect that matters has committed. Otherwise recovery creates a fresh explicit attempt or stops for attention.

### Required crash test

Kill after a fake provider records request receipt and after it records completed output, but before Cerebro writes B2. Recovery must retain the original attempt identity and make an explicit replay/fresh-attempt decision.

## 3. Provider output finalized, replay checkpoint not yet executable

Provider normalization correctly closes the most dangerous native-API race:

```text
streamed tool JSON appears complete
  > native call ID / signature / opaque reasoning arrives later
  > finalized ordered items + required replay are persisted
  > only then call becomes executable
```

### Required invariant

No `ToolCallInputDelta`, partial JSON, early call-name event or provisional provider block is execution authority. Only a completed canonical call whose provider correlation/replay dependencies are durably checkpointed can cross B3.

### Crash behavior

Any death before B3 causes zero client-tool execution. Recovery may reconstruct/retry inference according to provider-attempt rules, but there must be no external client-tool effect to reconcile.

### Required crash test

Place a kill point after complete-looking arguments but before late native replay/signature material and assert tool invocation count remains zero.

## 4. Tool dispatch: the irreducible ambiguity window

This is the central audit finding.

### Bad assumption

```text
no ToolResult row
  therefore tool did not happen
```

That implication is false after B4.

### Example sequence

```text
B3 executable checkpoint durable
  > HTTP POST create_issue
  > server commits issue #500
  > response reaches worker
  > process dies before B6
```

After restart, Cerebro knows the call was executable and non-terminal. It does not know whether issue #500 exists unless the remote API supports a stable request/idempotency key or queryable operation identity.

### Required invariant

A call has distinct durable meaning before and after dispatch may have escaped:

- before external dispatch: safe to execute once under current fencing/ownership;
- after dispatch may have escaped: never automatically execute again unless executor contract proves retry safety;
- after durable terminal result: continue normally;
- after ambiguous dispatch with no reconcilable result: persist/surface an indeterminate outcome and stop/replan without claiming the side effect failed.

The exact enum name is not important. The state must be representable and reconstructable.

### Tool-contract implications

Executor metadata should be able to state at least the semantics recovery needs:

- read-only/no side effect;
- idempotent under identical canonical operation key;
- externally idempotent only when a supplied idempotency key is reused;
- reconcilable through an authoritative lookup;
- non-idempotent/unreconcilable.

A static `parallel_safe` flag or human-readable tool annotation is not enough to decide crash replay.

### Required crash tests

For the same canonical call, exercise:

1. death before dispatch — exactly one execution after restart;
2. death after remote effect but before response — no blind second execution;
3. death after response but before local result — no blind second execution;
4. idempotency-key executor — retry with identical key yields one remote effect;
5. reconcilable executor — recovery queries effect, synthesizes truthful durable result, no duplicate dispatch;
6. unreconcilable executor — recovery records indeterminate/needs-attention and does not dispatch.

## 5. Local subprocesses are easier but not universally safe

Current `CliAgentProvider` cancellation kills its owned child process and Phase 0 tests that behavior. Local child-process tool execution can sometimes provide stronger crash semantics than remote calls, but process death can still leave grandchildren, OS-level operations, git/network commands or already-written files.

Therefore “we killed the process” is not generic proof that no effect occurred.

Required invariant: executor-specific cancellation acknowledgement determines what terminal status can truthfully be claimed. A timeout/cancel after a command has already committed filesystem/network effects is not automatically rollback.

## 6. Tool result observed in memory, persistence fails

### Failure window

```text
remote success returned
  > worker has full result
  > DB write fails / process dies
```

This is semantically the same ambiguity as a lost network response unless the result can be recovered by stable operation identity. Retrying the DB write in memory is useful but does not solve process death.

### Required invariant

Raw/full tool result needed for recovery must be durably captured before the next provider step. If its persistence cannot be confirmed, the harness must not proceed as though B6 happened.

The raw-vs-model-visible result split is helpful here: durable raw result/artifact identity is the recovery fact; bounded model projection can be regenerated.

## 7. Durable event log versus `agent_turns` projection

The proposed schema intentionally keeps both:

```text
agent_turns = current indexed projection
turn_events = audit/reconstruction log
```

That creates a classic crash-consistency question: are they two writes or one transition?

### Failure A

```text
append ToolSucceeded event
  > crash
  > agent_turns still says tool running
```

A reducer that trusts the projection may re-run the tool.

### Failure B

```text
projection advances to tool succeeded
  > crash
  > event missing
```

Audit/reconstruction no longer explains why execution advanced.

### Required invariant

Every state transition that changes what effect is executable next must be one atomic SQLite transaction (event(s) + projection version + ownership/version check), or the design must make one representation purely derivable from the other and validate a monotonic version before execution.

The current database already has `run_in_writer()` with `BEGIN IMMEDIATE`, so this is compatible with current local persistence. The important point is not implementation style; it is that the reducer cannot make external-effect decisions from an unversioned partially-updated projection.

### Required tests

Fault-inject between event insert, projection update and transaction commit. Every surviving DB state must reconstruct to one unambiguous next action.

## 8. CompletionPolicy accepted, final channel message not atomically finalized

Current Phase 0 behavior gives Cerebro a useful product invariant:

- no placeholder/intermediate agent message rows;
- one final row at completion;
- concurrent final replies ordered by completion time;
- topic PASS/silent completion writes zero final agent rows;
- DM silence/PASS fails closed.

Adding `AgentTurn` creates a second durable completion object.

### Crash sequence A — duplicate answer

```text
CompletionPolicy allow
  > INSERT final messages row
  > crash
  > AgentTurn still non-terminal
  > startup recovery resumes turn
  > INSERT second final messages row
```

### Crash sequence B — missing answer

```text
CompletionPolicy allow
  > mark AgentTurn completed
  > crash
  > final message never inserted
```

### Required invariant

Accepted product completion has one durable idempotency identity and finalization commit. For ordinary chat completion, the final message row and terminal-success turn state must be committed atomically in one local database transaction or through an equivalent outbox/idempotent recovery protocol.

Because both objects are currently in the same SQLite database, a single transaction is the simplest available consistency model; the invariant is what matters, not this implementation suggestion.

The final message’s auto-increment ordering should reflect transaction/commit order so the current completion-order behavior remains observable.

### Silent outcomes

PASS/silent topic completion is also a terminal product result, just one whose `message_id` is intentionally absent. Recovery must distinguish “intentionally no row” from “final message write lost.” DM rules still fail closed.

### Required tests

Kill at every finalization statement and restart repeatedly. Assert:

- exactly one final message for ordinary completion;
- zero for valid topic PASS/silent completion;
- one fail-closed error message for forbidden DM silence/PASS;
- no completed-success turn whose product outcome is unexplained;
- no visible final message whose owning turn can later produce another final answer.

## 9. Hub publication after durable commit

Current completion publishes `message.new` and `message.done` after the row exists. A crash between DB commit and Hub event can lose a transient notification; a crash after publish but before caller acknowledgement can duplicate it.

This is lower severity than message duplication because clients can reconstruct durable messages after reconnect.

### Required invariant

Hub/WebSocket events are not the durable source of truth for final messages or execution state. Consumers must tolerate duplicate/lost transient events and resynchronize from durable state. If a future consumer requires exactly-once downstream effects from Hub events, it needs a durable outbox/consumer cursor rather than assuming in-process publish is transactional with SQLite.

## 10. Usage/audit persistence failures

Phase 0 intentionally treats usage persistence failure as non-fatal. Preserve that only for telemetry semantics.

If a future Harness uses the same data to enforce hard budgets, security grants, idempotency or effect audit, best-effort persistence becomes a correctness bug.

### Required invariant

Classify durable facts by consequence:

- telemetry/UX metrics may be best effort;
- execution ownership, replay state, tool outcome, hard budget reservation, authorization/effect evidence and finalization cannot be best effort.

A hard budget should be admitted/reserved durably before a provider request if exceeding it is prohibited; actual usage can then reconcile the reservation.

## 11. Schema migration crash versus mixed-version workers

Current `db.migrate()` has a strong local property: each migration file runs under `BEGIN IMMEDIATE`, and the new `schema_version` row commits in the same transaction. A process crash during one migration should leave either the old or new migration version, not half of that file.

The more serious risk is mixed-version execution:

```text
old worker A running schema/event semantics N
  > new process B migrates DB to N+1
  > B starts new reducer
  > A keeps running old in-memory code
```

The health endpoint can report running commit/schema version, but observability is not fencing.

### Required invariant

Before a worker can transition an `AgentTurn`, dispatch an effect or finalize a result, its supported harness schema/event version and ownership epoch must still be valid for the database. A semantic migration either drains/fences old workers or is explicitly backward-compatible for the entire coexistence window.

### Required tests

Keep an old fixture worker alive through migration. After N+1 activation, attempts by A to renew ownership, append executable events, dispatch tools or finalize output must be rejected unless the fixture is declared compatible.

## 12. Crash matrix

| Crash point | Durable knowledge after restart | Safe generic action |
| --- | --- | --- |
| Before wake/turn admission | No turn | Re-delivery may create turn using causal idempotency key |
| After turn admission, before provider attempt | Turn exists, no provider attempt | Resume and admit provider attempt |
| After attempt admission, before network dispatch known | Attempt exists | Dispatch only if durable state proves it never crossed dispatch |
| Provider request may have reached service, no semantic checkpoint | Remote inference outcome unknown | Adapter/recovery decision; fresh attempt or reconcile; never pretend “not sent” |
| Completed call-looking deltas, before finalized replay checkpoint | No executable call | Do not execute tool |
| Finalized replay checkpoint, before tool dispatch | Executable call, effect not yet escaped if dispatch barrier proves it | Current fenced owner may dispatch once |
| Tool dispatch may have escaped, no terminal result | External outcome unknown | Reconcile/idempotent replay if guaranteed; otherwise indeterminate/needs attention |
| Terminal ToolResult durable | Effect/result known to Harness | Continue reducer; never re-execute call |
| Completion accepted, before finalization transaction | Accepted output durable | Idempotently finalize product result |
| After finalization transaction | Final message/silent outcome + terminal turn consistent | No execution; transient Hub events may be replayed/best-effort |

## What issue #206 should freeze

Before implementation, architecture reconciliation should state explicitly:

1. durable attempt/admission identities exist before provider/tool external dispatch;
2. replay safety is distinct from error retryability;
3. pre-tool provider replay checkpoint is a hard executable barrier;
4. post-dispatch missing result can be indeterminate and must not trigger blind non-idempotent replay;
5. reducer executable transitions are atomic/versioned with their event/projection state;
6. stale worker epochs cannot commit or dispatch;
7. terminal tool outcomes are monotonic and truthful under cancellation/timeout races;
8. final channel publication and terminal turn result are one idempotent durable finalization;
9. mixed-version workers cannot execute against an incompatible migrated schema;
10. transient Hub/UI events are never the source of recovery truth.
