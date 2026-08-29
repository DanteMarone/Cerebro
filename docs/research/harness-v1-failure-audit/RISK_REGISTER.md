# Harness v1 adversarial risk register

Issue: #208

This register attacks the proposed Harness v1 architecture at crash, restart, retry, concurrency, cancellation and schema boundaries. It does not propose a replacement architecture. Each missing mechanism is stated only as far as needed to define a safety invariant and a deterministic test.

## Evidence baseline

Architecture/research inputs are pinned exactly to:

- `research/codex-harness-mining@3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- `research/goose-harness-mining@ddb3ad9b5951fcbfe51420aac10df213200ccad5`
- `research/provider-api-normalization@f33801a853b6e6952e07767c83947fd582a41f13`
- issue #206

Local-source constraints are checked against `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7` and the accepted Phase 0 characterization `df542c53f587c8963ce84e8d83d731473ee7bd0d`.

Severity uses `Critical | High | Medium | Low`. Likelihood describes a long-running collaborative agent deployment, not a short unit-test run. Detectability uses `Poor | Moderate | Good`: poor means the durable database can look internally plausible while the external world is wrong.

## Executive disposition

The architecture already contains one unusually strong invariant: finalized provider output, native call references and required replay material must be durable before a client tool side effect is dispatched. Keep it.

The largest missing invariant is the mirror image after dispatch: **once an external side effect may have escaped, absence of a durable ToolResult is not proof that the effect did not happen.** A restarted harness must represent that ambiguity instead of silently re-running an arbitrary non-idempotent call.

The second major gap is **fencing**. Durable state plus TTL leases do not prevent a stale worker from continuing after ownership moved. Every authoritative transition/dispatch needs a turn version or execution epoch that a stale owner cannot successfully use.

The third is **atomic final publication**. Completion-ordered channel messages are a product invariant, but the proposed `AgentTurn` introduces a second durable object. The final message and durable completion must be one recoverable/idempotent commit decision, not two unrelated writes.

## R-01 — Tool side effect succeeds, process dies before ToolResult persistence

**Triggering sequence**

1. A finalized `ToolCallItem`, `ProviderCallRef`, required replay items and executable checkpoint are durably committed.
2. `ToolRuntime` dispatches a non-idempotent external operation, for example pushing a git ref, sending a message, creating a remote task, charging a card-like API, or mutating an MCP-backed service.
3. The external service performs the side effect and returns success to the worker.
4. The process dies before the terminal `ToolResultItem`/tool event is durable.
5. A replacement worker reconstructs the call as non-terminal.
6. Recovery executes it again.

**Resulting incorrect state:** the external effect occurs twice while Cerebro may record only one result. For some tools the second invocation can be destructive or produce a different object, making later reconciliation impossible.

**Severity:** Critical.

**Likelihood:** Medium. The vulnerable interval is short, but every side-effecting call creates it and process death does not need to be frequent for the eventual probability to matter.

**Detectability:** Poor. The durable log can look like one successful recovery while the remote service contains two effects.

**Does the proposed architecture prevent it?** No. “Every admitted call gets one terminal result” and “retries never duplicate a committed tool side effect” are goals, but they do not distinguish “never dispatched” from “may have executed but result was not committed.” The pre-tool replay checkpoint protects provider continuation, not the post-tool external-effect window.

**Missing invariant:** once dispatch of a non-read-only call may have crossed the process boundary, recovery must not infer non-execution from a missing result. The durable call must be recoverable as an **uncertain/unknown outcome** unless the binding supplies a stable idempotency key or authoritative reconciliation operation proving whether the effect happened. Automatic re-execution is allowed only under an explicit retry-safe/idempotent contract.

**Required test:** deterministic kill point after a fake remote executor records its side effect but before Cerebro persists the result. Restart. Assert the side effect count remains one; recovery either reconciles using the same stable operation key or persists/surfaces an uncertain outcome and does not dispatch again.

**Phase 1 disposition:** **Blocks the Phase 1 type contract.** Execution can arrive later, but Phase 1 must not freeze `ToolResult`/execution-state types that can express only `success|error|cancelled|timeout` and thereby force an ambiguous post-dispatch state to be mislabeled.

## R-02 — Worker restarts and executes the same admitted tool twice

**Triggering sequence**

1. Worker A owns an `AgentTurn` and durably identifies tool call `C1`.
2. A records/starts dispatch of `C1`, then stalls, loses its lease, or becomes network-partitioned from the database while the tool continues remotely.
3. Worker B takes ownership and sees `C1` without a terminal result.
4. B dispatches `C1`.
5. A later resumes or its original remote request finishes.

**Resulting incorrect state:** two concurrent executions of one canonical call, potentially with two conflicting terminal results.

**Severity:** Critical.

**Likelihood:** Medium.

**Detectability:** Moderate if both results reach Cerebro; poor if only one does.

**Does the proposed architecture prevent it?** Partially. Durable `AgentTurn` identity and startup stale-turn recovery help locate the work, but no explicit effect reservation/fencing rule prevents both owners from dispatching the same call. Current Cerebro TTL leases have no fencing token.

**Missing invariant:** an admitted effect has one durable execution identity and at most one currently authorized dispatcher epoch. A stale owner must be unable to commit a result or begin another external dispatch after ownership advances. This still does not manufacture exactly-once external effects; it must be combined with R-01’s uncertainty/idempotency rule.

**Required test:** pause worker A immediately after it is authorized to dispatch. Expire/take over ownership with worker B. Resume A. Assert only the current fenced owner may cross the dispatch barrier or commit a result; if A had already crossed the barrier, B treats the call as uncertain rather than blindly re-running it.

**Phase 1 disposition:** **Can wait for the durable ToolRuntime/worker-ownership phase**, but the durable call/attempt identities required for fencing must not be designed away in Phase 1.

## R-03 — Provider output exists, process dies before semantic checkpoint

**Triggering sequence**

1. A provider request is accepted and produces completed assistant output, possibly including tool calls.
2. The adapter has received enough provider output to know semantic work occurred.
3. The process dies before the corresponding completed inference items/attempt status are durably checkpointed.
4. Recovery reconstructs only the pre-request state and submits the inference again.

**Resulting incorrect state:** duplicated model work/cost and potentially a materially different second answer or tool plan. If the provider request included provider-hosted side effects, the duplicate can escape Cerebro entirely (R-04).

**Severity:** High for client-tool-only inference; Critical if provider-managed effects are enabled.

**Likelihood:** Medium.

**Detectability:** Moderate for cost/repeated request IDs; poor for provider-side hidden work.

**Does the proposed architecture prevent it?** Partially. `OutputItemCompleted` and sparse durable inference checkpoints define what should become authoritative, but the architecture does not yet define a durable inference-attempt intent/progress barrier before request dispatch or a rule for a request whose remote outcome is unknown after process death.

**Missing invariant:** each provider request has a stable Cerebro attempt identity committed before network dispatch. Recovery distinguishes `not_dispatched`, `dispatched/no_semantic_checkpoint`, `semantic_progress_committed`, and terminal outcomes sufficiently to decide whether same-request replay is safe. A missing local completion is never itself proof the provider did no work.

**Required test:** fake provider records receipt and completed output, then the worker is killed before local semantic checkpoint. Restart with and without provider idempotency/continuation support. Assert recovery policy is explicit and does not silently classify the old attempt as “never happened.”

**Phase 1 disposition:** **Blocks Phase 1 inference/recovery types.** Stable attempt identity and retry disposition belong in the provider-neutral contract even if durable execution storage arrives later.

## R-04 — Provider-hosted side effect repeats after stream retry

**Triggering sequence**

1. Cerebro sends an inference request that enables a provider-hosted web/code/computer/MCP/server tool.
2. The provider performs an operation with side effects.
3. The response stream disconnects before Cerebro receives a trustworthy terminal completion/checkpoint.
4. Adapter or harness treats the stream failure as retryable and replays the whole inference request.
5. The provider performs the hosted operation again.

**Resulting incorrect state:** duplicate external effect with no Cerebro `ToolRuntime` record capable of deduplicating it.

**Severity:** Critical.

**Likelihood:** Low to Medium while provider-hosted tools are opt-in; higher if promoted to normal tools.

**Detectability:** Poor.

**Does the proposed architecture prevent it?** Partially. Provider normalization explicitly identifies hosted tools as retry barriers and recommends keeping them explicit extensions. The generic retry contract still needs a durable progress signal strong enough to enforce that recommendation.

**Missing invariant:** once an inference attempt may have caused provider-managed semantic/external progress, whole-request replay is forbidden unless the adapter can prove provider-level idempotency. `retryable HTTP/stream error` is not equivalent to `safe semantic replay`.

**Required test:** fake hosted-tool provider records a side effect, then drops the stream. Assert recovery does not issue a second inference request unless a fixture supplies a working idempotency key and verifies one provider-side effect.

**Phase 1 disposition:** **Can wait if Harness v1 Phase 1 does not enable provider-hosted side-effecting tools.** The error/attempt contract must still avoid implying all transient stream failures are replay-safe.

## R-05 — Native call ID/signature arrives late in stream

**Triggering sequence**

1. Tool-call arguments become syntactically complete before the provider block/step is finalized.
2. A naive runner sees the call and dispatches it.
3. The provider later emits native call correlation, signed thought/reasoning material, or other required replay state.
4. The process dies before that late material is durable.

**Resulting incorrect state:** the tool side effect exists, but a valid provider continuation cannot be reconstructed.

**Severity:** Critical.

**Likelihood:** Medium across rich native provider streams.

**Detectability:** Good on immediate continuation failure; poor if a fallback silently starts a fresh semantic request.

**Does the proposed architecture prevent it?** **Yes, if implemented literally.** Provider normalization requires `OutputItemCompleted` plus native `ProviderCallRef` and preceding required replay items to be durable before marking the checkpoint executable and dispatching tools.

**Missing invariant:** no new architecture needed; preserve the existing pre-tool replay checkpoint as a hard executable barrier rather than advisory sequencing.

**Required test:** stream complete tool JSON early, delay native call ID/signature until block completion, and place a kill point before the executable checkpoint. Assert tool execution count is zero. Repeat with kill after checkpoint and verify restart has all replay material.

**Phase 1 disposition:** **Blocks Phase 1.** The ordered item, completed-output, provider-ref and replay-requirement types must exist from the start.

## R-06 — Semantic retry repeats already-committed work

**Triggering sequence**

1. Attempt A commits one or more completed semantic output items or terminal tool outcomes.
2. A later error occurs, such as stream disconnect, timeout, context error, completion-policy failure, or persistence retry.
3. Recovery uses a generic “retry turn/request” path from an older checkpoint.
4. The provider repeats reasoning and emits a new tool call that is semantically equivalent but has a new canonical/provider call ID.
5. Tool-level exact-ID deduplication cannot recognize semantic equivalence and executes again.

**Resulting incorrect state:** repeated side effect despite every individual call ID appearing unique and internally consistent.

**Severity:** Critical.

**Likelihood:** Medium if recovery is implemented as generic retries.

**Detectability:** Poor.

**Does the proposed architecture prevent it?** Partially. Research strongly says retry layers must be typed and separate, but no explicit monotonic “semantic progress watermark” currently forbids rollback across committed effects.

**Missing invariant:** recovery is monotonic across durable semantic/effect boundaries. A retry may replay the same request only from a checkpoint whose subsequent effects are known not to have escaped. After committed tool/evidence progress, recovery continues from that progress or explicitly abandons the attempt at a fresh semantic boundary; it does not rewind and ask the model to rediscover already-executed work without carrying the prior result/uncertainty forward.

**Required test:** commit a tool success, inject a later retryable provider failure, then force recovery from the durable turn. Assert the previous tool result remains in canonical history and the executor is not called again merely because a fresh provider attempt emits equivalent work.

**Phase 1 disposition:** **Blocks Phase 1 error/retry semantics.** `retryable` alone is insufficient; the contract needs replay disposition distinct from transport retryability.

## R-07 — Turn event and `agent_turns` projection disagree

**Triggering sequence**

1. A reducer transition logically changes the turn from state/version S to S+1 and appends a durable semantic event.
2. The event append succeeds but the indexed `agent_turns` projection update fails, or the projection update succeeds but the event append fails.
3. Process dies before repair.
4. Restart chooses one representation as current without a defined authority/version check.

**Resulting incorrect state:** the reducer can repeat an already-applied effect, skip required work, or expose a status that cannot be reconstructed from the audit log.

**Severity:** Critical.

**Likelihood:** Medium unless writes are deliberately grouped in one SQLite transaction.

**Detectability:** Moderate; inconsistencies are queryable if versions are recorded, otherwise subtle.

**Does the proposed architecture prevent it?** No explicit rule. It describes `agent_turns` as current indexed projection and `turn_events` as reconstruction/audit log, but does not specify atomic transition writes or which is authoritative after divergence.

**Missing invariant:** every reducer state transition that changes executable meaning commits its semantic event(s), resulting projection version and next-effect eligibility atomically, or one representation is explicitly derivable from the other with a monotonic version/CAS rule. A worker may act only from a validated current version.

**Required test:** fault injection at every write boundary around `event append > projection update > commit`. Restart after each injected crash. Assert all surviving states reconstruct to exactly one next reducer action and never redispatch a committed effect.

**Phase 1 disposition:** **Can wait until durable `AgentTurn` storage is introduced**, but blocks that phase and should be frozen in #206 now.

## R-08 — Final shared message and durable turn completion split

**Triggering sequence A**

1. Harness has accepted final assistant output.
2. Final channel message row is inserted.
3. Process dies before `AgentTurn` is marked completed.
4. Startup recovery sees a non-terminal turn and resumes it.
5. A second final message is appended.

**Triggering sequence B**

1. `AgentTurn` is marked completed.
2. Process dies before final channel message insertion.
3. Recovery trusts terminal status and does nothing.

**Resulting incorrect state:** duplicate visible answer in A; permanently missing answer in B. Both violate current completion-ordered product semantics.

**Severity:** Critical.

**Likelihood:** Medium unless explicitly transactional/idempotent.

**Detectability:** Good for duplicate/missing chat, but only after user-visible corruption.

**Does the proposed architecture prevent it?** Partially. The acceptance scenario says the final response is atomically appended and the `AgentTurn` becomes completed, but the actual invariant/transaction identity is not specified. Phase 0 only had one durable object, so it did not face this dual-write problem.

**Missing invariant:** one durable finalization transaction/idempotency key must bind the accepted final output, final message identity and terminal turn state. Recovery can retry final publication without creating a second channel row, and a turn cannot be terminal-success without a resolvable committed final product result (except deliberate silent/PASS outcomes).

**Required test:** kill after each statement in finalization. Restart repeatedly. Assert exactly one final message for ordinary completion, zero for valid topic PASS/silent completion, fail-closed DM behavior, and a terminal `AgentTurn` consistent with the message outcome.

**Phase 1 disposition:** **Can wait until durable AgentTurn/finalization implementation**, but blocks that phase.

## R-09 — Cancellation races with a completing tool

**Triggering sequence**

1. Tool call is in flight.
2. User/parent requests cancellation.
3. Tool finishes successfully at nearly the same time.
4. Cancellation path and tool-completion path race to write terminal call/turn states.
5. Depending on scheduling, success is overwritten by cancelled/timeout, or success triggers another inference step after the turn was durably cancelled.

**Resulting incorrect state:** durable history lies about whether the effect happened, or cancelled work continues autonomously.

**Severity:** High; Critical for destructive tools if “cancelled” falsely implies no side effect.

**Likelihood:** High over long-lived use because cancellation is specifically likely during slow tools.

**Detectability:** Moderate.

**Does the proposed architecture prevent it?** Partially. Cancellation is modeled as a lifecycle and every admitted call should get one terminal result, but terminal arbitration/precedence is not specified.

**Missing invariant:** cancellation is a request/control fact, not retroactive proof that an external effect did not complete. Tool terminalization is single-assignment/monotonic. Whichever durable fact wins must preserve real effect uncertainty: successful committed result remains success; post-dispatch cancellation without authoritative outcome becomes uncertain, not falsely “cancelled.” Once turn cancellation is terminal, no new provider/tool step may be admitted even if an in-flight completion arrives later.

**Required test:** use barriers to enumerate cancellation before dispatch, during remote execution, after remote success/before result commit, after result commit/before next inference, and simultaneous terminal writes. Assert one truthful terminal call outcome and no post-cancel autonomous step.

**Phase 1 disposition:** **Blocks the execution/result state model in Phase 1**, even if cancellation implementation is later.

## R-10 — Cancellation reports clean stop although a side effect escaped

**Triggering sequence**

1. External tool request has left the process.
2. Cancellation or timeout fires and local task/subprocess is aborted.
3. Remote service completes the request anyway.
4. Harness writes `cancelled` or `timeout` as if the effect did not happen.
5. User or recovery logic retries manually/automatically.

**Resulting incorrect state:** hidden external mutation plus misleading durable status, followed by duplicate action.

**Severity:** Critical.

**Likelihood:** Medium for network tools; lower for strongly killable local child processes.

**Detectability:** Poor.

**Does the proposed architecture prevent it?** No. Current candidate `ToolResult.status` values do not distinguish “execution was prevented” from “caller stopped waiting after dispatch.”

**Missing invariant:** terminal status must separate pre-dispatch cancellation/timeout from post-dispatch unknown outcome unless executor protocol guarantees cancellation acknowledgement. “Cancelled” may mean no side effect only when the executor proves the operation never committed.

**Required test:** fake remote endpoint ignores client cancellation and commits after the caller abandons. Assert Cerebro records uncertainty/reconciliation-required state and never automatically replays it.

**Phase 1 disposition:** **Blocks Phase 1 tool outcome taxonomy.**

## R-11 — Immutable StepSnapshot preserves permission that was urgently revoked

**Triggering sequence**

1. StepSnapshot S freezes permission P allowing destructive tool T.
2. Provider spends tens of seconds producing a call to T.
3. Administrator/user revokes P because credentials/workspace are compromised or the operation is no longer allowed.
4. Harness follows the “execute against the same snapshot” rule literally and authorizes T using stale P.
5. T executes after revocation.

**Resulting incorrect state:** a security/authorization revocation is ignored specifically because snapshot immutability was treated as stronger than revocation.

**Severity:** Critical for privileged tools.

**Likelihood:** Low to Medium, but this is a safety-boundary failure.

**Detectability:** Good in audit after the fact; too late to prevent effect.

**Does the proposed architecture prevent it?** No; in fact the current wording can cause it. Snapshot stability correctly prevents silent reinterpretation, but ordinary configuration immutability and emergency revocation are different semantics.

**Missing invariant:** StepSnapshot freezes the granted policy view for reproducibility, but execution must also validate a monotonic revocation/kill epoch for security-critical grants. Changes that merely add tools do not alter S; revocation of authority can invalidate S and must fail closed before side-effect dispatch. The old call becomes denied/stale under the original identity rather than re-bound to new policy.

**Required test:** freeze a destructive-tool snapshot, revoke permission after provider request starts but before tool dispatch, then finish the streamed call. Assert the original call is not executed and gets one explicit denied/stale terminal outcome.

**Phase 1 disposition:** **Can wait until StepSnapshot/ToolPolicy implementation**, but blocks privileged tool execution and should be frozen as an invariant now.

## R-12 — Snapshot says one tool binding; mutable executor has changed underneath it

**Triggering sequence**

1. Snapshot records tool definition/binding generation G1.
2. MCP server disconnects/reconnects, extension is upgraded, credentials rotate, or a mutable client object is repointed to generation G2.
3. Provider emits a call based on G1’s schema/semantics.
4. `ToolRuntime` follows a live executor reference that now invokes G2.

**Resulting incorrect state:** a call is executed by a tool implementation different from the one advertised, despite the snapshot containing a nominal version.

**Severity:** High.

**Likelihood:** Medium with dynamic MCP catalogs.

**Detectability:** Poor unless execution records concrete binding generation.

**Does the proposed architecture prevent it?** Partially. It explicitly says old binding unavailable should yield `unavailable/stale binding` rather than reinterpret through a new catalog. That only works if runtime verifies the concrete binding generation instead of storing a pointer to mutable routing state.

**Missing invariant:** the executable binding used at dispatch must prove it is the same generation/identity captured by the snapshot; otherwise fail closed. A snapshot version is evidence only if the executor validates it.

**Required test:** snapshot G1, replace/reconnect the MCP server as G2 with the same tool name but changed behavior, then execute the old call. Assert G2 is not invoked; result is stale/unavailable unless G1 is still explicitly addressable.

**Phase 1 disposition:** **Can wait until ToolBinding/StepSnapshot implementation**, but blocks that phase.

## R-13 — Two agents mutate the same git/workspace state concurrently

**Triggering sequence**

1. Agent A and Agent B derive snapshots/context from git tree H0 or overlapping files.
2. Both independently plan edits/tests/commits.
3. A changes files/index/HEAD to H1.
4. B executes commands based on H0 assumptions in the same working tree and may stage/commit A’s files, overwrite edits, or run tests against mixed state.
5. Both model histories claim their own intended work completed.

**Resulting incorrect state:** lost edits, commits containing another agent’s changes, incorrect test evidence, branch movement races, or a model reporting success for a state it never actually validated.

**Severity:** Critical for repository mutation; High for ordinary shared files.

**Likelihood:** High in the intended Slack-like multi-agent product unless workspaces are isolated or serialized.

**Detectability:** Moderate; git may expose conflicts, but clean-looking mixed commits are possible.

**Does the proposed architecture prevent it?** No. StepSnapshot freezes the *view*, not the mutable filesystem. Tool annotations such as `parallel-safe` are per tool and do not establish cross-turn workspace serialization. Current lease commit guard is explicitly a workflow guard, not a security boundary.

**Missing invariant:** side-effecting workspace/git operations require either isolated workspaces or an authoritative resource-ownership/version precondition that is checked at execution and final verification. A model’s snapshot of H0 cannot authorize a write/commit against silently changed H1. Git HEAD/index mutations need a stronger conflict key than provider-level concurrency.

**Required test:** run two agent turns against one repo from the same starting commit, interleave edits/stage/commit/test barriers, and prove Cerebro either serializes/conflict-fails one writer or isolates their work. Assert no commit can include unowned peer changes and completion evidence is tied to the exact resulting tree.

**Phase 1 disposition:** **Can wait while Phase 1 is behavior-preserving provider adaptation**, but blocks enabling concurrent Harness-owned write tools in a shared workspace.

## R-14 — “Parallel-safe” tools conflict on a hidden shared resource

**Triggering sequence**

1. Provider emits N parallel tool calls.
2. Tool definitions are marked parallel-safe at the coarse tool level.
3. Two calls target the same file, git index, database row, remote object, or rate-limited account.
4. Runtime executes them concurrently because the annotation says the tool class is safe.

**Resulting incorrect state:** lost update, nondeterministic result ordering, corrupted shared state, or false verification evidence.

**Severity:** High.

**Likelihood:** Medium if parallel execution is enabled.

**Detectability:** Moderate.

**Does the proposed architecture prevent it?** No explicit resource-level conflict rule. It supports parallel tools and annotations but does not define dynamic conflict keys.

**Missing invariant:** parallelism is opt-in and only permitted when both the tool binding and the concrete calls are non-conflicting under an executor-defined resource policy. A boolean annotation cannot by itself prove two parameterized mutations commute.

**Required test:** two calls to the same nominally parallel-capable tool target one mutable resource; assert serialized/conflict behavior. A second fixture targets independent resources and may run concurrently.

**Phase 1 disposition:** **Can wait.** Current Phase 0 behavior executes multiple tool calls sequentially; preserve that until a resource-safe parallelism contract exists.

## R-15 — Lease expires, replacement starts, stale worker continues

**Triggering sequence**

1. Worker A acquires a durable lease/ownership record and starts a slow provider/tool step.
2. A pauses due to GC, event-loop stall, partition, machine sleep, or renewal failure.
3. Lease TTL expires.
4. Worker B acquires the same resource/turn and begins execution.
5. A resumes with still-live local state and continues issuing writes or external effects.

**Resulting incorrect state:** split-brain execution of one turn/workspace. Both workers can be “correct” according to the lease state they observed at different times.

**Severity:** Critical.

**Likelihood:** Medium in any multi-process/restart deployment.

**Detectability:** Poor unless every write/dispatch records an ownership generation.

**Does the proposed architecture prevent it?** No explicit fencing invariant. Current Cerebro leases have holder/expiry but no fencing token; process-local semaphores and cancellation do not help after a partition.

**Missing invariant:** ownership acquisition advances a monotonic execution epoch/version, and every durable transition plus external-effect admission verifies that epoch is still current. A stale epoch may read/audit but cannot commit executable state, final messages, or new dispatches. Where an external system accepts fencing/idempotency tokens, propagate them.

**Required test:** freeze A beyond TTL, let B take over and advance the epoch, then resume A. Assert every attempted transition/dispatch/finalization from A is rejected as stale and cannot change current state.

**Phase 1 disposition:** **Can wait until durable worker ownership is implemented**, but blocks multi-worker/restart recovery and should be a frozen invariant in #206.

## R-16 — Provider semaphore resets on process death

**Triggering sequence**

1. Process A has K in-flight provider requests and has consumed its local `asyncio.Semaphore` capacity.
2. A dies/restarts while providers may still be computing/streaming remotely.
3. New process constructs a fresh semaphore at full capacity.
4. It immediately starts K more requests, possibly including recovery of old turns.

**Resulting incorrect state:** temporary provider concurrency can exceed configured limits, causing 429s, cost spikes, or amplification of duplicate attempts.

**Severity:** Medium; High if concurrency limit is a hard spend/safety control.

**Likelihood:** Medium on restart.

**Detectability:** Good from provider metrics if instrumented.

**Does the proposed architecture prevent it?** No, but this is mostly capacity control rather than correctness. Phase 0 confirms current semaphores are process-local.

**Missing invariant:** never use the in-memory semaphore as proof of exclusive turn/effect ownership. If concurrency must be a hard cross-process limit, back it with durable/distributed admission or accept/document bounded restart oversubscription. Turn fencing must independently prevent duplicate semantic execution.

**Required test:** simulate restart with fake remotely lingering requests. Assert turn correctness is preserved regardless of semaphore reset; if a hard global capacity is promised, assert the configured maximum is not exceeded across workers.

**Phase 1 disposition:** **Can wait** for single-process v1 if limits are explicitly best-effort throughput controls, not correctness/budget barriers.

## R-17 — Compaction races active provider replay scope

**Triggering sequence**

1. Context manager reads history and decides replay scope X is closed/trimmable.
2. Concurrently, another reducer transition or late finalized output extends/activates the provider continuation scope using items in X.
3. Compactor summarizes/deletes/reorders the old exact replay material.
4. Next provider request needs it for a valid continuation.

**Resulting incorrect state:** provider continuation fails or silently restarts with reduced fidelity; an already-executed tool result may become impossible to return in the required native sequence.

**Severity:** High to Critical depending provider/tool state.

**Likelihood:** Low if one reducer serializes a turn; Medium if compaction can run asynchronously.

**Detectability:** Good on provider rejection; poor on silent fidelity degradation.

**Does the proposed architecture prevent it?** Conceptually yes: required replay items are pinned while active. The missing piece is transactional/versioned compaction against the same history/replay version.

**Missing invariant:** compaction commits only if the history/replay-scope version it analyzed is still current. It cannot trim any item required by an open native continuation, including exact call/result ordering the adapter marks replay-required. Failed/version-stale compaction leaves the pre-compaction checkpoint intact.

**Required test:** pause compaction after planning its trim set, commit a new continuation item that extends the replay scope, then resume compaction. Assert compare/version failure and preservation of all required replay material.

**Phase 1 disposition:** **Can wait until ContextManager compaction**, while replay requirement/scope metadata must exist from Phase 1.

## R-18 — Provider/model changes while native continuation is active

**Triggering sequence**

1. Provider/model A emits tool/reasoning state whose exact opaque/native replay is still required.
2. Configuration, failover, user action, model discovery, or retry policy selects provider/model B.
3. Harness attempts to continue the same native cycle using portable semantic history only or accidentally forwards A’s opaque state to B.

**Resulting incorrect state:** invalid request, hidden reasoning leakage across providers, loss of required correlation, or a model acting on a tool result without the native context that requested it.

**Severity:** Critical for leakage/correlation; High otherwise.

**Likelihood:** Medium once runtime switching/failover exists.

**Detectability:** Good for explicit invalid requests; poor for semantic drift/leakage.

**Does the proposed architecture prevent it?** **Yes conceptually.** Provider normalization explicitly requires finishing the original continuation or abandoning it and starting a fresh semantic inference boundary; opaque replay state is non-portable.

**Missing invariant:** preserve that rule in executable transition validation. A provider/model switch is rejected while a required continuation is open unless the adapter declares compatibility, or it atomically records explicit abandonment before constructing a fresh step.

**Required test:** open a tool/reasoning continuation on A, request switch to B before tool result continuation, and assert no A opaque item is serialized to B. Verify either original-A completion or durable abandonment plus fresh-B semantic request.

**Phase 1 disposition:** **Blocks Phase 1 provider/replay model.**

## R-19 — Parent dies while child agent remains active

**Triggering sequence**

1. Parent turn P durably admits delegation call D and starts child turn C.
2. C performs work or side effects independently.
3. Parent worker dies before recording/observing C’s lifecycle/result.
4. Parent recovery replays D and creates C2, or marks P failed/cancelled while C continues orphaned.
5. C and C2 may both mutate state; completed C result may never be consumed.

**Resulting incorrect state:** duplicate delegated work, orphan side effects, leaked budgets, or parent completion inconsistent with child state.

**Severity:** High to Critical for side-effecting children.

**Likelihood:** Medium once durable/background delegation exists.

**Detectability:** Moderate if lineage is queryable.

**Does the proposed architecture prevent it?** Partially. Research recommends durable parent/root lineage and child runs, but does not define unique delegation admission, parent/child terminal coupling, or takeover semantics.

**Missing invariant:** a delegation call maps idempotently to one durable child execution identity. Parent recovery discovers that child rather than creating another. Parent cancellation/terminalization has an explicit policy for active descendants, and child completion cannot autonomously resume a stale parent owner.

**Required test:** kill parent immediately after child creation, during child execution, and after child completion/before parent consumes result. Restart parent and assert exactly one child identity, no duplicate child dispatch, and deterministic cancellation/result propagation.

**Phase 1 disposition:** **Can wait if delegated/background agents are out of Phase 1.** Blocks the first child-agent implementation.

## R-20 — Usage/audit persistence failure is treated as non-fatal even when it enforces a hard limit

**Triggering sequence**

1. Provider call consumes tokens/money or tool action requires an auditable budget/security event.
2. Usage/audit write fails or is dropped.
3. Runtime follows current best-effort accounting behavior and continues.
4. Restart/recovery sees lower durable usage or missing authorization/effect evidence.
5. More work is admitted beyond the intended hard budget, or audit cannot explain a destructive action.

**Resulting incorrect state:** budget overrun or missing correctness-critical audit facts while the turn itself appears successful.

**Severity:** High if budgets/audit are enforcement inputs; Medium if strictly telemetry.

**Likelihood:** Low to Medium.

**Detectability:** Poor for missing rows unless reconciled against provider bills/remote logs.

**Does the proposed architecture prevent it?** No explicit separation. Phase 0 intentionally makes usage persistence failure non-fatal, which is reasonable for telemetry but unsafe if Harness v1 later treats the same ledger as a hard admission control.

**Missing invariant:** classify persistence by semantics. Telemetry may be best effort; any record used for authorization, hard budget admission, idempotency, replay or effect reconstruction must commit at the corresponding durable boundary. Hard provider budget should reserve/admit from durable state before dispatch and reconcile actual usage afterward.

**Required test:** inject database failure on usage/audit writes while a hard limit is one request away. Assert either the request is not admitted without durable reservation or recovery cannot exceed the configured hard budget. Separate fixture proves telemetry-only failure does not crash the turn.

**Phase 1 disposition:** **Can wait if Phase 1 preserves current telemetry-only usage semantics.** Blocks any claim that budgets are hard execution guarantees.

## R-21 — Schema migration occurs while an old worker still runs

**Triggering sequence**

1. Worker A runs old Harness code against schema/version N.
2. New worker B starts, executes migration N+1, and begins writing new `AgentTurn`/event/status/payload semantics.
3. A remains alive and continues reading/writing the same SQLite database.
4. A either cannot understand new values or writes an old-shaped transition over state B already advanced.

**Resulting incorrect state:** crashes are the best case. Worse cases are silent projection rollback, missing new fields/defaults that change semantics, old reducer execution against new event payloads, or stale worker finalization after migration.

**Severity:** Critical once durable execution state controls side effects.

**Likelihood:** Medium during rolling/restart deploys or stale processes; current health endpoint already recognizes code-on-disk vs running-code drift as a real operational concern.

**Detectability:** Moderate. Schema/version health is visible, but semantic corruption may surface later.

**Does the proposed architecture prevent it?** No explicit worker/schema compatibility gate. Current `db.migrate()` correctly makes each SQL migration atomic and starts the local runtime only after migration, but it does not stop an already-running old process on the same DB.

**Missing invariant:** a worker may execute/transition durable turns only when its supported harness schema/event versions are compatible with the database epoch. A migration that changes executable semantics must either drain/fence old workers before activation or maintain explicit read/write compatibility. Ownership epoch checks must reject old workers after activation.

**Required test:** keep old worker A alive, migrate/start B, then let A attempt to renew ownership, append an event, dispatch a tool, and finalize a message. Assert every executable mutation is rejected or proven compatible. Also crash migration mid-file and verify current per-migration transaction leaves either N or N+1, never partial N+1.

**Phase 1 disposition:** **Can wait until the first Harness schema migration**, but blocks that migration/deployment model and should be decided before durable-turn tables ship.

## R-22 — Duplicate wake creates duplicate AgentTurns for one trigger

**Triggering sequence**

1. Human/channel/task event T should wake agent A once.
2. Hub delivery, poller restart/cursor race, service retry, API retry, or process restart presents T twice.
3. TurnCoordinator creates two durable `AgentTurn`s because each wake is locally valid.
4. Both infer and possibly execute tools, then both append final responses.

**Resulting incorrect state:** duplicate agent work, duplicate side effects and duplicate channel responses even though each individual turn is internally correct.

**Severity:** Critical for side-effecting turns; High for chat-only turns.

**Likelihood:** Medium. At-least-once delivery/recovery is easier to guarantee than exactly-once delivery, and Phase 0 already documents a poller cursor initialization edge case.

**Detectability:** Good for duplicate chat, poor for duplicated hidden/tool work.

**Does the proposed architecture prevent it?** No explicit wake idempotency key/uniqueness rule. A durable `AgentTurn` id alone prevents duplicate processing of *that id*, not creation of two ids for the same causal wake.

**Missing invariant:** every wake has a stable causal admission key scoped to the agent and trigger semantics. Turn creation is idempotent under repeated delivery. Intentional repeated wakes (for example periodic polling at different epochs) must have distinct keys.

**Required test:** deliver the same trigger concurrently and again after simulated restart. Assert one AgentTurn and one final response/effect set. Deliver two intentionally distinct scheduled/poll epochs and assert two turns.

**Phase 1 disposition:** **Can wait until durable TurnCoordinator creation**, but blocks robust restart/at-least-once wake handling.

## Cross-risk observations

### “Exactly once” must be scoped

There are three separate guarantees:

1. **Durable Cerebro transition exactly once:** achievable with a single DB transaction/CAS/fenced version.
2. **External effect exactly once:** not generally achievable after ambiguous network/process failure unless the external executor offers idempotency or reconciliation. The safe generic behavior is at-most-once automatic dispatch after uncertainty, not blind retry.
3. **User-visible final publication exactly once:** achievable inside Cerebro with an idempotent message identity/finalization transaction while preserving completion ordering.

Conflating these guarantees is itself a failure mode.

### Snapshot immutability is necessary but not sufficient

`StepSnapshot` correctly freezes what the model saw. It does not freeze the external world. Tool binding generation, permission revocation epoch, workspace content/version and worker ownership can all change after inference. Execution must prove the still-relevant preconditions without silently substituting newer semantics.

### A reducer is only crash-safe if effects have durable admission boundaries

“Load durable state > choose operation > persist effect > reload” is directionally strong. The dangerous part is any operation that performs an external effect before its durable admission is uniquely owned, or whose remote outcome becomes ambiguous before a terminal result is committed. Re-entry must classify those states instead of merely calling the operation again.

## Phase 1 blockers to feed issue #206

Even under the narrow initial Phase 1 scope, the following must be represented correctly before canonical contracts freeze:

- R-01/R-10: tool outcome model must be able to represent post-dispatch uncertainty; `cancelled`/`timeout` cannot always mean “no effect.”
- R-03: provider inference needs stable attempt identity/progress and retry disposition.
- R-05: finalized ordered output plus durable native references/replay material before tool executability.
- R-06: retryability must be separate from semantic replay safety.
- R-09: single-assignment/monotonic terminal outcome semantics.
- R-18: provider/model switch cannot carry active opaque continuation state across an incompatible boundary.

The other risks can be implemented in later phases only if issue #206 freezes their invariants now and no earlier schema/API choice makes them impossible.
