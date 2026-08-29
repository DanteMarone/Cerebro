# Required Harness v1 invariants

Issue: #208

These are the minimum invariants the #206 architecture freeze should carry forward. They are intentionally narrower than a replacement design. An implementation may satisfy them with different schemas/mechanisms as long as the observable safety properties and crash tests hold.

## Priority legend

- **P1-contract:** must be representable in the Phase 1 canonical types/provider contract even if the full execution subsystem arrives later.
- **Before durable execution:** can be implemented after Phase 1, but must exist before `AgentTurn`/ToolRuntime recovery owns side effects.
- **Before feature enablement:** required before the named optional/concurrent feature is enabled.

## I-01 — Causal turn admission is idempotent

Repeated delivery of the same semantic wake for the same agent creates one durable `AgentTurn`, not two.

A wake has a stable causal admission key. Intentionally repeated scheduled/poll occurrences have distinct occurrence identities.

**Covers:** R-22.

**Gate:** Before durable TurnCoordinator/restart delivery.

**Required test:** deliver one trigger concurrently and again after restart; exactly one turn/effect/final response exists.

## I-02 — Provider attempt identity is durable before network dispatch

Every provider request has a stable Cerebro attempt identity bound to the immutable StepSnapshot/request semantics before the request can leave the process.

A missing local completion after restart is not interpreted as proof that the provider never received the attempt.

**Covers:** R-03, R-04, late/superseded attempt races.

**Gate:** **P1-contract.**

**Required test:** kill after fake provider receipt but before local output persistence; recovery retains the same admitted attempt and makes an explicit recovery decision.

## I-03 — Completed output items, not deltas, are semantic authority

Streaming deltas are transient UX/parser facts. Tool execution, durable history and completion decisions use finalized `OutputItemCompleted` canonical items.

Partial arguments, early call names, array indexes and provisional provider blocks are never executable authority.

**Covers:** R-05.

**Gate:** **P1-contract.**

**Required test:** complete-looking JSON arrives before final native call reference/signature; tool execution remains zero until completed item checkpoint.

## I-04 — Provider-valid replay checkpoint precedes client-tool execution

Before a client tool can become executable, Cerebro durably holds:

- finalized canonical `ToolCallItem`;
- stable `CerebroCallId`;
- required native `ProviderCallRef`;
- all preceding adapter-owned replay material required for continuation;
- provider semantic options/replay checkpoint version;
- immutable StepSnapshot/tool binding/policy evidence.

Loss of process memory after this boundary does not make the provider continuation unreconstructable.

**Covers:** R-05, R-18.

**Gate:** **P1-contract.**

**Required test:** kill at every stream/finalization boundary; no tool executes before this set is durable.

## I-05 — Error retryability is distinct from semantic replay safety

`transient`, `rate_limited`, timeout or stream failure does not by itself authorize repeating semantic work.

Recovery has an explicit disposition such as same-request transport retry, fresh attempt from durable checkpoint, compact-then-fresh, auth refresh, or not replay-safe. The generic runner does not rewind over committed effects because an HTTP/provider error looks retryable.

**Covers:** R-03, R-04, R-06.

**Gate:** **P1-contract.**

**Required test:** inject a transient failure after durable semantic/tool progress; assert recovery carries progress forward and does not re-run the committed effect.

## I-06 — Durable semantic progress is monotonic across recovery

Once a semantic output/tool outcome is durably committed, restart/retry does not silently roll back to an earlier checkpoint that omits it.

Task-level “try again” is a new deliberate attempt with prior evidence represented, not an invisible rewind.

**Covers:** R-06.

**Gate:** **P1-contract** for history/attempt semantics; execution enforcement later.

**Required test:** persist a tool result, fail the next provider step, restart; the result remains in history and the tool is not re-executed due to rollback.

## I-07 — Dispatch ambiguity is a first-class durable state

For a side-effecting call, the harness can distinguish:

1. not externally dispatched / safe to execute;
2. external dispatch may have escaped / outcome not durably known;
3. terminal outcome durably known.

After state 2, absence of a ToolResult is never treated as evidence that the effect did not occur.

The exact enum/name is implementation-defined, but the current proposed `success | error | cancelled | denied | timeout | unavailable` set is insufficient unless an orthogonal execution state carries this distinction.

**Covers:** R-01, R-02, R-09, R-10.

**Gate:** **P1-contract.**

**Required test:** kill after remote side effect but before ToolResult persistence; restart cannot blindly dispatch again.

## I-08 — External side-effect replay requires executor proof

Automatic repeat dispatch after uncertainty is permitted only when the executor contract proves one of:

- operation is read-only/no side effect;
- repeated execution is idempotent;
- a stable idempotency/operation key is reused and the external service enforces it;
- authoritative reconciliation proves the original effect did not occur or recovers its result.

Otherwise the call becomes indeterminate/needs attention and no automatic second effect is issued.

**Covers:** R-01, R-02, R-04, R-10.

**Gate:** **P1-contract** must leave room for recovery/idempotency metadata; enforcement before durable ToolRuntime.

**Required test:** fake non-idempotent endpoint commits then loses response; recovery performs zero second mutations. Idempotent fixture may safely retry with the same key and still record one remote mutation.

## I-09 — One canonical call has one monotonic durable terminal outcome

An admitted `CerebroCallId` cannot end as both success and cancelled/error, and a later lifecycle signal cannot rewrite a truthful completed effect.

If the effect outcome is genuinely unknown after dispatch, the durable terminal/recovery state says so rather than fabricating failure.

**Covers:** R-01, R-02, R-09, R-10.

**Gate:** **P1-contract.**

**Required test:** race tool success, timeout and cancellation commits; exactly one truthful outcome is authoritative after restart.

## I-10 — Worker ownership is fenced, not merely leased

Ownership/takeover advances a monotonic execution epoch/version. Every authoritative reducer transition, provider/tool effect admission and final publication verifies the current epoch/version.

An expired, partitioned or resumed stale worker cannot mutate current execution state merely because it once held a TTL lease.

**Covers:** R-02, R-15, R-21 and stale external-attempt completion.

**Gate:** Before durable multi-worker/restart execution.

**Required test:** stall worker A beyond TTL, let B take over, then resume A; A cannot dispatch, terminalize or finalize current work.

## I-11 — Reducer next-effect admission is compare-and-set/atomic

Two workers reducing the same durable turn version cannot both make the same next external effect eligible.

The state/version transition that admits an effect is atomic with its expected turn version/current ownership check.

**Covers:** R-02, R-07, R-15.

**Gate:** Before durable execution.

**Required test:** two reducers read identical state, race admission, and only one provider/tool dispatch becomes authorized.

## I-12 — Execution events and current projection cannot diverge executably

`turn_events` and `agent_turns` must either be updated in one transaction for each executable transition, or one must be explicitly derivable/authoritative with a monotonic version check that prevents action from a stale projection.

A crash cannot leave two plausible “next effects.”

**Covers:** R-07.

**Gate:** Before durable `AgentTurn` schema ships.

**Required test:** fault inject between every event/projection write boundary and restart; exactly one next reducer action is reconstructable.

## I-13 — Cancellation stops future work but does not rewrite history

Cancellation is a durable control/lifecycle fact. It does not imply that an already-dispatched external effect failed.

- pre-dispatch cancellation can truthfully prevent the effect;
- post-dispatch cancellation requires executor proof to claim no effect;
- a durably successful ToolResult remains successful;
- after terminal turn cancellation, no new provider/tool step may be admitted;
- late completions may be audited but cannot resurrect autonomous execution.

**Covers:** R-09, R-10.

**Gate:** **P1-contract** for outcome/lifecycle separation; enforcement with durable execution.

**Required test:** cancellation at every dispatch/result boundary produces the same durable truth live and after restart.

## I-14 — StepSnapshot binding identity is verified at dispatch

The executable tool implementation/generation used at dispatch is the one captured/advertised by the snapshot.

If an MCP server/catalog/endpoint reconnects or changes to a new generation, an old call cannot silently route to the new implementation. It gets one stale/unavailable outcome unless the original binding remains explicitly addressable.

**Covers:** R-12.

**Gate:** Before StepSnapshot ToolRuntime execution.

**Required test:** snapshot G1, replace server with same-named G2, execute old call; G2 invocation count remains zero.

## I-15 — Security revocation may invalidate a frozen grant without rebinding it

Snapshot immutability prevents silent policy reinterpretation, but a security-critical grant can carry a revocation/kill epoch checked immediately before side-effect dispatch.

A revoked old call is denied/stale under its original identity. It never inherits a newer grant or tool definition.

**Covers:** R-11.

**Gate:** Before privileged/destructive tool execution.

**Required test:** revoke tool authority while provider is streaming; finalized call is not executed.

## I-16 — Mutable workspace preconditions are checked or isolated

A frozen cwd/path alone is not sufficient for write correctness. Side-effecting workspace/git operations either execute in isolated state or verify the resource/version preconditions on which the model/tool plan depended.

Conflicting shared-tree writes cannot silently overwrite/include another turn’s mutations. Verification evidence identifies the exact resulting tree/artifact state it checked.

**Covers:** R-13, R-14.

**Gate:** Before concurrent Harness-owned workspace mutation. Sequential execution is a safe temporary policy.

**Required test:** two agents start from one git base and interleave edits/staging/commits; no mixed/unowned commit or stale-success evidence is possible.

## I-17 — Parallel mutation is resource-aware and opt-in

A tool-level `parallel_safe` annotation does not authorize conflicting concrete calls. Executor/policy can derive conflict keys or otherwise prove operations commute.

Until that exists, preserve Phase 0’s sequential handling of multiple tool calls.

**Covers:** R-14.

**Gate:** Before parallel tool execution.

**Required test:** same tool/same mutable resource serializes or conflicts; independent resources may run concurrently.

## I-18 — Active required replay state is pinned under versioned compaction

Compaction cannot summarize, reorder or remove provider/native material required by an open continuation. The compaction plan is conditional on the exact history/replay-scope version it analyzed.

If that version changed before commit, compaction retries/recomputes and the prior checkpoint remains intact.

**Covers:** R-17.

**Gate:** Replay metadata is **P1-contract**; transactional compaction before ContextManager compaction ships.

**Required test:** pause compactor, extend replay scope, resume; stale compaction cannot commit.

## I-19 — Provider/model switch is a fresh semantic boundary when replay is incompatible

Opaque replay state is never translated across incompatible provider/model families.

If a required continuation is open, Harness either finishes it with the owning compatible adapter or durably abandons that attempt before creating a fresh semantic step. Switch/abandon supersedes the old attempt so late events cannot become current.

**Covers:** R-18 and late-provider-event races.

**Gate:** **P1-contract.**

**Required test:** open continuation on A, switch to B; no A opaque material reaches B, and late A completion cannot execute tools or finish current turn.

## I-20 — Final product publication is idempotent and consistent with turn terminalization

For ordinary completion, the accepted final output, final `messages` row identity and terminal-success `AgentTurn` state form one durable finalization decision.

Recovery may retry finalization but cannot create a second final message. A turn cannot be completed-success with an unexplained missing product result.

Topic PASS/silent completion is an explicit successful product outcome with intentionally no final agent message. DM PASS/silence remains fail-closed per Phase 0.

**Covers:** R-08.

**Gate:** Before durable `AgentTurn` finalization.

**Required test:** kill at every finalization statement and restart repeatedly; exactly one correct product outcome remains and completion ordering is preserved.

## I-21 — Hub/UI events are derived, not recovery truth

Live deltas, `message.new`, `message.done`, activity and similar fanout may be duplicated/lost across process failure. Durable database state is the recovery source of truth; reconnecting consumers can resynchronize.

If a future downstream side effect requires exactly-once event delivery, it needs its own durable outbox/cursor semantics.

**Covers:** finalization/event crash windows.

**Gate:** Before relying on Hub events for any correctness action.

**Required test:** drop/duplicate Hub events around durable commit; DB/product state remains correct and reconnect reconstructs it.

## I-22 — Hard budget/authorization facts are not best-effort telemetry

Usage/audit persistence may remain non-fatal only when it is observational telemetry.

Any record used to admit provider spend, authorize an effect, prove idempotency, reconstruct a side effect or enforce a hard limit must be durably committed at the corresponding admission boundary.

**Covers:** R-20.

**Gate:** Before budgets/audit are promoted to hard execution guarantees.

**Required test:** fail accounting persistence at the hard-limit boundary; no unreserved request escapes while telemetry-only failure remains non-fatal.

## I-23 — Mixed-version workers cannot execute incompatible durable state

Each worker knows the harness schema/event versions it supports. After a semantic migration activates an incompatible database epoch, old workers are drained/fenced or operate only within an explicitly compatible read/write window.

Atomic SQL migration alone is insufficient because an old process can remain alive after the new schema commits.

**Covers:** R-21.

**Gate:** Before first durable Harness schema migration/deployment.

**Required test:** keep old worker alive through migration; after activation it cannot renew executable ownership, append incompatible events, dispatch tools or finalize current turns.

## I-24 — Delegation admission is idempotent and lineage-owned

A parent delegation effect maps to one durable child identity. Parent recovery discovers that child rather than creating another.

Parent cancellation/completion defines what happens to active descendants; late child completion cannot autonomously resurrect a cancelled/stale parent.

**Covers:** R-19.

**Gate:** Before child/background agents.

**Required test:** kill parent after child creation and after child completion/before result consumption; exactly one child exists and recovery is deterministic.

## I-25 — External harness processes/sessions have explicit orphan semantics

`ExternalAgentAdapter` execution is not treated like a stateless provider HTTP call. Abrupt Cerebro death may leave an external coding harness/session/descendant effect active.

Restart must reconnect by durable external execution identity, prove cleanup, or mark the old execution indeterminate before launching replacement. Explicit cancellation cleanup is not proof that crash cleanup happened.

**Covers:** external-harness orphan/double-launch failure mode.

**Gate:** Before Harness v1 owns recoverable CLI/external-agent execution.

**Required test:** kill Cerebro while fake external harness remains active; restart cannot launch a duplicate until old execution is reconciled/terminated/declared indeterminate.

## I-26 — Provider semaphores are never correctness ownership

Process-local concurrency limits may remain best-effort capacity controls. Correctness, duplicate prevention and budget admission must not depend on semaphore state surviving process death.

If Cerebro promises a hard global provider-concurrency limit, it needs cross-process admission; otherwise restart oversubscription is an accepted capacity behavior, not an execution-ownership mechanism.

**Covers:** R-16.

**Gate:** Before claiming cross-process provider concurrency guarantees.

**Required test:** restart with lingering fake provider requests; turn/effect correctness remains intact regardless of semaphore reset.

## Minimal Phase 1 contract changes implied by this audit

The exact schema belongs to #206, but Phase 1 canonical contracts must leave room for these facts:

1. stable inference-attempt identity and immutable StepSnapshot association;
2. semantic retry/replay disposition separate from provider error retryability;
3. completed ordered output items and durable provider replay/native call references;
4. tool execution state capable of distinguishing “not dispatched,” “may have executed,” and durable terminal result;
5. executor idempotency/reconciliation capability metadata sufficient for recovery decisions;
6. cancellation/lifecycle state separate from truthful tool execution outcome;
7. provider/model replay compatibility and explicit abandonment boundary;
8. version identities needed later for fenced turn ownership and stale-attempt rejection.

Without those, later recovery code will be forced either to add breaking state-model changes or to guess in exactly the crash windows this audit is meant to prevent.

## Invariants that can be implemented later without weakening Phase 1

Implementation may safely defer these only while the corresponding feature stays constrained:

- turn/event projection transactions and worker fencing until durable `AgentTurn` execution is introduced;
- workspace isolation/resource conflict handling while tool execution stays sequential/single-owner;
- resource-aware parallelism while current sequential multiple-tool behavior is preserved;
- child lineage/recovery while delegated/background agents are disabled;
- external harness restart ownership while CLI adapters remain outside durable re-entry guarantees;
- hard global provider semaphore while concurrency is documented as process-local capacity;
- hard budget reservation while usage is explicitly telemetry rather than enforcement;
- mixed-version fencing until the first Harness semantic schema migration, provided deployments are drained before then.

The invariant must be decided before the feature is enabled, even when its implementation is deferred.
