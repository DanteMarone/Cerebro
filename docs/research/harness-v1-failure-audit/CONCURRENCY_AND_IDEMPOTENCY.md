# Harness v1 concurrency and idempotency audit

Issue: #208

## Conclusion

Harness v1 needs to keep four forms of concurrency control separate:

1. **turn/effect ownership** — which worker is currently authorized to advance one durable execution;
2. **provider capacity** — how many requests may run concurrently;
3. **resource/workspace ownership** — which turns may mutate the same external state;
4. **idempotency/reconciliation** — what happens when an effect may already have executed.

A TTL lease, `asyncio.Semaphore`, immutable `StepSnapshot`, and canonical call ID each solve a different problem. None is a substitute for the others.

The central concurrency invariant is fencing:

> Once durable ownership advances, an older worker/attempt may still finish local or remote work, but it must be unable to commit executable state, dispatch a new effect, or publish a final result as current.

The central idempotency invariant is equally important:

> A stable call ID can deduplicate the *same admitted operation*. It cannot prove that a freshly generated, semantically similar call after a model retry is the same real-world operation.

## 1. Current Cerebro lease semantics are coordination, not fencing

At `main@57e9c4...` the `leases` table contains:

```text
resource
holder_id
holder_kind
channel_id
reason
acquired_at
expires_at
```

Acquire/renew/release are atomic SQLite writer transactions. That is useful. There is no monotonically increasing lease generation/fencing token.

Current `docs/LEASE_GUARD.md` also correctly says the git hook is a workflow guard, not a security boundary. It can be bypassed and should not be used as proof that a running tool still owns a workspace.

### Failure sequence

```text
A owns turn/workspace lease
  > A stalls past TTL
  > B acquires same resource
  > B starts work
  > A resumes with stale in-memory state
```

Both A and B can continue unless every meaningful operation verifies more than holder name/old expiry.

### Required invariant

Durable execution ownership has a monotonic epoch/version. Acquisition/takeover advances it. The epoch participates in compare-and-set/transaction predicates for:

- reducer state transitions;
- provider-attempt admission;
- tool-dispatch admission;
- terminal tool-result commit;
- child-run admission where relevant;
- final product publication.

A stale worker can still log that a late remote result arrived, but cannot make it current.

The exact mechanism can be a turn version, execution generation, fencing token or equivalent. The architecture requirement is monotonic stale-owner rejection, not a particular table shape.

## 2. Two workers reduce the same durable state concurrently

A re-entrant reducer is not automatically single-execution.

### Failure sequence

```text
A reads turn version 10: next effect = call provider
B reads turn version 10: next effect = call provider
A persists intent and calls provider
B persists intent and calls provider
```

If “load durable state > compute effect” is not followed by a compare-and-set effect admission, both workers can be internally correct from the snapshot they read.

### Required invariant

A transition that makes an external effect eligible is admitted exactly once against an expected durable turn version and current ownership epoch. A losing concurrent reducer reloads; it does not perform the effect it computed from stale state.

### Required test

Barrier two worker fixtures after both read the same turn version but before transition commit. Release simultaneously. Assert one transition wins, one reloads, and only one provider/tool dispatch is admitted.

## 3. Late completion from a superseded provider attempt

### Failure sequence

```text
attempt A1 streaming slowly
  > cancel/failover decides A1 is abandoned
  > attempt A2 starts from fresh semantic boundary
  > A2 commits output
  > delayed A1 stream emits completion/tool call
```

If event handlers key only by `AgentTurn` and not active attempt/snapshot generation, A1 can append stale output into A2’s canonical history or schedule a stale tool.

### Required invariant

Every provider event is causally bound to one immutable attempt/StepSnapshot identity. Once that attempt is durably superseded/abandoned, later events from it can be retained only as stale diagnostic evidence; they cannot mutate current semantic history, open tool calls, completion policy state or final publication.

### Required test

Run two fake attempts, supersede A1, complete A2, then deliver a late finalized tool call and `InferenceCompleted` from A1. Assert current turn state/history is unchanged and no tool dispatch occurs.

## 4. Process-local provider semaphores are capacity controls only

Phase 0 confirms `AgentRuntime` uses an `asyncio.Semaphore` per provider and releases it safely on ordinary exception/cancellation.

A process restart resets those semaphores. Old provider requests may still be computing remotely. Therefore:

- the semaphore cannot prove a turn is uniquely owned;
- it cannot prove a provider attempt no longer exists;
- it cannot enforce a hard cross-process concurrency ceiling unless replaced/augmented by distributed admission.

For a single-process Harness v1, this is acceptable if documented as best-effort throughput protection. Durable fencing still must carry correctness independently.

## 5. Immutable StepSnapshot versus permission revocation

Snapshot immutability is the right defense against time-of-check/time-of-use reinterpretation: a provider must not see tool definition X and later have its call silently routed to definition Y.

But authority can need revocation.

### Failure sequence

```text
S grants destructive tool T
  > provider is streaming
  > user/admin revokes T due to compromise
  > tool call finalizes
  > runtime says “S was immutable” and executes T
```

That turns reproducibility into a security bug.

### Required distinction

- ordinary catalog/config additions or non-security changes do not mutate S;
- the old call never inherits a newer grant or newer binding;
- a monotonic security revocation/kill epoch may invalidate a previously granted snapshot before external dispatch;
- invalidation produces one explicit denied/stale terminal outcome under the original call identity.

The generic harness does not need to reinterpret why a policy was revoked; it only needs a fail-closed revocation check for grants whose policy says they are revocable.

## 6. Immutable StepSnapshot versus mutable tool binding

A `ToolPlanSnapshot` is only as immutable as the executable binding it references.

Dynamic MCP state can change because of:

- `tools/list_changed`;
- server reconnect/restart;
- credential rotation;
- extension upgrade;
- endpoint failover;
- same model-facing tool name now mapping to different implementation.

### Required invariant

At dispatch, `ToolRuntime` proves the concrete executable binding generation matches the one advertised in the snapshot. If G1 is gone, the old call becomes stale/unavailable. It is never rerouted to G2 merely because the canonical name still exists.

This is already the intended direction in the Harness proposal; the adversarial requirement is that the check happens at execution, not only when the snapshot object is built.

## 7. StepSnapshot versus mutable filesystem/workspace

Snapshotting cwd/workspace metadata does not snapshot file contents or git state.

### Failure sequence

```text
A sees git HEAD H0, file F=v0
B sees git HEAD H0, file F=v0
A writes F=v1, stages/commits H1
B executes edit/shell based on v0 in same tree
```

Possible outcomes include:

- B overwrites A;
- B stages A’s modifications with its own;
- B’s commit moves HEAD while A still validates old work;
- tests run against a mixed tree;
- a model reports “tests passed for my patch” when the tested tree included another agent’s mutations.

### Current lease limitation

Cerebro has file/repo leases for human/agent coordination, but the commit guard is deliberately non-security enforcement and lease TTL is not execution fencing. It also does not automatically make every shell/git invocation conditional on a working-tree version.

### Required invariant

For any tool whose correctness depends on mutable workspace state, the binding declares the resource/version precondition it relies on or executes in an isolated workspace. A write/commit cannot silently apply against a conflicting newer workspace state.

For git specifically, completion evidence should identify the exact tree/commit it verified. “Tests passed” without the tested tree identity is weak evidence under concurrency.

### Minimum safe v1 policy

Preserving current sequential behavior is safer than enabling cross-turn parallel workspace mutations before this is solved. Global serialization is conservative but valid; isolated worktrees or resource-level optimistic concurrency can come later.

## 8. Tool-level `parallel_safe` is too coarse for mutable resources

A tool implementation can be reentrant while two calls to it still conflict because of arguments.

Example:

```text
fs_write(path="x", ...)
fs_write(path="x", ...)
```

or:

```text
git_commit(repo=R, ...)
git_checkout(repo=R, ...)
```

A boolean annotation cannot determine whether concrete calls commute.

### Required invariant

Parallel dispatch is opt-in. If a tool mutates resource-keyed state, the executor/policy derives conflict keys from concrete arguments and serializes/rejects overlapping calls. Until then, the Phase 0 sequential execution of multiple tool calls is the safe default.

## 9. Exact call idempotency versus semantic retry

Suppose canonical call `C1` is persisted and executed once. Stable `C1` can prevent recovery from accidentally dispatching *C1* twice.

It cannot solve this:

```text
C1 = create_issue(title="X") succeeds
  > later provider failure
  > harness rewinds semantic history
  > model generates C2 = create_issue(title="X")
```

`C2` is a different admitted call. Generic code cannot safely infer that it is “really the same” operation based on arguments/text.

### Required invariant

Do not rewind across committed semantic/effect boundaries. Recovery carries committed ToolResults/indeterminate outcomes forward. Task-level semantic retry is a new deliberate attempt with prior evidence present, not a hidden rollback that asks the model to rediscover already-executed side effects.

If a task intentionally wants retry semantics (“try creating a deployment again”), that decision belongs to completion/task policy and executor idempotency, not fuzzy deduplication in the generic harness.

## 10. Cancellation versus tool completion

Cancellation is an intent to stop future autonomous work. It does not establish whether an in-flight remote effect committed.

### Race matrix

| Cancellation point | Truthful generic outcome |
| --- | --- |
| Before external dispatch admitted | call can terminate cancelled; no effect dispatched |
| After admission, before dispatch barrier crossed | cancelled if barrier proves dispatch never happened |
| After remote dispatch may have escaped | success if authoritative success is durably known; otherwise indeterminate unless executor proves cancellation |
| After ToolResult durable | keep ToolResult terminal outcome; cancellation stops subsequent work |
| After next provider step already admitted | that step must observe cancellation/ownership state; late completion cannot admit more effects |

### Required invariant

Tool terminalization is single-assignment/monotonic. Turn cancellation and tool outcome are related but not the same state variable. A later cancellation cannot rewrite a durably successful side effect as though it never happened.

### Required test

Use deterministic barriers to exercise every row above and then restart. Durable reconstruction must produce the same terminal call truth as the live path.

## 11. Cancellation versus CLI/external harness process lifetime

Phase 0 verifies that an explicit `CancelledError` reaches `CliAgentProvider` and terminates/kills the owned child process. Abrupt Cerebro process death is different:

```text
Cerebro worker launches external coding harness
  > harness starts shell/network/git descendants
  > Cerebro worker is killed -9 / machine process dies
  > child or grandchildren may remain alive depending platform/process grouping
  > replacement worker launches a second external harness
```

Even if the direct child dies automatically, effects it already launched may survive.

### Required invariant

`ExternalAgentAdapter` must have explicit execution ownership and orphan semantics separate from direct `ProviderAdapter`. On restart it either:

- reconnects to a durable external session/operation identity;
- proves and cleans up the old execution before replacement; or
- treats the old execution as indeterminate and refuses blind duplicate launch.

Process-group/job-object cleanup is useful local hygiene, not proof of rollback.

## 12. Duplicate wake/admission

A durable reducer does not prevent two durable turns from being created for the same causal trigger.

Likely duplicate-delivery sources include:

- reconnect/replay of message events;
- service retries;
- poller cursor recovery;
- scheduler at-least-once delivery;
- simultaneous workers observing the same trigger.

### Required invariant

Turn admission is idempotent on a stable causal key such as the semantic trigger identity plus target agent. Creation uses a unique constraint/CAS or equivalent so concurrent deliveries converge to one `AgentTurn`.

The causal key must include an occurrence/epoch for intentionally recurring wakes; otherwise a daily poll would collapse forever into its first turn.

## 13. Parent/child concurrency

Durable child lineage solves observability but not idempotent delegation by itself.

### Parent crash sequence

```text
P admits delegation call D
  > child C created and starts
  > P process dies
  > P recovery replays D
  > creates child C2
```

### Required invariant

Delegation admission is keyed by the parent call/effect identity so replay finds C instead of creating C2. Child identity, root/parent lineage, inherited snapshot/scope, budget and ownership are durable before child execution begins.

### Parent cancellation sequence

```text
P cancellation committed
  > C finishes later
  > C result wakes P / schedules continuation
```

A child completion may be retained as durable evidence, but it cannot resurrect a terminally cancelled parent without an explicit resume/new-turn decision.

### Parent terminalization policy

Before delegation ships, architecture needs an explicit policy for whether parent completion is allowed while children remain active. Viable policies include wait, detach with explicit ownership transfer, or cancel descendants. What is unsafe is accidental orphaning where no durable owner/policy explains ongoing effects.

## 14. Shared provider/model continuation and switching

Provider normalization already gives the right semantic rule: required opaque continuation state is provider/model scoped and non-portable.

Concurrency adds one more condition: a switch is not safe merely because a configuration value changed. Any in-flight old attempt can still emit late events.

### Required invariant

Switch/abandon transition advances the active attempt generation. Old provider events are fenced from current semantic history. Opaque state from the old provider remains private to that adapter/audit scope and is never serialized to the new provider.

## 15. Compaction is a concurrent write to executable history

Even if inference is serialized per turn, an asynchronous compactor can race state changes unless its write is conditional.

### Required invariant

A compaction checkpoint includes the exact history/replay version it compacted. Commit uses compare-and-set against that version. If new semantic/replay items arrived, compaction recomputes; it never applies an old trim set to newer history.

Required replay material is pinned at the adapter-defined scope, and a compaction failure/version conflict leaves the previous checkpoint intact.

## 16. Schema version is part of concurrency control

Current migrations are transactionally atomic per SQL file, but an old running process can coexist with a newly migrated database.

Once `agent_turns` drives side effects, this is a stale-worker problem analogous to lease expiry.

### Required invariant

Worker capability/schema epoch participates in execution admission. A process whose reducer/event schema is incompatible with the active DB epoch can remain observable but cannot own/advance turns. Deployment either drains old workers or proves a compatibility window.

## 17. Idempotency hierarchy

Harness v1 should be explicit about which layer owns which idempotency key:

```text
causal wake key
  prevents duplicate AgentTurn creation

AgentTurn / reducer transition version
  prevents duplicate durable next-effect admission

InferenceAttemptId
  distinguishes/reconciles provider requests and late events

CerebroCallId
  canonical identity for one admitted client tool call

executor operation/idempotency key
  prevents/reconciles duplicate real-world effect when supported

final publication key / AgentTurn identity
  prevents duplicate final channel message
```

These keys are not interchangeable. In particular, generating a new `CerebroCallId` during semantic retry defeats exact-call deduplication by definition; the correct protection is monotonic recovery history, not argument matching.

## 18. Tests required before enabling multi-worker or parallel mutation

At minimum:

1. two reducers race same turn version; one effect admission wins;
2. old owner resumes after lease expiry/takeover and is fenced from all authoritative writes/dispatches;
3. superseded provider attempt emits late final call; it is audit-only and cannot execute;
4. stale permission snapshot is invalidated by security revocation before dispatch;
5. stale MCP binding generation cannot route through replacement implementation;
6. two agents edit/commit same repo from same base; conflict is serialized/rejected/isolated and no mixed commit appears;
7. two parallel calls target same mutable resource; they do not run concurrently;
8. cancellation races remote success at every dispatch/result boundary;
9. duplicate wake delivery creates one durable turn;
10. parent crash after child creation discovers same child on recovery;
11. old external harness process/session cannot be blindly duplicated after Cerebro process death;
12. old-schema worker is fenced after incompatible migration activation.

## What can wait

The Phase 1 provider-compatibility implementation does not need to solve all workspace/delegation/distributed scheduling mechanics immediately. It does need to avoid freezing canonical types around assumptions that make them impossible later.

Safe deferrals are conditional:

- keep multiple tool calls sequential until resource-aware parallelism exists;
- keep worker model single-process until fencing exists;
- keep delegated/background child execution disabled until idempotent child admission/lifecycle exists;
- keep provider-hosted side-effecting tools explicit/disabled unless replay barriers exist;
- treat provider semaphore as best-effort capacity control unless cross-process limit is implemented;
- preserve current workspace coordination rules, but do not claim they provide Harness-level isolation/exactness.
