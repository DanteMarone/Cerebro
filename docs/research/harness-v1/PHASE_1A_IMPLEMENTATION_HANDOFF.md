# Harness v1 Phase 1A implementation handoff

Issue: #212 — `Implement: Harness v1 canonical contracts and compatibility adapters`

Status: **Phase 1A merge repair complete; awaiting independent re-review and merge**

Branch: `implement/harness-v1-phase1a-contracts`

Date: 2026-08-29

## Merge-repair pass for review #213

The independent review completed at
`review/harness-v1-phase1a@853d3217ae1e2cb454ceb14a58bbc2f7c167f2aa` with verdict
**MERGEABLE AFTER FIXES**. This repair started exactly at
`d000ba85c316e146943a2d181da03098e0daebcd` and addresses only accepted findings P1A-01
through P1A-05. P1A-06 and P1A-07 remain follow-up gates.

Repair commits, in order:

- `dc5b38b0f33b726b7a83f860764979f8eae34ba0` — prevent cancelled streams from finalizing deltas;
- `22c598323bd7934041488c3c3eda0c030109bdbb` — enforce attempt and causal-history invariants;
- `5605ee8515c02329784881469a9f19175c56583c` — make external cancellation part of the public lifecycle;
- `49ddf2059b72d7293bbdc980f610a1862b8708ee` — redact opaque payloads from validation errors;
- `e4bc746007195a2982cc32612c1fe1b12eb4842c` — document the repaired invariants.

`e4bc746007195a2982cc32612c1fe1b12eb4842c` is the complete repair implementation head before
this handoff-only commit. A commit cannot contain its own SHA; the authoritative final repair head
is the pushed `implement/harness-v1-phase1a-contracts` branch ref and is reported with the
completion handoff.

| Finding | Disposition |
| --- | --- |
| P1A-01 | Cancellation now exits semantic finalization, closes the active provider iterator, and emits no completed item or normal completion from partial text/tool fragments. |
| P1A-02 | Construction and deserialization enforce the complete dispatch/barrier/semantic matrix while failed and abandoned attempts preserve either barrier value. Multi-field transitions validate atomically. |
| P1A-03 | Active committed `ToolResultItem`s automatically protect their causal calls; caller protection still covers unresolved possibly-escaped calls. Multi-call and interleaved-history regressions assert no active orphan result. |
| P1A-04 | The declared lifecycle carries a cancel token; `stream_events()` registers/removes its driving task, so public `cancel()` reaches existing CLI cleanup without `track()`. No restart recovery was added. |
| P1A-05 | Direct model, union adapter, nested request and nested event validation hide raw inputs. Traceback/log tests prove the sentinel payload is absent while durable serialization remains exact. |

Repair verification from the repository root:

- focused Harness repair suite — **138 passed**;
- post-adjustment opaque-redaction suite — **8 passed**;
- `flake8 .` — clean, exit 0;
- `PYTHONPATH=. pytest -q` — **593 passed, 3 skipped**, exit 0.

Exact repair-delta files (including this handoff):

- `cerebro/harness/adapters/cli_external.py`
- `cerebro/harness/adapters/openai_compatible.py`
- `cerebro/harness/attempts.py`
- `cerebro/harness/events.py`
- `cerebro/harness/external_agent.py`
- `cerebro/harness/history.py`
- `cerebro/harness/items.py`
- `cerebro/harness/request.py`
- `cerebro/harness/serialization.py`
- `docs/harness_v1_contracts.md`
- `docs/research/harness-v1/PHASE_1A_IMPLEMENTATION_HANDOFF.md`
- `tests/test_harness_contracts.py`
- `tests/test_harness_external_agent.py`
- `tests/test_harness_openai_adapter.py`
- `tests/test_harness_redaction.py`

`cerebro/runtime.py::AgentRuntime` remains the active production path. No SQL migration, Harness
persistence, recovery driver, snapshot persistence, tool checkpoint transaction, reducer/effect
cutover, provider-selection cutover, native provider, or external-agent restart recovery was added.
Do not start Phase 1B until this branch is re-reviewed and merged.

## Exact authoritative inputs

Immutable SHAs, not moving branch tips.

| Input | SHA |
| --- | --- |
| Implementation base (`main`, Phase 0 characterization merged) | `920ff0fe325f6c5cbd337d2217aa97d90a6a62eb` |
| Clarified design source of truth (`design/harness-v1-contract-clarifications`) | `05fb8fa09c47598bbeed16c9be279f5dfe2a648b` |
| Architecture review (`review/harness-v1-architecture-audit`) | `46865080a74a20f7406df506d7c6668ffdafc283` |
| Original frozen reconciliation (`design/harness-v1-reconciliation`) | `f0b792fd02b72b53375babd7c02a8b95bdeb1902` |

Read before editing: root `AGENTS.md`, issue #212 in full,
`docs/research/harness-v1/PHASE_1_CONTRACT.md`, `docs/research/harness-v1/HANDOFF.md` and
`docs/research/codex-harness/CEREBRO_HARNESS_V1.md` at the clarified SHA.

## Commit chain

From the base, in order:

- `55e497cb119db02ac9cc4eef1f568737aab4cf3e` — Add Harness v1 canonical contracts and adapter
  boundaries
- `cca5d4b77a3c8ddad78c085f1914801078d83711` — Add deterministic tests for Harness v1 Phase 1A contracts
- `69d12b4` — Document Harness v1 Phase 1A contracts and record the handoff (adds
  `docs/harness_v1_contracts.md`, the README pointer and the first revision of this file)
- a final amendment commit follows, correcting the module-boundary wording and adding the
  import-boundary test

A Git commit cannot contain its own SHA. The authoritative final branch head is the
`implement/harness-v1-phase1a-contracts` ref after the final commit, reported on issue #212.

## What was implemented

### `cerebro/harness/` — canonical contracts

| Module | Types |
| --- | --- |
| `ids.py` | `HarnessId`, `InvalidHarnessId`, `AgentTurnId`, `ConversationTurnId`, `StepSnapshotId`, `InferenceAttemptId`, `InferenceItemId`, `CerebroCallId`, `ModelProfileId`, `ProviderConfigId`, `ArtifactRef`, `ToolBindingGeneration`, `ExternalExecutionId` |
| `content.py` | `Provenance`, `TextPart`, `JsonPart`, `MediaPart`, `ContentPart`, `Instruction`, `OmissionMetadata`, `text_of` |
| `provider_ref.py` | `ProviderCallRef` |
| `tooling.py` | `ToolKey`, `JsonToolInput`, `TextToolInput`, `ProviderOpaqueToolInput`, `ToolInput`, `ToolResultStatus`, `ToolRecoveryCapability`, `ToolDefinition`, `ToolBinding` |
| `items.py` | `INFERENCE_ITEM_FORMAT_VERSION`, `ItemOrigin`, `MessageItem`, `ToolCallItem`, `ToolResultItem`, `ReasoningSummaryItem`, `ProviderOpaqueItem`, `InferenceItem`, `ReplayRequirement`, `ReplayRetentionScope`, `ReplaySensitivity`, `item_sort_key` |
| `history.py` | `InferenceHistory` (canonical/audit views, append, `supersede_abandoned_attempt`) |
| `events.py` | `InferenceStarted`, `OutputItemStarted`, `AssistantTextDelta`, `ReasoningSummaryDelta`, `ToolCallInputDelta`, `OutputItemCompleted`, `UsageUpdate`, `ProviderMetadata`, `InferenceCompleted`, `InferenceFailed`, `InferenceEvent`, `is_authoritative` |
| `attempts.py` | `INFERENCE_ATTEMPT_FORMAT_VERSION`, `InferenceAttempt`, `ProviderDispatchState`, `ProviderAttemptSemanticState`, `InferenceCompletionStatus` |
| `errors.py` | `InferenceError`, `InferenceErrorKind`, `SemanticRecoveryDisposition`, `ProviderRecoveryAction`, `classify_recovery`, `provider_action_for` |
| `execution.py` | `TOOL_EXECUTION_FORMAT_VERSION`, `ToolExecution`, `ToolDispatchState`, `KnownResolution`, `IndeterminateResolution`, `ToolResolution` |
| `model_profile.py` | `ProviderConfig`, `ModelProfile`, `ToolCallingMode`, `OpaqueReplayBehavior`, `ReasoningSummarySupport`, `InstructionRoleFidelity` |
| `request.py` | `InferenceRequest`, `ToolPolicy`, `ReasoningPolicy`, `OutputPolicy`, `request_semantic_hash` |
| `turn.py` | `AGENT_TURN_FORMAT_VERSION`, `AgentTurn`, `AgentTurnLifecycle`, `ProductOutcomeKind` |
| `wake.py` | `CAUSAL_WAKE_KEY_VERSION`, `CausalWakeKey`, `WakeKind` |
| `serialization.py` | `dump_item`/`load_item`, `dump_attempt`/`load_attempt`, `dump_tool_execution`/`load_tool_execution`, `dump_request`/`load_request`, `dump_event`/`load_event`, `canonical_json`, supported-version sets |
| `exceptions.py` | `HarnessError`, `HarnessStateError`, `UnsupportedFormatVersion`, `UnsupportedDialectFeature`, `UnknownDialect`, `ContinuationNotAdmissible` |
| `provider_adapter.py` | `ProviderAdapter`, `AdapterCapabilities`, `PreparedProviderRequest`, `CancelToken`, `assert_continuation_admissible` |
| `external_agent.py` | `ExternalAgentAdapter`, `ExternalExecutionRequest`, `ExternalPromptTurn`, `ExternalRecoveryCapability`, `ExternalAgentEvent` variants, `OrphanReconciliation` |
| `projection.py` | `project_instructions`, `project_history`, `tool_key_from_wire_name` |
| `adapters/openai_dialect.py` | `to_wire_messages`, `to_wire_tools`, `wire_name_for_tool_key`, `tool_key_for_wire_name`, `OpenAIDialectOptions`, unresolved-key helpers |
| `adapters/openai_compatible.py` | `OpenAICompatibleAdapter` |
| `adapters/cli_external.py` | `CliExternalAgentAdapter`, `ExternalExecutionHandle`, `prompt_turns_from_messages` |
| `adapters/__init__.py` | `ADAPTER_FACTORIES`, `adapter_factory_for_dialect`, `supported_dialects` |

### Changes to existing files

- `cerebro/providers/openai_compatible.py`
  - `stream_payload(payload)` split out of `stream()`. `stream()` builds the payload from
    `Message` rows exactly as before and delegates; the Harness adapter builds its own payload
    from canonical items and delegates to the same method. One HTTP client, one SSE parser.
  - `ProviderError.status_code` added (default `None`), set where an HTTP status produced the
    failure. The error taxonomy needs 429 vs 401 and parsing it back out of the message string
    would break the moment the wording changes. Message text is unchanged.
- `cerebro/runtime.py`, `tests/test_agents_loader.py`, `tests/test_cli_agent_provider.py`,
  `tests/test_context.py`, `tests/test_service.py` — one trailing blank line trimmed from each.
  `flake8 .` did not pass on the base commit (5 × W391); root `AGENTS.md` requires it before
  commit. Whitespace only, no behaviour change.
- `README.md` — pointer to the new contracts documentation.
- `docs/harness_v1_contracts.md` — new component documentation.

### Files added

Production: 20 modules under `cerebro/harness/` (including `adapters/`).
Tests: `tests/harness_fixtures.py` plus six `tests/test_harness_*.py` modules.
Docs: `docs/harness_v1_contracts.md`, this handoff.

## AR gate compliance

| Gate | How it is encoded |
| --- | --- |
| AR-02 (producing attempt identity) | `InferenceItem.producing_attempt_id`, required for `origin="provider_attempt"` and forbidden otherwise. `ProviderOpaqueItem` must be provider-originated. |
| AR-02 (superseded disposition) | `InferenceHistory.supersede_abandoned_attempt()` marks `superseded_at`/`superseded_reason`/`superseding_attempt_id`, drops the items from `canonical_request_history()`, retains them in `audit_history()`, and never supersedes past a protected call or any committed `ToolResultItem`. Nothing is deleted. |
| AR-04 (attention projection) | `AgentTurn.needs_attention` / `unresolved_effect_count`; `ToolExecution.is_unresolved_effect` keeps counting after a terminal `indeterminate` resolution. |
| AR-05 (finalization discriminator) | `AgentTurn.is_finalized` reads `product_outcome_kind`, never `final_message_id`. `topic_pass`/`topic_silent_stop` are finalized with no message id. |
| AR-06 (`stable_operation_key`) | `ToolExecution.dispatch_eligible` is false until the key is assigned when `repeat_semantics="stable_idempotency_key"`; `mark_dispatch_may_have_escaped` refuses. The key cannot be rotated or assigned after the mark. |
| AR-07 (causal wake) | `CausalWakeKey` encodes the DM/poll/explicit tuples, requires an occurrence identity where the contract says so, and hashes deterministically. |
| AR-10 (format versions) | `InferenceItem`, `InferenceAttempt` and `ToolExecution` each carry `format_version`; `serialization.py` refuses unknown or missing versions. |
| AR-11 (continuation admission) | `assert_continuation_admissible()` refuses a profile requiring opaque replay against a dialect that cannot carry it. `provider_action_for("reconcile_or_suspend") == "suspend"`. |
| AR-12 (sensitive replay) | Declared below. |

### AR-12 declaration for this PR

**The OpenAI-compatible / LM Studio adapter cannot emit `hidden_reasoning`,
`signature_or_encrypted_reasoning` or `secret_like` replay payloads.** It emits no
`ProviderOpaqueItem` at all:

- chat completions requires nothing echoed back except tool call ids, which are ordinary
  `ProviderCallRef`s;
- streamed `reasoning` / `reasoning_content` is a summary. It is never required for continuation
  and this adapter never turns it into opaque replay material. By default it is not even
  finalized into an item, matching current behaviour where reasoning is private and never
  re-enters the transcript.

`OpenAICompatibleAdapter.emits_sensitive_replay_material` is `False` and
`AdapterCapabilities.emits_opaque_replay_items` is `False`. Tests assert both, and assert the
adapter emits no opaque item across text, reasoning and tool-call streams.

No sensitive replay material is created by this PR, so none is stored ungoverned. At-rest
classification, encryption, access and retention remain owed by the first adapter PR that can
actually emit such payloads.

The generic redaction policy is nevertheless implemented now, because it is cheap and because a
policy written after the data exists is written too late:

- `ProviderOpaqueItem.__repr__`/`__str__` never show the payload at any sensitivity;
- `log_projection()` returns metadata with `payload: "<redacted>"` for logs, Hub and UI;
- the durable serialized form keeps the payload exactly — a redacted signature cannot continue a
  conversation.

## Adapter compatibility decisions

1. **Transport reuse over reimplementation.** The adapter drives
   `OpenAICompatibleProvider.stream_payload`. Two SSE parsers would drift, and the drift would
   show up as a tool call one path sees and the other does not.
2. **Canonical history, not `Message` rows.** `prepare()` renders ordered `InferenceItem`s. No
   generic Harness module imports `cerebro.models.Message`. Exactly two compatibility edges
   do: `projection.py`, which turns rows into canonical types, and `adapters/cli_external.py`,
   which hands them straight back to the unchanged `CliAgentProvider`. A test enforces this.
3. **Wire shapes stop at the dialect module.** Chat roles, `tool_calls`, `tool_call_id` and the
   assistant-then-tool sequence live only in `adapters/openai_dialect.py`.
4. **`tool_call_id` → `ProviderCallRef`, never `CerebroCallId`.** `replay_required=True`, because
   chat completions rejects a tool result whose id it did not issue. A canonical call with no
   provider ref raises rather than substituting Cerebro's identity onto the wire.
5. **Assistant text and its calls merge into one wire turn when they share a producing attempt.**
   This reproduces the current runtime's assistant-message-with-`tool_calls` shape. Calls from
   different attempts never merge.
6. **Empty assistant turns with nothing attached are dropped**, matching current behaviour.
7. **Reasoning summaries are not put on the wire.** Chat completions has no slot and never
   requires them back; this is a stated dialect decision, not an omission.
8. **The developer authority falls back to `system`**, controlled by
   `OpenAIDialectOptions.supports_developer_role` / `developer_instruction_fallback`. Today's
   servers have no developer role, and LM Studio would accept and ignore one. The fallback is a
   declared option so a future endpoint changes a flag rather than inheriting a silent downgrade.
9. **Malformed tool arguments become `TextToolInput`, verbatim.** Repairing them would hide the
   bug; inventing JSON would fabricate arguments the model never sent. The existing runtime's
   model-visible "arguments were not valid JSON" behaviour is unchanged and untouched.
10. **A tool name outside the frozen plan resolves to a reserved unresolved `ToolKey`**
    (`extension/provider_wire/unresolved/<name>`) rather than a fabricated plausible key, so the
    tool runtime can later resolve it as unavailable without risking a collision with a real
    binding.
11. **Explicit refusals**: provider-opaque items, non-text content parts, a config naming another
    dialect, a missing model, parallel tool calls, and an unregistered dialect all raise.
12. **`finish_reason="stop"` alongside finalized tool calls reports `tool_calls_pending`.** A
    server that finalized calls has not ended the turn whatever it called the reason.
13. **External CLI execution does not go through `ProviderAdapter`.** `CliExternalAgentAdapter`
    wraps the unchanged `CliAgentProvider` and reuses its prompt rendering rather than
    duplicating it. `ProviderError`/`ProviderUnavailable` propagate unchanged. Recovery
    capability declares no reconnect, no resume, no orphan reconciliation, and
    `reconcile_orphan()` returns `suspend`.
14. **No new provider SDK dependency.** `httpx` and `pydantic` were already present;
    `requirements.txt` is untouched.

## Contract ambiguities discovered

None of these is a genuine contradiction, so no piece of Phase 1A was stopped. Each is an
under-specification resolved conservatively, recorded here so PR 2 does not re-derive it
differently.

1. **`prepare()` has no attempt identity in §9, but §11 requires one before dispatch.** The frozen
   signature is `prepare(InferenceRequest, ProviderConfig)`, yet a `PreparedProviderRequest` that
   is not bound to an attempt could be dispatched twice under two identities. Resolved by adding
   a keyword-only `attempt_id` argument; the two positional parameters are unchanged.
2. **`ProviderDispatchState` collapses two different terminals.** §11 defines a linear
   `admitted → dispatch_may_have_escaped → terminal`, but `terminal` is reached both by a request
   that escaped and by one cancelled before the barrier — and §11 also requires
   `cancelled_before_dispatch` to remain distinguishable. Resolved by keeping the three state
   values exactly as specified and adding a durable `dispatch_barrier_committed` flag that
   `may_have_reached_provider` reads. No state was renamed or removed.
3. **`indeterminate` appears in two places with different meanings.** §6.3 lists it as a
   `ToolResultStatus` (model-visible evidence); §16 models it as a distinct
   `indeterminate_needs_attention` resolution rather than a known status. Resolved by honouring
   both: `ToolResultItem.status` may be `indeterminate`, while `KnownResolution` rejects it and
   `IndeterminateResolution` is a separate variant.
4. **AR-02 does not say who decides which calls are protected.** The protected set comes from
   `ToolExecution` state, which `InferenceHistory` does not own. Resolved by making
   `protected_call_ids` a caller-supplied argument to `supersede_abandoned_attempt()`; PR 2/3
   supplies it from the durable store.
5. **The contract does not state a repr/`__str__` policy for opaque payloads**, only that generic
   code must not inspect payload semantics. Resolved by redacting at every sensitivity rather than
   only the sensitive ones.
6. **`ToolBindingGeneration` is listed as an identity while §31.5 leaves its source open.**
   Resolved by keeping it an opaque prefixed identity, so PR 3 can decide how CoreTools versions
   and MCP `tools/list_changed` generations produce it without a redefinition.
7. **No canonical `ToolKey` is defined for a tool the model named but the plan does not contain.**
   Resolved with the reserved unresolved coordinate described above.

## Verification

Commands from root `AGENTS.md`, run on the final tree:

```bash
flake8 .
PYTHONPATH=. pytest -q
```

Results:

- `flake8 .` — clean, exit 0. (The base commit reported 5 × W391; those files were trimmed.)
- `PYTHONPATH=. pytest -q` — **566 passed, 3 skipped**. The base commit was 448 passed, 3 skipped,
  so the 118 new tests are additive and nothing previously green regressed. The 3 skips are the
  same pre-existing skips as on the base.

New test modules:

| Module | Tests | Covers |
| --- | --- | --- |
| `tests/test_harness_contracts.py` | 48 | identity invariants, item envelope validation, ordered mixed history, AR-02 supersession, attempt dispatch barrier and monotonicity, error kind vs transport retryability vs semantic disposition, tool uncertainty/idempotency metadata, turn finalization discriminator and attention projection, causal wake occurrence identity, request semantic hash, AR-11 admission, the collaboration-`Message` import boundary |
| `tests/test_harness_serialization.py` | 12 | round trips for every item variant, attempt and tool execution; opaque payload fidelity; missing/future `format_version` rejection for all three families |
| `tests/test_harness_openai_adapter.py` | 34 | canonical → wire for plain, tool-round and multi-call histories; attempt-scoped merging; explicit refusals; `prepare` payload shape; wire → canonical finalized events; deltas never authoritative; malformed arguments; unresolved tool names; error classification; AR-12 declaration |
| `tests/test_harness_external_agent.py` | 10 | structural separation of the two adapter protocols, no shared base class, no inference-semantics imports, event streaming, prompt-rendering preservation, error propagation, no claimed recovery, cancellation reaching the child-owning task |
| `tests/test_harness_projection.py` | 7 | F-01 projection semantics and equivalence with the current wire mapping; tool rows refused |
| `tests/test_harness_redaction.py` | 7 | repr/str/log redaction at every sensitivity, logging formatting, durable payload fidelity |

Phase 0 characterization (`tests/test_harness_characterization.py`, 46 tests) and the CLI provider
tests remain green and unmodified.

No test invokes Codex, Claude, Antigravity or Goose. The external-agent tests use a stub provider
and a `CliAgentProvider` constructed with a fake command.

## Runtime impact

**None.** `cerebro/runtime.py::AgentRuntime` remains the active production execution path and its
behaviour is unchanged. `RuntimeService._provider_for` is untouched; nothing selects a
`ProviderAdapter` or an `ExternalAgentAdapter` yet. The only production edit outside the new
package is the `stream_payload` split and the `ProviderError.status_code` attribute, both
additive.

No SQL migration, no persistence store, no `TurnRecoveryDriver`, no `StepSnapshot`, no side-effect
checkpoint, no reducer/effect cutover, no finalization redesign, no ContextManager or compaction,
no Anthropic/Gemini provider, no multi-worker fencing, no parallel tool execution, no subagents,
no external-agent crash recovery, no hard budget admission.

## Intentionally deferred to PR 2 (additive durable Harness store)

- Harness SQL schema and migration: `agent_turns`, `turn_events`, `step_snapshots`,
  `inference_items`, `inference_attempts`, `tool_executions`. `inference_items` is
  conversation-owned from its first schema (AR-03) with required turn attribution; the contract
  types already carry `agent_turn_id` and `sequence_no` for that.
- The versioned JSON envelope and column/index choices. `serialization.py` gives the per-object
  `format_version` discipline PR 2 stores; it does not choose columns.
- Causal admission uniqueness on `CausalWakeKey.serialized()` / `stable_hash()`, including the
  duplicate-delivery versus later-occurrence distinction and the recorded decline outcome (AR-07,
  F-21).
- `TurnRecoveryDriver` owned by `TurnCoordinator`: the startup scan of non-terminal turns in the
  active epoch, and durable `suspended` with a reason for anything unrecoverable (AR-01).
- Atomic turn/event/snapshot/item/attempt/call transitions under `db.run_in_writer()`.
- The `TurnStore` discovery surface for turns needing attention and their unresolved
  `CerebroCallId` / `ToolKey` / dispatch state (AR-04). The contract fields exist; the query does
  not.
- Persisting supersession metadata and supplying `protected_call_ids` from durable
  `ToolExecution` state.

Also still open, for PR 3 and later: `StepSnapshot` and the CoreTools/MCP tool-plan projection,
binding-generation sourcing, the pre-side-effect checkpoint transaction (A–L plus E2), raw tool
output storage policy, the reducer/effect cutover, atomic product finalization, and
ContextManager/compaction.

## Notes for the next implementer

- `cerebro.models.Message` is imported by exactly two modules: `projection.py` and
  `adapters/cli_external.py`. `test_no_generic_harness_module_reads_collaboration_messages`
  enforces that, and `tests/test_harness_external_agent.py` guards the equivalent boundary
  for `external_agent.py`. Keep both green.
- `ToolExecution` and `AgentTurn` have `validate_assignment` off deliberately: their transitions
  move two fields at once and the invariant only holds across the pair, so each transition
  re-checks explicitly. `InferenceAttempt` keeps assignment validation because its transitions are
  single-field-safe.
- `InferenceHistory` is in-memory. PR 2 replaces its storage, not its semantics; the supersession
  rule and the `(sequence_no, item_id)` ordering are the parts that must survive verbatim.
- The `attempt_id` keyword on `prepare()` is load-bearing. Do not make it optional to simplify a
  call site.
