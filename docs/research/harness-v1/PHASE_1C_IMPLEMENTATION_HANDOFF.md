# Harness v1 Phase 1C implementation handoff

Issue: #220 — `Implement: Harness v1 executable snapshot and pre-side-effect checkpoint`

Branch: `implement/harness-v1-phase1c-checkpoint`

Status: implementation complete; verification recorded below.

## Immutable inputs

- exact implementation base: `main@6c74837db23169e6b6231a334b6fcf5bffd76973`
- exact clarified contract: `design/harness-v1-contract-clarifications@05fb8fa09c47598bbeed16c9be279f5dfe2a648b`
- merged Phase 1B implementation and handoff: `main@6c74837db23169e6b6231a334b6fcf5bffd76973`
- Phase 1B independent review: `review/harness-v1-phase1b@2592b32d62c03d28edfc49f666ecfa967a919d0e`
- Phase 1B repair review: `review/harness-v1-phase1b-repair@685952ce7d1a485e0a5d8f38c493e7cef3245baa`
- failure audit: `research/harness-v1-failure-audit@ee7a8a37fc03d2538ee3ecc5007a48a79d8a4af4`
- seam inventory: `research/harness-v1-seam-inventory@3870a64baeb81e6d32b1ddd13bf0022db30961a0`

Issue #220 and contract sections 13–18, 19–20, 25 and 30–32.6 agree. No implementation piece was
stopped for an ambiguity. The one contract question that needed a decision rather than a reading —
the exact binding-generation source for CoreTools and MCP, listed as review blocker 31.5 — is
decided below.

## Migrations and schema

`006_harness_executable_snapshot.sql` is additive. Migration 005 is untouched.

Columns added:

- `harness_metadata.security_revocation_epoch` (default 0);
- `inference_histories.replay_version` (default 0) — the durable provider-replay checkpoint;
- `step_snapshots`: `provider_config_id`, `provider_id`, `adapter_dialect`,
  `adapter_dialect_version`, `model_profile_id`, `model_profile_version`,
  `inference_history_version`, `provider_replay_version`, `context_projection_version`,
  `token_budget`, `tool_plan_hash`, `tool_plan_catalog_version`, `permission_policy_version`,
  `security_revocation_epoch`, `workspace_ref`, `cwd`, `environment_ref`, `environment_version`,
  `completion_policy_version`;
- `tool_executions`: `binding_executor_identity`, `recovery_effect_class`,
  `recovery_repeat_semantics`, `raw_output_ref`, `model_output_item_id`.

Table added: `harness_artifacts` (artifact reference, format version, producing turn/call/tool
key/binding generation, content type, storage backend, byte size, SHA-256, inline payload or
relative path, retention policy, provenance JSON, created-at).

Indexes added: `idx_tool_executions_call_item` (unique on `tool_call_item_id`),
`idx_harness_artifacts_call`, `idx_harness_artifacts_turn`, `idx_step_snapshots_executable`.

Triggers added:

- `trg_step_snapshots_executable_identity` — a `format_version = 2` row must carry the complete
  frozen execution identity; a `format_version = 1` row must carry none of it. Scoped to those two
  exact versions so an unknown future version is rejected at read time by strict decoding rather
  than by the database guessing what it means;
- `trg_harness_artifacts_immutable`;
- `trg_inference_histories_replay_monotonic`;
- `trg_tool_executions_output_refs_immutable` — a committed raw-output reference, canonical result
  item, binding generation or stable operation key cannot be replaced.

`harness_metadata.schema_epoch` and `storage_format_version` advance to 2. Reads still require an
exact match, so an older build refuses a newer database rather than misreading it.

## StepSnapshot design

`cerebro/harness/snapshot.py` defines `StepSnapshot` at `format_version = 2`. The Phase 1B
identity-only `StepSnapshotIdentity` stays at `format_version = 1` and both live in
`step_snapshots`. They are never interchangeable: the executable barrier requires a version-2 row
and rejects a version-1 one explicitly, so no Phase 1B row can quietly authorise an effect.

The snapshot freezes, by value or stable reference: snapshot/turn/step identity and creating turn
version; provider config id, provider id, adapter dialect and dialect version; model profile id and
version; provider semantic options; inference-history version; provider-replay version;
context-projection version; token budget; the `ToolPlanSnapshot`; permission-policy version;
security-revocation epoch; workspace reference, cwd, environment reference and version; completion
policy version; trace metadata; creation timestamp.

No credentials. `provider_semantic_options` and `trace_metadata` reject credential-shaped keys at
construction, and `ProviderConfig.credential_reference` remains the only credential handle.

Storage writes the canonical envelope plus every queryable column, and reads compare all of them.
A hand-edited column is two answers to one question, so it fails closed
(`test_snapshot_envelope_drift_fails_closed`). `trg_step_snapshots_immutable` from migration 005
still forbids any update.

## ToolPlan design

`ToolPlanSnapshot` freezes `catalog_version`, `policy_version`, `security_revocation_epoch`, the
offered `ToolDefinition`s, their `ToolBinding`s, the provider wire-name → `ToolKey` map, and per-key
`ToolGrantEvidence`. Validation rejects a definition with no binding, a binding with no definition,
a wire name that resolves to nothing, two wire names for one key, and any binding or grant frozen at
a different catalog/policy version than the plan. A wire name resolves through the frozen map or not
at all; it is never parsed.

`cerebro/harness/tool_plan.py` projects the live surface. `CerebroToolCatalog` reads
`CoreTools.specs_for` and the `MCPRegistry` clients for one agent and profile, without starting a
subprocess or touching production routing.

## CoreTools/MCP binding-generation decision (review blocker 31.5)

The generation must change when the executable binding meaningfully changes and stay stable
otherwise. A generation that churns on every restart would make every recovered snapshot stale and
turn crash recovery into "give up"; one that never changes would let a replacement server answer a
call the model never made to it. That gives two sources:

- **CoreTools — content-derived, restart-stable.** `core_binding_generation` digests the canonical
  `ToolKey`, the executor identity `cerebro.core_tools/<name>`, the exact offered description and
  the exact offered input schema. The executable binding is code in this process, so a restart does
  not replace it and the generation survives one. Changing the offered contract does replace what
  the model was promised, and that changes the generation.
- **MCP — connection-scoped.** `mcp_binding_generation` digests the same material plus the
  answering client's `connection_id`. `StdioMCPClient` now mints a fresh `uuid4` on every successful
  handshake and clears it on stop, and `connection_id` reports `None` whenever no process is
  running. A respawn, a Cerebro restart or a `tools/list` refresh that changes a schema all produce
  a new generation, so a snapshot frozen against the old one resolves stale rather than being
  rebound. A server that has never been contacted contributes no entries at all, which is the
  truthful answer to "what is executable right now".

Trust tier and the `tools_enabled` globs are **grant** state, not binding identity. They land in
`ToolGrantEvidence` and `policy_version`. Revoking a tier therefore denies the frozen call under its
original identity instead of pretending the executor changed
(`test_trust_tier_moves_the_grant_not_the_binding_identity`).

`catalog_version` and `policy_version` are deterministic digests of the offered identity material
and of the tier/glob decision respectively, so both are restart-stable.

Recovery capabilities declared for the current catalogue: read-only core tools are `idempotent`;
every mutating core tool (`scratchpad_append`, `memory_write`, `create_channel`, `post_message`,
`task_create`, `task_update`) is `never_automatic_repeat`, because none accepts an idempotency key
and none exposes an authoritative reconciliation lookup. Every MCP tool is `never_automatic_repeat`:
an external server declares nothing about repeat safety today, so the Harness declares nothing on
its behalf. An unrecognised core name is treated as side-effecting.

## Security-revocation check strategy

One monotonic `harness_metadata.security_revocation_epoch`. A snapshot may only be committed while
it freezes the current epoch. Both the barrier transaction and the dispatch transaction compare the
snapshot's epoch against the current one and fail closed on any difference. The tool runtime
additionally compares the live grant's `policy_version` against the frozen plan's. Either mismatch
resolves the call `denied` under its original `CerebroCallId` and binding generation, with zero
executor invocations; the call is never rebound to the newer grant.

The epoch is coarse on purpose. Fine-grained per-grant revocation would need state an interrupted
turn cannot be trusted to have read; an epoch is one comparison a snapshot froze and dispatch
re-checks.

## Provider replay/version/checkpoint ownership

`inference_histories` owns two conversation-scoped versions: `version` (every appended or superseded
item) and `replay_version` (the explicit provider-replay checkpoint). `replay_version` advances only
for material a later request must reproduce exactly — a `ProviderOpaqueItem` with
`replay_requirement="required_for_correctness"`, and a `ToolCallItem` carrying a
`replay_required` `ProviderCallRef`. Ordinary assistant prose does not advance it
(`test_replay_version_advances_only_for_replay_material`). The trigger forbids rewinding it.

`ProviderOutputCoordinator` is the only path that admits finalized provider output. It accepts
`OutputItemCompleted` from the turn's active attempt and active snapshot, appends in provider order
through the existing `append_inference_items` transaction, counts deltas without persisting any, and
returns typed rejections for stale attempts, non-provider items and attempt-attribution mismatches.
No generic code reads an opaque payload; `ProviderOpaqueItem.log_projection()` still redacts it for
every sensitivity.

**Sensitive replay at rest.** The current OpenAI-compatible adapter still emits no
`hidden_reasoning`, `signature_or_encrypted_reasoning` or `secret_like` replay payload, and Phase 1C
fabricates none. The Phase 1A redaction guarantees are unchanged. Phase 1C introduces no new storage
path that can accept sensitive replay: opaque items continue to land in `inference_items` exactly as
Phase 1B stored them, and the new `harness_artifacts` store holds tool output only, never provider
replay material. The at-rest classification, encryption and retention gate therefore remains due
with the first adapter PR that can actually emit such a payload, as AR-12 requires.

## Exact A–L/E2 barrier implementation

`HarnessStore.commit_executable_call_checkpoint`, one `db.run_in_writer` /
`BEGIN IMMEDIATE` transaction.

Verified first by `_verify_executable_barrier`, all failing closed:

| letter | check |
| --- | --- |
| A | a `format_version = 2` snapshot row exists, decodes strictly, belongs to the turn, is the turn's active snapshot, and is the turn's current step |
| B | the named attempt exists, belongs to that turn and snapshot, is the turn's active attempt, and is `active` or `completed`. `completed` is the ordinary case, not an edge one: a provider finishes a step with `tool_calls_pending` and only then does the tool run, so demanding a still-streaming attempt would block every real dispatch. `abandoned`, `failed` and `cancelled_before_dispatch` are refused |
| C | every item this attempt produced up to the call is durable, in ascending non-duplicated sequence order, unsuperseded, and the call is the last of them |
| D | the persisted item is a `ToolCallItem` of this turn, produced by the active attempt, carrying this `CerebroCallId`, unsuperseded, naming the frozen binding's `ToolKey` |
| F | when required, the call carries a `replay_required` `ProviderCallRef` with a handle |
| G | every `ProviderOpaqueItem` kind the caller declares required is durable among the preceding items |
| H | `inference_histories.version` equals the expected history version, `replay_version` equals the expected replay version, and neither snapshot-frozen version is ahead of durable truth |
| J | the frozen plan contains this `ToolKey`, the offered binding equals the frozen binding exactly, and grant evidence exists when the plan carries any |
| — | the current security-revocation epoch equals the snapshot's |

Then committed together in the same transaction:

| letter | write |
| --- | --- |
| E | the `CerebroCallId` is persisted as the `tool_executions` primary key, after a uniqueness check on both `call_id` and `tool_call_item_id` (also enforced by `idx_tool_executions_call_item`) |
| E2 | when the frozen capability requires it, `stable_operation_key` is written in the same insert; a missing key is refused before the transaction opens, and `dispatch_eligible` is re-asserted after |
| I | the row is inserted in `not_dispatched` |
| J | `binding_generation`, `binding_executor_identity` and the recovery capability are written as queryable columns and canonical JSON |
| K | `AgentTurn.state_version` advances once, under its existing compare-and-set |
| L | one `tool.call_admitted` event carrying `checkpoint="executable_pre_side_effect"`, the binding generation, repeat semantics, whether an operation key was assigned, and the history/replay/revocation versions |

An injected failure anywhere inside the transaction commits none of it and advances no turn version
(`test_f05_barrier_is_all_or_nothing_and_pre_barrier_state_invokes_nothing`).

## ToolRuntime dispatch ordering

`HarnessToolRuntime.execute_call`:

1. load the current turn, the immutable snapshot, the exact `ToolExecution`, its frozen binding and
   the finalized call arguments; refuse if the durable execution and the snapshotted plan disagree
   about executable identity;
2. reject a terminal turn, a snapshot that is no longer the turn's active step, an advanced
   security-revocation epoch, a frozen binding that is no longer addressable at its exact
   generation, and a changed grant policy version — each resolving under the original call identity
   with zero invocations;
3. and 4. `mark_tool_dispatch_after_barrier` re-runs the entire barrier verification **and** commits
   `dispatch_may_have_escaped` in one writer transaction. Verifying in one transaction and marking
   in another would leave a window for a revocation to land between them;
5. only then invoke the exact snapshotted executor binding.

`execute_step_calls` runs several admitted calls strictly in original provider order, sequentially;
there is no `gather`, and a test asserts that. `cancel_before_dispatch` records the one cancellation
outcome that is provable. `resume_uncertain_call` continues a call already at
`dispatch_may_have_escaped` after a restart.

## Recovery-capability and repeat rules

- `idempotent` — at most one automatic repeat after an unknown outcome;
- `stable_idempotency_key` — at most one automatic repeat, reusing the exact durably persisted
  `stable_operation_key`; a fresh key would be a second mutation with extra steps;
- `reconcile_before_repeat` — the gateway's named authoritative lookup is consulted; an
  inconclusive answer resolves `indeterminate` with `reconciliation_attempted=true` and never
  repeats;
- `never_automatic_repeat` — resolves `indeterminate` immediately, and `resume_uncertain_call`
  refuses.

A raising executor is `unknown`, not a known failure. `CerebroToolGateway` will not call an
`error: …` string a known failure for a side-effecting binding, because the current
`CompositeToolExecutor` and `StdioMCPClient` collapse tool refusal and transport loss into one
shape; for a read-only binding the same string is a known error, since there is no effect to be
uncertain about. Cerebro claims no generic exactly-once external effects.

## Raw-output policy (AR-12, decided in the PR that creates the data)

- **Backend**: `harness_artifacts` rows plus a Harness-owned directory,
  `<data_dir>/harness_artifacts`, sharded by digest prefix. Nothing else writes there. Raw output
  never enters `messages`, `Message.meta_json`, Hub events, `tool_calls` or `audit_events`.
- **Inline threshold**: 8 KiB of UTF-8. At or below it the exact bytes live in the row; above it
  they live in one file named by the artifact reference.
- **Durability**: the file is written to a `.partial` name, flushed, `fsync`-ed and atomically
  renamed **before** the semantic transaction opens; the index row is inserted inside it. A
  committed `ArtifactRef` therefore always points at a complete object, and a rolled-back
  transaction leaves at most an unreferenced file nothing can name. A staging failure raises before
  the transaction opens, and the store refuses a `ToolResultItem` whose `raw_output_ref` has no
  staged artifact.
- **Retention**: `conversation`. An artifact lives as long as the turn that produced it. Nothing
  prunes automatically in Phase 1C; deletion is an explicit operator action, because deleting the
  evidence for an unreconciled effect is worse than keeping it.
- **Provenance**: producing turn, call, tool key, binding generation, executor identity, status,
  byte size and SHA-256. `ArtifactStore.read` verifies the digest and fails closed on a mismatch.
- **Access and redaction**: the payload is readable only through `ArtifactStore.read`. Generic
  surfaces get `StoredArtifact.describe()` and `ToolRuntimeOutcome.describe()`, which carry size and
  digest and no content. A test asserts the payload appears in no turn event, no outcome projection,
  no artifact description and no operator attention listing.

**Model-visible projection**: the first 4096 characters, with `OmissionMetadata` recording the
reason, omitted bytes and original size whenever anything is dropped. A bounded projection with no
omission record is indistinguishable from a short result.

## Deterministic fixtures and results

All against fakes; no paid provider or real MCP subprocess.

| fixture | Phase 1C disposition |
| --- | --- |
| F-04 | complete-looking assistant and tool-argument deltas admit nothing, advance no history version, create no `ToolExecution`, and invoke nothing |
| F-05 | eight-stage crash matrix (`pre_snapshot`, `post_snapshot`, `post_attempt`, `post_finalized_output`, `post_barrier`, `post_dispatch_mark`, `post_executor_invocation`, `post_result_commit`), each closing and reopening the database. Every pre-barrier stage: zero invocations, zero executions. Every later stage: exactly one `CerebroCallId`, one snapshot/replay set and one operation key. Plus an injected mid-barrier failure proving D/E/E2/I/J/K/L is all-or-nothing |
| F-06 | a lost response for a `never_automatic_repeat` tool stays `dispatch_may_have_escaped` → `indeterminate`, one invocation, `needs_attention` after reopen, and an explicit refusal to resume |
| F-07 | one remote mutation under `op-charge-77` across an in-process retry, and a second arm that kills the process after the dispatch mark and reuses the exact persisted key on resume |
| F-08 | a committed known success survives reopen, keeps one result item, and refuses re-execution |
| F-09 | tool arms: pre-dispatch cancellation (zero invocations, known `cancelled_before_dispatch`); post-dispatch cancellation refused rather than rewriting uncertainty, with a terminal cancelled turn still `needs_attention`; a known success surviving a later cancellation |
| F-10 | late finalized output from an abandoned attempt is rejected, changes no history, creates no execution, and the barrier refuses it outright |
| F-13 | a 24 KiB result keeps complete durable raw evidence (file backend, exact SHA-256 round trip) and a 4096-character projection with omission metadata |
| F-14 | arm A: G1 still addressable → G1 invoked once, G2 count zero. Arm B: G1 unaddressable → `unavailable` under the original identity, G2 count zero |
| F-15 | the epoch advances after the snapshot → `denied` under the original `CerebroCallId` and generation, zero invocations, never rebound |
| F-16 | three admitted calls execute sequentially in original provider order, each with its own durable execution, artifact and result item; `execute_step_calls` contains no `gather` |

Additional targeted coverage: executable snapshot round trip after close/reopen; refusal to rebuild
a snapshot from newer current configuration; snapshot column/envelope divergence; unknown snapshot
and tool-plan versions; refusal to freeze credential material; snapshot must freeze the current
revocation epoch; barrier compare-and-set on turn, history and replay versions; missing
`ProviderCallRef` and missing required `ProviderOpaqueItem` blocking the checkpoint; one
`ToolCallItem` never producing two execution identities; E2 refusal without a durable key; a
`completed` attempt still authorising its own tool call while a `failed` one cannot; an abandonment
landing between the checkpoint and the dispatch transaction stopping the dispatch; artifact write
failure leaving no committed reference; a dangling `raw_output_ref` refused; raw output absent from
every generic surface; Phase 1B Harness data surviving the 005 → 006 upgrade.

Phase 1B TG-01 through TG-19 and all Phase 1A/Phase 0 regressions remain green. The only test edits
were to `test_migration_from_pre_phase1b_schema_preserves_product_data` and
`test_migration_triggers_enforce_every_monotonic_boundary`, which assert the exact applied-migration
list and trigger set; both now expect `[5, 6]` and the four new triggers, and both gained assertions
rather than losing any.

## Verification

From the repository root at `10499c7` plus the documentation and crash-matrix commits:

- `PYTHONPATH=. pytest -q tests/test_harness_snapshot.py tests/test_harness_checkpoint.py
  tests/test_harness_tool_runtime.py tests/test_harness_tool_plan.py
  tests/test_harness_crash_matrix.py tests/test_harness_store.py tests/test_db_migrations.py` —
  all passed;
- `flake8 .` — clean, exit 0;
- `PYTHONPATH=. pytest -q` — **703 passed, 3 skipped**, exit 0;
- `git diff --check` — clean.

## Production routing

`cerebro/runtime.py`, `cerebro/service.py` and `cerebro/poller.py` have no Phase 1C diff. No module
outside `cerebro/harness/` imports `tool_runtime`, `tool_gateway`, `output_checkpoint` or any
checkpoint method, and nothing outside the package imports `cerebro.harness` at all. The one
production file touched is `cerebro/mcp.py`, which gains a `connection_id` property and its
lifecycle; it changes no routing, no wire behaviour and no tool result.

`cerebro.runtime.AgentRuntime` remains the only active production execution path.

## Intentionally deferred to Phase 1D

- the durable reducer and the direct-provider cutover through `ProviderAdapter`;
- `RuntimeService`/`AgentRuntime` routing to the Harness execution path;
- the semantic provider retry/re-entry loop and cancellation orchestration;
- `TurnRecoveryDriver` automatically resuming executable work;
- product `CompletionPolicy` and the atomic finalization transaction;
- native Anthropic/Gemini rollout, external-agent restart recovery, multi-worker takeover/fencing,
  compaction, parallel client tools, subagents and hard budget reservation.

P1A-06 (missing provider-native call-ID provenance) remains a required precondition before the
Harness OpenAI-compatible adapter is activated in production. Phase 1C checkpoint correctness does
not depend on it: `ProviderCallRef` is persisted with the finalized `ToolCallItem` and the barrier
can require it, but nothing in Phase 1C derives execution identity from a provider-native id.

## Contract ambiguity and merge blockers

None blocking. Two decisions were made rather than read, and both are recorded above for review:

1. the exact CoreTools/MCP binding-generation sources (contract review blocker 31.5);
2. the raw-output backend, 8 KiB inline threshold, and retention/provenance policy (AR-12's PR-3
   gate).

One deliberate conservatism is worth flagging for Phase 1D: because the current
`CompositeToolExecutor` returns one string shape for both a tool-reported error and a transport
failure, `CerebroToolGateway` resolves a side-effecting `error: …` as truthfully unknown rather than
as a known failure. That is correct under decision 18, and it means the current core and MCP
executors will produce `indeterminate` outcomes where a richer executor contract could produce known
ones. Giving executors a way to declare a proven non-effect is Phase 1D work, not a Phase 1C gap.

## Commits and final branch identity

- `47262c8` — Add executable StepSnapshot, tool plan and pre-side-effect checkpoint
- `10499c7` — Add Phase 1C snapshot, checkpoint and tool-runtime fixtures
- `c6c5bbb` — Add F-05 crash matrix and document the Phase 1C checkpoint path
- the barrier attempt-state repair commit follows

A Git commit cannot contain its own SHA, so the exact pushed branch head is reported in the
completion response; this handoff records its predecessors.
