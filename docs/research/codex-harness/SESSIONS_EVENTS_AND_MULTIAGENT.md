# Codex Sessions, Events, and Multi-Agent Architecture

**Status:** Initial confirmed map of session protocol, durable thread replay, turn lifecycle, fork/resume semantics, and V1/V2 multi-agent control.

**Pinned upstream:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

No Codex implementation code is copied into Cerebro by this document. Findings are currently **conceptual inspiration only**.

## Main conclusion

Codex separates four things that are easy to collapse in a smaller harness:

1. a **thread** as durable conversation/task identity;
2. a live **session/runtime** that owns active execution and queues;
3. a **turn** as one causally traceable unit of work inside the thread;
4. an **event/rollout log** from which model-visible state and user-visible lifecycle can be reconstructed.

Multi-agent work is built on those same primitives. A sub-agent is a real thread with parent/root lineage, persisted metadata and its own turn lifecycle. Collaboration tools send typed inter-agent communications or manipulate that thread's execution state; they are not merely nested provider calls hidden inside a parent inference.

For Cerebro, this strongly supports making tasks/agents/turns/messages durable Cerebro-owned entities and treating provider inference workers as replaceable executors over that state.

## 1. The core protocol is submission queue > event queue

`codex-rs/protocol/src/protocol.rs` explicitly describes an asynchronous SQ/EQ protocol.

A `Submission` carries:

- a unique submission id used to correlate events;
- a typed `Op`;
- optional W3C trace context;
- optional `parent_turn_id` and `root_turn_id` for causal inter-agent submissions.

The session submission loop receives these operations and dispatches typed handlers such as turn input, interrupt, approvals, inter-agent communication, compaction, rollback and shutdown.

Outbound events use the corresponding typed `Event` / `EventMsg` surface. Turn and item lifecycle is represented explicitly rather than inferred only from assistant text.

**Cerebro implication:** use a command/event boundary around an agent runtime. UI/API actions should submit typed commands to a task/thread actor or coordinator; model/tool/runtime activity should emit typed events with stable IDs and causal lineage.

Upstream:
- `codex-rs/protocol/src/protocol.rs`
- `codex-rs/core/src/session/handlers.rs`

## 2. Threads are durable identity; live runtimes are replaceable

`ThreadManager` owns currently live `CodexThread` instances in memory, but a separate `ThreadStore` owns persisted thread state/history.

Thread creation metadata includes stable identity and lineage such as:

- `session_id` shared by a root thread and its sub-agents;
- `thread_id`;
- `forked_from_id`;
- `parent_thread_id`;
- `SessionSource` / thread source;
- persisted base instructions;
- dynamic tools and capability roots;
- multi-agent version;
- history mode and history-base information;
- initial context-window identity;
- cwd/model-provider/memory-mode persistence metadata.

A thread can therefore be reopened into a new runtime from persisted history rather than requiring the original in-memory worker to survive.

**Cerebro implication:** make durable `AgentThread`/`Task` identity independent of WebSocket/process/provider-client lifetime. A worker should acquire a task/thread, reconstruct its execution view, work, checkpoint and release it.

Upstream:
- `codex-rs/core/src/thread_manager.rs`
- `codex-rs/thread-store/src/types.rs`

## 3. Persisted rollout is replayable state, not only a chat transcript

The persisted history is a sequence of `RolloutItem`s. Reconstruction does more than concatenate messages.

`Session::reconstruct_history_from_rollout(...)` derives:

- rebuilt model-visible response history;
- previous-turn model/compaction/realtime settings;
- latest surviving reference `TurnContextItem`;
- replayed World State baseline;
- context-window number and window identities.

It understands compaction replacement-history checkpoints, turn boundaries, interruption, rollback, inter-agent communication and old rollout compatibility.

The reconstruction logic scans newest-to-oldest to find the newest sufficient checkpoint/metadata, then replays the surviving suffix forward to preserve exact semantics.

**Cerebro implication:** durable event history should distinguish raw audit data from the canonical state reducer that constructs the next model request. If Cerebro persists only rendered chat text, it will lose the ability to deterministically restore tool/context/task state after compaction, rollback or worker replacement.

Upstream:
- `codex-rs/core/src/session/rollout_reconstruction.rs`
- `codex-rs/history/*`
- `codex-rs/thread-store/*`

## 4. Stored turn status is a first-class projection

The thread store exposes durable turn-level concepts including statuses:

- `Completed`;
- `Interrupted`;
- `Failed`;
- `InProgress`.

Failed turns can retain structured Codex error information in addition to a user-visible message.

This is a useful distinction from the raw event stream: the store can project current thread/turn state while the rollout remains the replay/audit source.

**Cerebro implication:** maintain both an append-only/auditable event stream and indexed projections for current task/turn status. Do not require every UI read to replay an entire conversation, and do not make the projection the only durable truth.

Upstream:
- `codex-rs/thread-store/src/types.rs`

## 5. Rollback is modeled as a durable history transition

Thread rollback is refused while a turn is active. Before applying rollback, the session flushes persistence, reloads stored history and runs rollout reconstruction with an appended `ThreadRolledBack` event.

After rebuilding the in-memory state it persists the rollback marker itself and recomputes token usage. Reconstruction interprets rollback as dropping the newest N surviving real user-turn segments.

This means rollback is not destructive ad-hoc mutation of an in-memory message vector; it is represented as a replayable state transition.

**Cerebro implication:** prefer durable corrective events/checkpoints for operations such as rollback, compaction, cancellation and ownership transfer. Destructive database edits should be exceptional because they make audit/recovery substantially harder.

Upstream:
- `codex-rs/core/src/session/handlers.rs`
- `codex-rs/core/src/session/rollout_reconstruction.rs`

## 6. Fork and resume are distinct state operations

`ThreadManager` supports resume from persisted rollout/history and also explicit fork snapshots.

Confirmed fork modes include:

- truncate before a chosen user-message boundary;
- snapshot the current persisted state as interrupted;
- multi-agent full-history forks;
- V2 multi-agent forks of the last N turns.

The interrupted fork mode appends the same turn-aborted marker a real interrupt would use when the persisted snapshot ends mid-turn. Full-history and truncated child forks preserve different context-baseline behavior because a truncated prompt can no longer safely diff against all parent state.

Paginated history also has explicit `ForkBoundary`/`PreparedFork` concepts and a source reservation so the source cannot be deleted before the child's history reference is durable.

**Cerebro implication:** define `resume` and `fork` separately. Resume keeps logical identity; fork creates a new identity from a frozen causal snapshot. A fork should record source task/thread, boundary and inherited context policy.

Upstream:
- `codex-rs/core/src/thread_manager.rs`
- `codex-rs/core/src/agent/control/spawn.rs`
- `codex-rs/thread-store/src/types.rs`

## 7. Inter-agent communication has delivery semantics separate from text

Inter-agent messages are typed `InterAgentCommunication` objects and can carry a `trigger_turn` bit.

On receive, the session first enqueues the communication into its mailbox. If it should trigger work, or an outstanding durable sleep needs pending work, the shared pending-work scheduler may start a turn.

This creates an important semantic difference:

```text
message
  > enqueue/deliver information
  > does not necessarily create a new inference turn

follow-up task / triggering communication
  > enqueue information
  > start a turn if the target is idle
```

V2 exposes this split directly as `send_message` versus `followup_task`.

**Cerebro implication:** Slack-like agent collaboration should not map every message to a provider call. Messages should be durable communication objects; scheduling policy decides whether a message wakes/starts an agent turn.

Upstream:
- `codex-rs/core/src/session/handlers.rs`
- `codex-rs/core/src/agent/control.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_spec.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2.rs`

## 8. One root-scoped control plane owns the agent tree

`AgentControl` is intended to exist once per root thread/session tree and is cloned/shared by the root and all spawned sub-agents.

It owns root-scoped state including:

- a common `session_id`;
- the agent registry/path mapping;
- V2 residency state;
- execution limiter;
- rollout budget;
- root service tier;
- a weak link to global `ThreadManagerState`.

This keeps multi-agent identity/allocation scoped to one collaborative task tree rather than making every live thread globally addressable without ownership boundaries.

**Cerebro implication:** model a collaboration/workspace root or task tree with its own agent registry, budgets and permissions. Global infrastructure can host many trees, but cross-tree addressing should be explicit rather than accidental.

Upstream:
- `codex-rs/core/src/agent/control.rs`

## 9. Child agents inherit the live turn, not stale startup config

The V1 and V2 spawn handlers intentionally construct child configuration from the **effective live parent turn**.

Confirmed inherited/runtime-refreshed properties include:

- current provider and model;
- reasoning settings;
- developer/base instructions with provenance rules;
- approval policy and approval reviewer;
- cwd;
- permission profile/sandbox-relevant state;
- current environment selections from the request's `StepContext`;
- parent thread, parent turn and root turn lineage;
- service tier when supported.

Optional agent-role and model/reasoning overrides are applied and validated after the live base is constructed.

The source explicitly warns that cloning stale config can send a child out with the wrong provider or runtime policy.

**Cerebro implication:** spawning an agent should snapshot the parent's current effective execution contract. Provider choice, workspace/permissions and instruction state must be explicit child-spawn inputs or inherited from a versioned turn snapshot, not rediscovered from mutable global config.

Upstream:
- `codex-rs/core/src/tools/handlers/multi_agents.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_common.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/spawn.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs`

## 10. Multi-agent lineage is explicit and causal

Spawn records child metadata including:

- parent thread ID;
- parent turn ID;
- root turn ID;
- spawn depth;
- agent path/task name;
- optional role/nickname;
- fork mode/source when applicable.

Submissions used for inter-agent work also carry parent/root turn IDs. This gives telemetry, UI and recovery code enough causal information to associate child work with the root request that caused it.

V2 task names form canonical `AgentPath`s that can be resolved relative to the current agent, while V1 primarily exposes opaque thread IDs to the model.

**Cerebro implication:** every delegated task should record `parent_task_id`/`parent_turn_id` and `root_task_id` (or equivalent). This enables a Slack-like UI to show one causal tree, lets budgets aggregate upward, and makes cancellation/recovery understandable.

Upstream:
- `codex-rs/protocol/src/protocol.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_common.rs`
- V1/V2 spawn handlers

## 11. Agent existence, residency and active execution are different states

Codex does not require every known V2 agent to remain fully live in memory.

Confirmed behavior includes:

- persisted V2 agent identities can be restored without reopening their runtimes;
- an evicted/closed V2 child can be reloaded from stored model context;
- parent ownership and persisted parent lineage are validated before owner-driven child resume;
- the child resumes with stored model/provider/reasoning information plus current parent runtime permission/cwd policy where appropriate;
- execution concurrency is separately limited for V2 sub-agent turns.

`AgentExecutionLimiter` tracks active sub-agent execution and returns `AgentLimitReached` when no slot is available; the guard releases capacity when the executing turn ends.

**Cerebro implication:** separate:

- agent/task identity exists;
- runtime is resident/loaded;
- turn is queued;
- turn is actively consuming provider/tool resources.

This is particularly important for a collaborative UI where many agents may exist but only a bounded number should execute simultaneously.

Upstream:
- `codex-rs/core/src/agent/control.rs`
- `codex-rs/core/src/agent/control/spawn.rs`
- `codex-rs/core/src/agent/control/execution.rs`

## 12. V1 and V2 reveal useful API evolution

The two multi-agent surfaces show an architectural shift rather than just renamed tools.

### V1

- primarily identifies agents by thread id;
- `spawn_agent` can optionally full-fork context;
- `send_input` can either queue input or interrupt immediately;
- `wait_agent` waits for selected agents to reach final status;
- explicit `resume_agent` / `close_agent` management.

### V2

- gives agents canonical task names/paths;
- spawn requires `task_name` and defaults `fork_turns` to all, with `none` or last-N supported;
- `send_message` is non-triggering communication;
- `followup_task` explicitly means message + trigger work;
- `wait_agent` waits for mailbox/activity rather than merely polling final status;
- `list_agents` exposes the live tree;
- `interrupt_agent` stops current execution while preserving agent availability;
- persisted identities/runtimes support residency and reload semantics.

**Cerebro implication:** V2's distinction between durable agent identity, mailbox communication and scheduled work is closer to Cerebro's intended collaborative product than a spawn/wait-only sub-agent API.

Upstream:
- `codex-rs/core/src/tools/handlers/multi_agents_spec.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs`
- `codex-rs/core/src/agent/control/*`

## 13. Multi-agent lifecycle is surfaced as ordinary turn items/events

Spawn and other collaboration operations emit structured `CollabAgentToolCallItem` and `SubAgentActivityItem` lifecycle, including sender/receiver identity, status and selected metadata. AgentControl can emit item-started/item-completed events on a parent thread for sub-agent activity.

This allows the UI/event consumers to observe delegation using the same item lifecycle machinery as other agent actions rather than inventing a hidden side channel.

**Cerebro implication:** represent delegation, agent messages, task start/stop and child completion as first-class events/messages in the same workspace event model used by the UI. Provider-specific stream events can remain adapter-internal unless promoted into a stable Cerebro event.

Upstream:
- V1/V2 multi-agent handlers
- `codex-rs/core/src/agent/control.rs`
- `codex-rs/protocol/src/items.rs`

## 14. Candidate Cerebro session/task core

A minimal model-agnostic architecture suggested by these findings is:

```text
Workspace / RootTask
  shared budgets + policy + agent registry

AgentThread
  durable identity
  parent/root lineage
  model/provider preference
  mailbox
  current projection/status

Turn
  stable turn id
  parent/root causal ids
  request snapshot
  queued | running | completed | interrupted | failed

EventLog
  append-only task/turn/tool/message/context events
  checkpoints/compaction/rollback markers

StateReducer
  current thread projection
  next model-visible history/context snapshot

WorkerLease
  load/reconstruct thread
  acquire execution capacity
  run provider/tool loop
  checkpoint
  release/suspend/recover
```

This fits Cerebro's intended direction better than binding a long-lived agent object directly to one provider SDK session.

## Open questions carried forward

- exact event persistence filtering: which client/UI events become rollout items versus transient stream events;
- local thread-store live-writer durability, retry and compression guarantees;
- V2 residency eviction policy and economics;
- agent graph persistence and deletion/close semantics;
- root/sub-agent rollout-budget enforcement;
- whether Cerebro should use append-only SQL events, an object log + SQL projections, or a hybrid;
- how provider-specific response IDs/caching should survive worker replacement;
- provider abstraction: what belongs to `ProviderAdapter` versus generic turn runtime.

The next documented target is provider abstraction, followed by MCP/tool-search/output-budget details, then the Codex-to-Cerebro gap and Harness v1 proposal.

## Provenance ledger additions

| Finding | Upstream source | Classification | Candidate Cerebro use |
| --- | --- | --- | --- |
| Submission queue / event queue protocol | `protocol/src/protocol.rs`, `session/handlers.rs` | conceptual inspiration only | Typed command/event runtime boundary |
| Durable thread separate from live runtime | `thread_manager.rs`, `thread-store/*` | conceptual inspiration only | Core Cerebro task/thread model |
| Rollout reconstruction restores model/context/window/world state | `session/rollout_reconstruction.rs` | conceptual inspiration only | Deterministic recovery reducer |
| Durable rollback event + replay | session handlers/reconstruction | conceptual inspiration only | Event-sourced corrective transition |
| Resume vs causal fork snapshots | thread manager + agent spawn | conceptual inspiration only | Task branch/resume model |
| Message delivery separate from trigger-turn scheduling | session/AgentControl/V2 tools | conceptual inspiration only | Strong collaborative-agent primitive |
| Root-scoped AgentControl and budgets | `agent/control.rs` | conceptual inspiration only | Workspace/task-tree coordinator |
| Child inherits effective live turn policy/environment | multi-agent common/spawn | conceptual inspiration only | Strong spawn snapshot rule |
| Explicit parent/root turn lineage | protocol + spawn options | conceptual inspiration only | Causal observability/cancellation |
| Agent identity/residency/execution separated | agent control/residency/execution | conceptual inspiration only | Scalable agent lifecycle |
| V2 task paths + mailbox-oriented collaboration | V2 multi-agent handlers | conceptual inspiration only | Strong Cerebro UX fit |

No Codex implementation source has been copied or adapted into Cerebro.
