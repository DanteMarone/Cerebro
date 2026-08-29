# Harness v1 research reconciliation

Issue: #206 — `Design: reconcile Harness v1 research and freeze architecture`

Date: 2026-08-29

This document records the disposition of the pinned Harness v1 research inputs. It is a synthesis record, not new upstream research.

## Pinned inputs

- Codex harness research: `research/codex-harness-mining@3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- Goose harness research: `research/goose-harness-mining@ddb3ad9b5951fcbfe51420aac10df213200ccad5`
- Native provider normalization: `research/provider-api-normalization@f33801a853b6e6952e07767c83947fd582a41f13`
- Accepted Phase 0 characterization: `test/harness-v1-phase0-characterization@df542c53f587c8963ce84e8d83d731473ee7bd0d`
- Current Cerebro seam inventory: `research/harness-v1-seam-inventory@3870a64baeb81e6d32b1ddd13bf0022db30961a0`
- Failure-mode audit: `research/harness-v1-failure-audit@ee7a8a37fc03d2538ee3ecc5007a48a79d8a4af4`
- Current source baseline referenced by Phase 0/#207/#208: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

Codex and Goose findings remain conceptual inspiration only. No upstream implementation source is authorized for copying/adaptation by this reconciliation.

## Reconciliation rule

A finding is:

- **accepted** when it is part of the frozen architecture essentially as stated;
- **modified** when the architectural direction survives but its semantics were tightened by another input/current Cerebro constraints;
- **deferred** when the design leaves an explicit seam but Phase 1 does not implement it;
- **rejected** when it is not part of Cerebro Harness v1 or would violate the frozen boundaries.

## 1. Codex harness findings

| Finding | Disposition | Reconciliation |
| --- | --- | --- |
| Immutable request-scoped step state | **Accepted** | Becomes versioned `StepSnapshot`. It freezes provider/model semantic settings, canonical history/replay versions, tool definitions/wire mapping, executable binding generation, policy evidence and completion/context references. |
| Provider config/runtime/model behavior separation | **Accepted, modified** | `ProviderAdapter` owns direct inference protocol/config behavior. `ModelProfile` is separately versioned behavior/capability data. External coding harnesses are removed from this contract. |
| Provider-neutral inference types | **Accepted, modified** | Provider review proves canonical history must be ordered `InferenceItem`s, not message-centric types with optional provider hints. |
| Provider cache/continuation state as optional hints | **Modified** | Conversation/cache handles remain optional only where stateless replay is lossless. Required native replay items/call refs become first-class durable state. |
| Canonical tool identity / definition / binding / result | **Accepted** | `ToolKey`, request-scoped binding, provider wire-name mapping and one stable `CerebroCallId` are frozen. MCP is a source beneath this model. |
| One terminal result per admitted call | **Modified** | The stable identity/monotonicity requirement is retained, but the failure audit requires explicit post-dispatch uncertainty. An unreconcilable call may resolve as `indeterminate` rather than fabricating success/error/cancelled. |
| Raw/full tool output separate from bounded model output | **Accepted** | Durable raw output/artifact reference is separate from explicit model-visible projection/truncation metadata. |
| Context as typed/versioned state and compaction checkpoint | **Accepted, Phase 1 partly deferred** | Context projection becomes versioned behind `ContextManager`; actual compaction is later. Required provider replay items are already pinned against future compaction. |
| Typed retry/recovery/cancellation/suspend | **Accepted, modified** | Retryability is explicitly separate from semantic replay safety. Cancellation is control state, not evidence that an external effect did not occur. |
| Completion/evidence policy separate from provider finish | **Accepted** | Phase 1 implements current Cerebro chat PASS/silence/DM policy; stronger coding-task verification is deferred. |
| Deferred/searchable tool exposure | **Deferred** | Canonical tool identities allow it later; Phase 1 direct tool exposure remains narrow and sequential. |
| Durable session/turn reconstruction | **Accepted, modified** | Durable `AgentTurn` + ordered items/snapshots/attempts/tool execution facts become source of truth. Generic exactly-once external effects are explicitly not promised. |
| Codex hidden/managed subagent execution as product model | **Rejected** | Cerebro's visible Slack-like collaboration remains above the harness. Future delegated agents use durable child lineage without adopting Codex UX/runtime ownership. |
| Responses-shaped provider contract as generic abstraction | **Rejected** | Current native-provider review proves the generic contract must not be OpenAI Responses-shaped. |

## 2. Goose harness findings

| Finding | Disposition | Reconciliation |
| --- | --- | --- |
| Re-entrant persisted-state machine/effect architecture | **Accepted conceptually** | This becomes Cerebro's durable `HarnessReducer`/effect loop. Goose's experimental operation ordering/API is not copied or treated as settled upstream truth. |
| Reload durable state between explicit effects | **Accepted** | Process-local `_generate` transcript/state cannot remain recovery truth. Reducer decisions are recomputed from durable versions/checkpoints. |
| Direct providers and ACP/CLI external agents are different abstraction levels | **Accepted** | Frozen split between `ProviderAdapter` and `ExternalAgentAdapter`; current `CliAgentProvider` is the migration seam. |
| Host-owned modular tool inspection/policy above MCP | **Accepted** | Tool policy/runtime remains Cerebro-owned; MCP does not bypass trust tiers, allowlists, confinement, future security/egress modules or recovery semantics. |
| Durable history separate from active model context | **Accepted** | Ordered canonical inference history is durable; `ContextManager` produces provider/model-budgeted projections. |
| Provider completion separate from task/completion acceptance | **Accepted** | Canonical `InferenceCompleted` status is input to `CompletionPolicy`, not terminal product truth. |
| Durable child sessions/lineage | **Deferred** | Canonical turn IDs reserve root/parent lineage now; child admission/recovery is later and must be idempotent. |
| Durable effects, transient client events and telemetry are separate | **Accepted** | Durable execution facts, Hub/UI events and usage/telemetry are three distinct layers. |
| Goose exact `GOOSE_STATE_MACHINE` implementation as template | **Rejected** | It was experimental at the pinned baseline and remains conceptual inspiration only. |
| Goose provider interface including external ACP agents under one provider concept | **Rejected** | Cerebro keeps direct inference and external-agent contracts separate. |

## 3. Native provider normalization findings

All 14 provider-normalization corrections are incorporated.

| Finding | Disposition | Reconciliation |
| --- | --- | --- |
| Ordered `InferenceItem` history | **Accepted** | Frozen canonical history representation. |
| `ProviderOpaqueItem` replay classes | **Accepted** | Ordered, adapter-owned, durable according to replay requirement/scope/sensitivity. |
| Durable `ProviderCallRef` | **Accepted** | Native call correlation is not canonical call identity but is durable when replay requires it. |
| Summary-only generic reasoning visibility | **Accepted** | `ReasoningSummaryItem/Delta` are the only generic reasoning surfaces. Required hidden reasoning stays sensitive opaque replay state. |
| `OutputItemCompleted` authoritative | **Accepted** | Deltas never authorize tool execution or durable history. |
| Semantic provider completion status | **Accepted** | Includes end-turn, tool-pending, provider-continuation, incomplete/filter/max-output classes. |
| Separate provider options/cache hints/replay state | **Accepted** | Semantic options are snapshotted; cache handles are optional where possible; required replay is durable ordered history. |
| Replay checkpoint before side-effecting tools | **Accepted and strengthened** | Failure audit adds durable call dispatch semantics and executor recovery capability to the pre-side-effect barrier. |
| Expanded provider error taxonomy | **Accepted** | Adds quota/billing, permission, request size and preserves distinct context exhaustion/policy/auth classes. |
| Richer `ModelProfile` | **Accepted** | Tool mode, reasoning/replay semantics, role fidelity, stateless replay and incompatibilities are versioned behavior data. |
| Explicit OpenAI-compatible dialect validation | **Accepted** | Accepted wire requests are not proof of semantic support. |
| Required replay pinned against compaction | **Accepted** | Actual compaction deferred; the invariant is frozen now. |
| Provider/model switching at fresh semantic boundaries | **Accepted and strengthened** | Active incompatible continuation must be abandoned durably; late old-attempt output is fenced. |
| Strong stateless replay/crash fixtures | **Accepted** | Included in Phase 1 contract even before a second native provider ships. |

## 4. Phase 0 current behavior

Phase 0 is not a suggestion; it is the compatibility baseline.

| Behavior | Disposition | Reconciliation |
| --- | --- | --- |
| Final collaboration row appears only at completion | **Accepted unchanged** | Harness persistence is separate; no placeholder/partial channel rows are introduced. |
| Concurrent final rows ordered by completion time | **Accepted unchanged** | Final message is still inserted at completion/finalization transaction time. |
| Topic exact `PASS` is silent/discarded | **Accepted unchanged** | Becomes explicit terminal product outcome with no final agent message. |
| Topic empty `stop` is silent completion | **Accepted unchanged** | Same as above. |
| DM PASS/silence fail closed | **Accepted unchanged** | CompletionPolicy persists current error behavior. |
| Multiple tool calls execute sequentially | **Accepted for Phase 1** | Parallel provider output is representable but execution remains sequential until resource-aware safety exists. |
| Provider concurrency isolated by per-provider semaphore | **Accepted as capacity behavior** | Semaphores remain process-local capacity controls, not correctness ownership. |
| TurnGuard behavior | **Accepted unchanged for Phase 1** | Current ceilings/freeze messages remain; process-local state does not become durable recovery truth. |
| MCP/core allowlist and confinement refusal | **Accepted unchanged** | Canonical ToolRuntime wraps and preserves these enforcement points. |
| Cancellation cleanup/no partial row | **Accepted unchanged** | Durable cancellation is added without changing current UI/product cleanup. |
| CLI subprocess killed on explicit cancellation | **Accepted unchanged** | Still required even though external harness durable crash recovery is deferred. |
| Usage persistence non-fatal | **Accepted for telemetry** | Remains valid because `budget_usage` is observational. Hard spend admission would require different durable semantics later. |

## 5. Current Cerebro seam inventory findings

| Current seam/finding | Disposition | Reconciliation |
| --- | --- | --- |
| `AgentRuntime` currently owns nearly all harness concerns | **Accepted migration fact** | Preserve its service-facing turn entry initially; decompose `_generate`/`_run_tool` behind durable harness contracts. |
| `Provider.stream(list[Message], ...)` and `ContextBuilder.build() -> list[Message]` | **Accepted migration debt** | Translation to canonical history is inserted at these boundaries; collaboration `Message` stops being the provider protocol type. |
| Live tool protocol synthesized with `Message.meta_json` and kept only in memory | **Accepted critical gap** | New ordered durable inference/tool/replay state is stored separately; `meta_json` remains product/import compatibility metadata only. |
| `RuntimeService`/`ChannelPoller` own wake/dispatch | **Accepted boundary** | They stay above the harness. Durable harness re-entry does not redefine wake policy. |
| `CliAgentProvider` conflates provider inference with external harness execution | **Accepted critical gap** | Split native provider and external agent adapter registries/contracts. |
| `ContextBuilder` is a useful collection seam | **Accepted, modified output** | Reuse source collection/compatibility behavior; canonical output is no longer chat messages. |
| Tool responsibilities spread across CoreTools/MCP/service/runtime | **Accepted migration fact** | Wrap into canonical catalog/plan/policy/runtime without bypassing current execution-time enforcement. |
| Existing `tool_calls` / `audit_events` are unused by runtime | **Accepted** | Do not treat them as Harness state or automatically reuse them. |
| `TurnGuard`, semaphores, service tasks and poller in-flight state are process-local | **Accepted** | None of these becomes crash-recovery ownership. |
| Hub is lossy in-process fanout | **Accepted** | Durable execution events are separate; Hub remains a projection. |
| `run_in_writer()` is existing atomic SQLite primitive | **Accepted** | Use it for executable checkpoint/finalization transactions. |
| `budget_usage` and `agent_quota` have different provenance | **Accepted unchanged** | Preserve distinction after adapter split. |
| Product `tasks` are not harness execution tasks | **Accepted unchanged** | New turn/effect nomenclature and persistence stays separate. |

## 6. Failure audit findings

The failure audit changes the architecture from "durable enough to replay" to "durable enough to know when replay is unsafe."

| Finding | Disposition | Reconciliation |
| --- | --- | --- |
| Stable provider attempt identity before dispatch | **Accepted; Phase 1 contract** | Every network/provider request is bound to `InferenceAttemptId` + immutable snapshot before it can leave the process. |
| Provider retryability != semantic replay safety | **Accepted; Phase 1 contract** | Separate canonical error metadata from harness recovery disposition. |
| Post-tool-dispatch ambiguity must be durable | **Accepted; Phase 1 contract** | Tool execution distinguishes `not_dispatched`, `dispatch_may_have_escaped`, and resolved state. |
| Missing ToolResult after dispatch is not retry proof | **Accepted; Phase 1 contract** | Automatic second dispatch is forbidden without executor proof. |
| Executor idempotency/reconciliation capability required | **Accepted; Phase 1 contract** | Snapshotted tool binding carries recovery semantics and stable operation key when applicable. |
| Cancellation cannot falsify effect outcome | **Accepted; Phase 1 contract** | Turn cancellation and call resolution are separate monotonic state. |
| Semantic progress monotonic across recovery | **Accepted; Phase 1 contract** | Never rewind committed tool effects/history to ask the model to rediscover them. |
| Provider/model switch needs abandonment/fresh boundary | **Accepted; Phase 1 contract** | Old replay state is not translated; superseded attempt output is non-authoritative. |
| IDs/versions sufficient for later stale-worker fencing | **Accepted; Phase 1 contract** | `state_version`, `execution_epoch`, snapshot/attempt/call/binding versions exist from initial schema/types. |
| Generic exactly-once remote side effects | **Rejected** | Harness guarantees durable transition/finalization idempotency; arbitrary external effects require executor guarantees or become indeterminate. |
| TTL lease sufficient for worker ownership | **Rejected** | Later multi-worker execution requires monotonic fencing epoch/CAS, not only expiration. |
| Parallel mutation based on one `parallel_safe` boolean | **Rejected** | Resource-aware conflict proof is required; Phase 1 stays sequential. |
| Durable multi-worker/takeover enforcement | **Deferred** | Types/schema leave room, but single-process Phase 1 does not claim it. |
| Workspace/git concurrent mutation | **Deferred** | Requires isolation or resource/version preconditions before enablement. |
| Child execution, external-agent recovery, mixed-version worker enforcement | **Deferred with explicit gates** | Each is blocked until its audit invariant/test set is implemented. |

## 7. Important modifications to the pre-reconciliation architecture

### 7.1 Tool "exactly once" wording

Old wording could be read as a promise that every real-world side effect happens exactly once. That is not achievable generically across the post-dispatch ambiguity window.

Frozen meaning:

- one stable `CerebroCallId` per admitted canonical call;
- exactly-once durable admission/transition/final publication under local transactional state;
- monotonic terminal/indeterminate call resolution;
- no automatic duplicate external mutation without executor idempotency/reconciliation proof.

### 7.2 `StepSnapshot` immutability

A snapshot freezes interpretation/binding. It does not make mutable files/repos immutable and it does not force execution after a security-critical grant is revoked.

Frozen additions:

- binding generation checked at dispatch;
- security revocation/kill epoch may invalidate a frozen grant;
- concurrent mutable resource safety is a separate concern.

### 7.3 Provider request retry

Old architecture's "safe automatic retry" examples are now conditional on semantic replay proof. A network/HTTP class is never enough by itself after dispatch may have escaped.

### 7.4 Durable events/projection

`agent_turns` plus `turn_events` are retained conceptually, but executable transitions must be atomic/versioned. The event log cannot say one thing while the current projection authorizes a conflicting next effect.

### 7.5 External CLI harnesses

The old package layout left CLI agents as parallel provider implementations. Reconciliation freezes a separate external-agent boundary because crash/session/tool ownership differs materially from native model inference.

## 8. Explicitly rejected migration shortcuts

The following shortcuts are out of scope for implementation unless architecture is reopened:

1. Make `messages` the durable reducer/inference log.
2. Store canonical provider replay in `Message.meta_json`.
3. Keep `CliAgentProvider` implementing the same semantic adapter as native APIs indefinitely.
4. Treat existing `tool_calls` as valid Harness call state without redefining/migrating its semantics.
5. Treat `audit_events` as an existing durable reducer event log.
6. Treat current TTL leases, semaphores or `RuntimeService._turns` as durable execution ownership.
7. Execute a tool from partial streaming JSON before the provider item/replay checkpoint is finalized.
8. Retry a side-effecting call because a timeout/429/5xx is "retryable."
9. Convert provider-required hidden reasoning into normal Cerebro reasoning/UI output.
10. Translate active provider opaque replay state into another provider/model.
11. Enable parallel client-tool mutation in Phase 1.
12. Change current channel PASS/silence/finalization behavior as a side effect of the harness refactor.

## 9. Deferred features and their gates

| Feature | Deferred until |
| --- | --- |
| Durable multi-worker/takeover | monotonic ownership fencing + CAS effect admission + stale-worker crash fixtures |
| Compaction | versioned history/replay-scope CAS and replay pinning tests |
| Parallel tools | concrete resource conflict keys/commutativity proof |
| Shared git/workspace mutation | isolation or resource/version preconditions + exact verification identity |
| Child/subagents | idempotent child admission + lineage + descendant terminal policy |
| Recoverable external harnesses | durable external execution identity + orphan reconciliation/reconnect semantics |
| Hard provider budget enforcement | durable spend reservation/admission semantics |
| Deferred/searchable tool catalogs | direct ToolCatalog/ToolPlanSnapshot contract proven and catalog pressure justifies it |
| Provider-hosted tools | explicit cross-provider semantic contract or adapter-local extension with safe replay semantics |
| Second native provider | after direct-provider durable runner contract is implemented; then used as abstraction stress test |

## 10. Provenance disposition

No reconciliation decision changes the legal/provenance classification of the upstream research:

- Codex: conceptual inspiration only, pinned upstream baseline retained by issue #202 research.
- Goose: conceptual inspiration only, pinned upstream baseline retained by issue #203 research.
- Cerebro implementation must use independent code/naming and record any future upstream adaptation separately before merge.

The reconciled architecture is a Cerebro-owned synthesis driven by independent upstream findings, current provider documentation research, current Cerebro source mapping and adversarial failure analysis.
