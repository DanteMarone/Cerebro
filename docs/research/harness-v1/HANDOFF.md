# Harness v1 architecture reconciliation handoff

Issue: #206 — `Design: reconcile Harness v1 research and freeze architecture`

Status: **architecture reconciliation complete; ready for Phase 1 implementation review**

Branch: `design/harness-v1-reconciliation`

Branch base: `f33801a853b6e6952e07767c83947fd582a41f13`

Last design-content head before this handoff commit: `46702963695ef963c3ad1e7f919f461df63b33cb`

> A Git commit cannot contain its own final SHA without changing that SHA. The authoritative final branch head is therefore the Git ref after this handoff commit and is recorded in the issue #206 completion comment. This file records the exact predecessor head and complete incremental commit chain so a fresh agent can verify the final ref without relying on chat history.

Date: 2026-08-29

## Exact authoritative inputs

Use these exact immutable SHAs. Do not substitute moving branch tips.

- Codex harness research: `research/codex-harness-mining@3f246ae7f4f49a9d5cb3e2593299e5591914c1c7`
- Goose harness research: `research/goose-harness-mining@ddb3ad9b5951fcbfe51420aac10df213200ccad5`
- Native provider normalization: `research/provider-api-normalization@f33801a853b6e6952e07767c83947fd582a41f13`
- Accepted Phase 0 characterization: `test/harness-v1-phase0-characterization@df542c53f587c8963ce84e8d83d731473ee7bd0d`
- Current Cerebro seam inventory: `research/harness-v1-seam-inventory@3870a64baeb81e6d32b1ddd13bf0022db30961a0`
- Failure-mode audit: `research/harness-v1-failure-audit@ee7a8a37fc03d2538ee3ecc5007a48a79d8a4af4`
- Current source baseline characterized by Phase 0/#207/#208: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

Root `AGENTS.md` and issue #206 including the latest coordination comment were read before reconciliation.

## Deliverables

Completed on this branch:

1. `docs/research/codex-harness/CEREBRO_HARNESS_V1.md`
   - reconciled implementation-ready architecture;
   - replaces the earlier Codex-only proposal as the architecture source of truth.

2. `docs/research/harness-v1/RECONCILIATION.md`
   - accepted/modified/deferred/rejected dispositions for Codex, Goose, native-provider, Phase 0, current-seam and failure-audit findings;
   - explicit rejected migration shortcuts and provenance disposition.

3. `docs/research/harness-v1/PHASE_1_CONTRACT.md`
   - canonical identities/types;
   - durable state transitions and invariants;
   - Phase 0 compatibility requirements;
   - deterministic acceptance fixtures F-01 through F-20;
   - explicit deferred claims and review blockers.

4. `docs/research/harness-v1/HANDOFF.md`
   - this resumable checkpoint.

## Incremental design commits

- `89cfd9b2bd43daa18d7ebf46ba9abc92cac85aa2` — reconcile Harness v1 architecture
- `ed1e64c2b8647648d22e11db2b3890cfdc49ed62` — record reconciliation decisions
- `46702963695ef963c3ad1e7f919f461df63b33cb` — define Phase 1 contract
- final handoff commit follows this predecessor and is the branch ref recorded in issue #206

All work is documentation/design only. No production or test code was intentionally changed.

## Frozen architecture decisions

The implementation should treat these as decided unless a new explicit architecture review reopens them:

1. Cerebro Slack/channel/task/product state remains above the harness.
2. `RuntimeService` and `ChannelPoller` remain wake/dispatch policy above the harness; `AgentRuntime` is the initial product-facing migration boundary.
3. Durable `AgentTurn`/execution state is separate from collaboration `messages` and product `tasks`.
4. `messages` and `Message.meta_json` are not the canonical Harness execution/replay log.
5. Harness operation is a durable, re-entrant reducer/effect loop.
6. Every semantic inference operates against an immutable, versioned `StepSnapshot`.
7. Direct native `ProviderAdapter` is separate from `ExternalAgentAdapter` for CLI/ACP/vendor harnesses. Current `CliAgentProvider` is the concrete migration seam.
8. `ModelProfile` is versioned behavior/capability data separate from provider identity/configuration.
9. Canonical inference history is an ordered `InferenceItem` stream.
10. Provider-required opaque replay material and native call references are durable, ordered and adapter-owned when required for correctness.
11. Provider cache/conversation IDs are optional optimizations wherever lossless stateless replay exists.
12. Generic/UI reasoning is summary-only. Hidden/signature/plaintext reasoning retained solely for provider replay remains sensitive opaque state.
13. `OutputItemCompleted` finalized items are semantic authority. Streaming deltas are never executable authority.
14. Before a side-effecting tool executes, finalized call + `CerebroCallId` + required `ProviderCallRef` + required ordered replay state + executable `StepSnapshot`/tool binding + recovery capability must be durably checkpointed.
15. Tool policy/runtime remains Cerebro-owned; MCP is a tool source/transport below canonical catalog/plan/policy/runtime contracts.
16. Every admitted tool call has a stable Cerebro identity and monotonic durable execution state.
17. Tool execution distinguishes `not_dispatched`, `dispatch_may_have_escaped`, and resolved outcome. Missing result after dispatch never proves retry safety.
18. Generic exactly-once external side effects are **not** promised. Automatic repeat dispatch requires executor proof of read-only, idempotent, stable-idempotency-key or authoritative reconciliation semantics.
19. Raw/full tool output is separate from bounded model-visible output.
20. Provider error retryability and semantic replay safety are separate decisions.
21. Durable semantic progress is monotonic. Recovery never silently rewinds across committed tool effects/results.
22. Cancellation is control state and cannot falsify an already-known or indeterminate external effect.
23. Provider/model switches with active incompatible replay state require explicit abandonment/fresh semantic boundary; late superseded-attempt output is non-authoritative.
24. Canonical IDs/versions include state/attempt/snapshot/binding/execution epochs sufficient for later stale-worker fencing without redefining the model.
25. Provider inference completion is separate from Cerebro `CompletionPolicy`/product acceptance.
26. Durable execution facts, transient Hub/UI events and telemetry/accounting remain separate layers.
27. Existing `tool_calls` and `audit_events` are not automatically reused merely because their names resemble Harness objects.
28. Measured `budget_usage` and external-harness `agent_quota` retain distinct provenance.
29. Phase 0 product behavior is a hard compatibility contract: completion-ordered final messages, zero partial channel rows, topic PASS/silent completion, DM fail-closed behavior, sequential tool execution, provider concurrency isolation, TurnGuard behavior, cancellation cleanup and resilient usage telemetry.

## Phase 1 scope

Phase 1 is deliberately a **single-process durable direct-provider core**, initially proving the design through the existing OpenAI-compatible/LM Studio path.

It includes:

- canonical IDs, ordered inference items, provider/model/error/recovery/tool types and versioned serialization;
- compatibility projection from current collaboration `Message`/`ContextBuilder` inputs to canonical inference state;
- direct `ProviderAdapter` compatibility edge for OpenAI-compatible/LM Studio;
- explicit separate `ExternalAgentAdapter` boundary while preserving current legacy CLI behavior;
- additive Harness persistence beside `messages` for turns, sparse events, snapshots, inference items, attempts and tool executions;
- stable provider-attempt identity before dispatch;
- immutable StepSnapshot and current CoreTools/MCP tool-binding projection;
- finalized-output/provider-replay checkpoint before side-effecting tool dispatch;
- explicit post-dispatch uncertainty and executor idempotency/reconciliation metadata;
- raw/full tool result versus bounded model result;
- re-entrant reducer/effect execution for the direct-provider path;
- monotonic retry/recovery/cancellation semantics;
- current chat CompletionPolicy and atomic/idempotent final product publication;
- existing Hub/usage projections and Phase 0 observable behavior unchanged.

The exact contract and deterministic acceptance fixtures are in `PHASE_1_CONTRACT.md`.

## Explicitly deferred functionality

These features have reserved seams/identities but are not Phase 1 promises:

- durable multi-worker/takeover recovery and stale-worker fencing enforcement;
- parallel client-tool execution;
- concurrent shared workspace/git mutation;
- ContextManager compaction;
- child/subagent execution and descendant terminal policy;
- recoverable external CLI/ACP/vendor-harness sessions/orphan reconciliation;
- hard provider budget reservation/admission;
- deferred/searchable tool catalogs and richer artifact UX;
- provider-hosted tools as a generic cross-provider contract;
- production support for every native provider in the first slice.

Do not enable the associated feature until the gates in `RECONCILIATION.md` and the failure-audit invariants are implemented and tested.

## Ordered implementation / PR sequence

Recommended implementation issues/PRs:

1. **Implement: Harness v1 canonical contracts and compatibility adapters**
   - canonical IDs/items/errors/provider/model/tool types;
   - current `Message`/ContextBuilder projection;
   - OpenAI-compatible/LM Studio adapter;
   - separate external-agent boundary/shim.

2. **Implement: Harness v1 additive durable store**
   - new Harness tables/CRUD/serializer/versioning;
   - causal admission uniqueness;
   - atomic turn/event/snapshot/item/attempt/tool transitions;
   - do not repurpose `messages`, `tool_calls`, `audit_events` or product `tasks`.

3. **Implement: Harness v1 StepSnapshot and pre-tool checkpoint**
   - CoreTools/MCP canonical tool plan/bindings;
   - immutable snapshots and binding generations;
   - finalized provider output/replay persistence;
   - side-effect executable barrier and dispatch uncertainty;
   - raw/model output split;
   - preserve sequential execution.

4. **Implement: Harness v1 durable reducer direct-provider cutover**
   - move OpenAI-compatible/LM Studio path out of `_generate` locals;
   - provider-attempt admission/late-attempt fencing;
   - semantic retry/recovery/cancellation;
   - tool reconciliation/indeterminate handling;
   - preserve all Phase 0 behavior.

5. **Test/Implement: Harness v1 product finalization and crash hardening**
   - final message/silent outcome + terminal AgentTurn as one idempotent decision;
   - crash-injection fixtures at provider/tool/finalization boundaries;
   - F-01 through F-20 and Phase 0 suite green.

6. **Implement: Harness v1 ContextManager projection and model-aware budgeting**
   - typed/versioned context projection behind current sources;
   - no compaction required in this PR.

7. **Implement: first materially non-OpenAI native provider**
   - Gemini Interactions or Anthropic Messages;
   - prove opaque replay/native-call semantics through unchanged generic runner.

8. Later independent issues: compaction; multi-worker fencing; workspace/resource concurrency; external-agent recovery; subagents; completion verifiers; deferred tools/artifacts; hard budget admission.

## Remaining questions requiring review before production implementation

These are implementation choices inside the frozen architecture, not reasons to reopen the main model:

1. **Harness SQL/index/serializer shape.** Choose exact columns/indexes and versioned JSON envelope while preserving all canonical identities, atomicity and monotonic transitions.
2. **Sensitive opaque replay at rest.** Before a native adapter persists hidden/signature reasoning material, decide encryption/access/retention/redaction policy. Generic logs/UI must remain blind to payload semantics.
3. **Raw tool-output storage.** Decide inline-size threshold, artifact/blob location, lifecycle/retention and failure behavior without destroying model/recovery evidence.
4. **Exact causal wake encoding.** Define deterministic `CausalWakeKey` for current immediate-DM, poll and explicit turn paths, including any occurrence identity needed to distinguish intentional repeats.
5. **Tool binding generation.** Define how CoreTools versions and MCP reconnect/`tools/list_changed` generations become stable snapshottable executable binding identities.
6. **Rollout ownership.** If the durable reducer ships behind a feature flag/shadow path, ensure old and new paths cannot both execute the same causal wake. A shadow must not perform external side effects.
7. **Source drift.** The seam inventory/current behavior were pinned to `main@57e9c4...`; if implementation starts from a newer `main`, revalidate affected paths/functions before patching rather than assuming source layout is unchanged.
8. **First second-wire provider.** Gemini Interactions and Anthropic Messages are both valid abstraction stress tests. Pick based on implementation priority; this is not a canonical-contract decision.

## Provenance

- Codex findings remain conceptual inspiration only under the exact issue #202 pinned upstream baseline.
- Goose findings remain conceptual inspiration only under the exact issue #203 pinned upstream baseline.
- No upstream Codex/Goose implementation code was copied or adapted in this design pass.
- Any future adapted/copied implementation requires a new explicit provenance/license/NOTICE decision before merge.

## Verification

This branch is intended to differ from its base only by the four design deliverables listed above. Perform a final Git compare after this commit and record the exact resulting branch head on issue #206.

Tests/lint are not required for this design-only branch because root `AGENTS.md` permits skipping them for documentation-only changes. Production implementation PRs must restore normal lint/test requirements and include the Phase 0 + Phase 1 acceptance coverage appropriate to their slice.
