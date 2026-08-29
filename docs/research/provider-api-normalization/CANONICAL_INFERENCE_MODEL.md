# Canonical Inference Model

**Issue:** #204

## Conclusion

Cerebro can support the target providers behind one provider-neutral Harness contract, but the unit of history must be an **ordered inference item**, not only a role/message transcript.

The generic runner should understand Cerebro semantics — instructions, messages, client tool calls/results, visible reasoning summaries, usage, stop status, errors — while adapters own provider wire schemas. Exact provider-originated material needed for replay must be carried as an opaque ordered item that the generic runner stores but never interprets.

This avoids both failure modes:

1. the generic runner does not become Responses-, Messages-, Interactions-, or Chat-Completions-shaped;
2. richer providers do not have to discard signed reasoning state, ordered steps, multimodal blocks, or other fidelity-critical information to fit a lowest-common-denominator chat schema.

## 1. Canonical history is an ordered item stream

Replace the tentative `instructions/messages/items` ambiguity in `CEREBRO_HARNESS_V1.md` with one clear distinction:

```text
InferenceRequest
  instructions: list[Instruction]
  history: list[InferenceItem]     # exact semantic order
  ...
```

Recommended `InferenceItem` union:

```text
MessageItem
  role: user | assistant
  content: list[ContentPart]
  provenance

ToolCallItem
  call_id: CerebroCallId
  tool_key: ToolKey
  input: ToolInput
  provider_ref?: ProviderCallRef

ToolResultItem
  call_id: CerebroCallId
  tool_key: ToolKey
  status
  content: list[ContentPart]
  provider_ref?: ProviderCallRef

ReasoningSummaryItem
  content: list[ContentPart]       # only provider-supported visible/summarized reasoning
  provenance

ProviderOpaqueItem
  provider_id
  kind
  payload                          # exact adapter-owned representation
  replay_requirement
  retention_scope
  sensitivity
```

The generic runner may sequence, persist and hand `ProviderOpaqueItem` back to the owning adapter. It must not inspect `payload` to make task/tool/completion decisions.

Why an ordered item rather than a side metadata bag:

- Gemini stateless Interactions requires model-generated `thought` and `function_call` steps in their original history position.
- Anthropic can interleave thinking and tool-use blocks and requires the latest tool-use thinking sequence unchanged.
- OpenAI Responses is natively item-oriented and reasoning items may need to be replayed alongside tool calls/results.
- DeepSeek thinking + tools requires provider reasoning state to be included in the subsequent protocol history.

Attaching all opaque material to the whole turn or to a generic `provider_hints` map loses ordering and makes safe reconstruction harder.

## 2. Instructions are semantic, provider roles are not

Use canonical governing instructions separately from conversation messages:

```text
Instruction
  authority: system | developer
  content: list[ContentPart]
  provenance
```

`MessageItem.role` should only need `user | assistant` in the core history. Tool calls/results are their own item types.

Adapters decide how instruction authority maps to their native request:

- OpenAI can preserve system/developer distinctions.
- Gemini uses `system_instruction` rather than a system chat role.
- Anthropic has a top-level/system instruction surface and provider-specific conversation rules.
- DeepSeek may accept a developer role but documents compatibility behavior that can collapse it to system semantics.
- local OpenAI-compatible models may ultimately be rendered through a chat template with weaker role fidelity.

`ModelProfile` should expose whether developer-vs-system authority is faithfully expressible. The generic runner should not invent vendor roles.

## 3. Content parts must be extensible without becoming vendor blocks

Portable v1 content should be represented as semantic media, not provider wire names:

```text
ContentPart =
  TextPart(text)
  JsonPart(value)                  # useful for structured tool/result content
  MediaPart(
      media_type: image | audio | video | document | other,
      mime_type?,
      source: inline | uri | artifact_ref,
      data/ref,
      metadata?
  )
```

A dedicated `ArtifactRef` remains useful for Cerebro-owned large outputs/files.

Do not put Anthropic `tool_use`, Gemini `thought`, or OpenAI `function_call` inside `ContentPart`; those are inference items with execution/replay semantics.

Provider-native citations, annotations, hosted-tool records and experimental blocks can stay in provider extensions until Cerebro has a cross-provider semantic use for them.

## 4. Tool calls need two identities

The tentative Harness v1 field `provider_call_id? # opaque adapter hint, not canonical identity` is too weak.

Use:

```text
CerebroCallId
  harness-generated stable identity for ToolRuntime/audit/recovery

ProviderCallRef
  provider_id
  native_call_id?
  opaque?
  replay_required: bool
```

The provider-issued ID is not Cerebro's canonical identity, but it can be **required durable protocol state**:

- OpenAI function-call output references `call_id`.
- Anthropic tool results reference `tool_use_id`.
- Gemini function results match model-issued function-call IDs.
- OpenAI-compatible Chat protocols use `tool_call_id`.

Therefore `ProviderCallRef` must be durably associated with the canonical call whenever the adapter marks it replay-required. Losing it after executing a tool can make the next request impossible to serialize correctly.

The generic runner only compares/uses `CerebroCallId`; the adapter consumes `ProviderCallRef` when constructing native history.

## 5. Tool input should not assume every provider tool is JSON-function-shaped

Cerebro client tools in v1 can remain JSON-schema function tools, which maps well across all target providers.

Still, make the call payload extensible:

```text
ToolInput =
  JsonToolInput(value)
  TextToolInput(text)
  ProviderOpaqueToolInput(provider_id, payload)
```

This avoids freezing the generic call type around one vendor's `arguments` JSON string. OpenAI already has non-function/custom/programmatic tool forms; hosted provider tools are also not Cerebro client tools.

V1 policy can expose only `JsonToolInput` to `ToolRuntime`. Other forms remain provider extensions until Cerebro deliberately supports them.

## 6. Provider opaque replay state is first-class and durably classified

Recommended metadata:

```text
ProviderOpaqueItem
  provider_id: str
  kind: str
  payload: bytes/json/string/encrypted envelope

  replay_requirement:
    required_for_correctness
    fidelity_preserving
    optimization_only

  retention_scope:
    current_tool_cycle
    current_turn
    conversation
    provider_defined

  sensitivity:
    ordinary
    hidden_reasoning
    signature_or_encrypted_reasoning
    secret_like
```

Rules:

- `required_for_correctness` is always durably checkpointed before the next external side effect or resumable boundary depends on it.
- `fidelity_preserving` should normally be durable when cheap; loss permits a semantically valid but potentially lower-quality fresh request.
- `optimization_only` may be dropped without affecting recoverability.
- `hidden_reasoning` and `signature_or_encrypted_reasoning` are not emitted to normal Hub/UI/log streams and are never parsed by generic Harness code.
- An adapter must be able to state whether an opaque item can be omitted after a scope boundary.

The generic runner never reconstructs hidden chain-of-thought. It is allowed to retain provider-returned opaque bytes/blocks verbatim when the provider requires replay.

## 7. Reasoning needs two separate concepts

Rename the current generic `ReasoningDelta` concept to avoid conflating user-visible reasoning with replay state.

Canonical displayable concept:

```text
ReasoningSummaryItem / ReasoningSummaryDelta
```

Only use this for provider-supported summarized/visible reasoning that Cerebro policy intentionally exposes.

Provider reasoning needed only for continuation belongs in `ProviderOpaqueItem`, even if a provider happens to serialize it as plaintext. DeepSeek `reasoning_content` during thinking+tool cycles is the important example: it is protocol replay state and should not automatically become UI-visible chain-of-thought.

Request control should be semantic:

```text
ReasoningPolicy
  effort?: enum/string normalized where possible
  summary_visibility: omitted | summary_if_supported
```

Model/provider-specific controls remain adapter/profile mappings. Do not promise an exact cross-provider meaning for “high” effort where providers define different scales.

## 8. Canonical event stream: deltas are live; completed items are authoritative

A generic runner needs both low-latency streaming and exact completed semantic items.

Recommended event shape:

```text
InferenceStarted

OutputItemStarted
AssistantTextDelta
ReasoningSummaryDelta
ToolCallInputDelta

OutputItemCompleted(item: InferenceItem)

UsageUpdate
ProviderMetadata
InferenceCompleted
InferenceFailed
```

`OutputItemCompleted` is the authoritative handoff from stream parser to durable history. It solves several cross-provider problems:

- partial JSON tool arguments are never executable;
- final provider call IDs/signatures can arrive late in a block/step;
- exact opaque replay blocks can be durably stored without persisting every raw token delta;
- adapters can normalize vendor event ordering without the runner branching on event names.

Convenience events such as `ToolCallStarted`/`ToolCallCompleted` can still exist, but the completed `ToolCallItem` is the executable record.

Do not persist every streamed reasoning/text delta merely for replay. Persist finalized semantic/opaque items and sparse lifecycle events.

## 9. Completion/stop semantics need a canonical status, not just “done”

Recommended completion result:

```text
InferenceCompleted
  status:
    end_turn
    tool_calls_pending
    provider_continuation_required
    max_output_reached
    content_filtered_or_refused
    incomplete
  usage
  provider_metadata?
```

This is intentionally separate from `AgentTurn` completion. Examples:

- Anthropic `tool_use` means run Cerebro tools then continue.
- Anthropic `pause_turn` can mean provider/server-tool continuation without a Cerebro ToolRuntime call.
- provider max-token/incomplete statuses should not look like successful user-turn completion.

Provider-specific stop reasons remain metadata, but the adapter must map the semantic class.

## 10. Request fields: split semantics, extensions and optimization hints

Recommended request:

```text
InferenceRequest
  model: ModelRef
  instructions: list[Instruction]
  history: list[InferenceItem]

  tools: list[ToolDefinition]
  tool_policy: ToolPolicy

  reasoning: ReasoningPolicy?
  output: OutputPolicy

  trace/task metadata

  provider_options?: ProviderOptions       # semantic, snapshotted
  cache_hints?: ProviderCacheHints         # optional optimization
```

Important distinction:

- `provider_options` can affect semantics and therefore belongs in `StepSnapshot`/durable request provenance. Example: selecting a provider-native hosted tool or context-management behavior.
- `cache_hints` may disappear on worker restart with no semantic damage.
- required replay state is **not** a request hint; it is part of ordered inference history.

## 11. `ModelProfile` vs `ProviderAdapter`

`ModelProfile` should describe behavior the Harness/planner must know before constructing a request:

```text
context/output limits
input/output modalities
tool calling: unsupported | native | emulated
tool input forms
parallel client tools
structured output
reasoning control modes
reasoning summary availability
requires/preserves opaque reasoning replay
instruction-role fidelity
stateless lossless replay support
provider-hosted tool capability names
model-specific parameter incompatibilities
```

`ProviderAdapter` owns executable/protocol behavior:

```text
auth, endpoint, headers/signing
wire schema and API version
request serialization
stream parsing
native call-ID binding
opaque replay capture/re-emission
provider-side continuation/cache handles
error mapping
provider dialect quirks / silently ignored fields
transport-safe retries
```

Some facts are provider+endpoint-wide rather than model-specific. Keep those in adapter/dialect capabilities and intersect them with `ModelProfile`.

## 12. Error model

The existing Harness v1 taxonomy is close but should add explicit provider permission and billing/quota distinctions:

```text
InferenceErrorKind
  transient_transport
  rate_limited
  quota_or_billing
  authentication
  permission_denied
  invalid_request
  request_too_large
  context_exhausted
  provider_overloaded
  provider_internal
  cancelled
  policy_denied             # Cerebro/provider safety policy, not authz
  unsupported
  fatal_internal
```

Useful fields:

```text
provider_code
provider_message
request_id
retry_after
retryable
retry_disposition:
  same_request_after_backoff
  after_auth_refresh
  after_compaction
  fresh_attempt_from_checkpoint
  not_retryable
```

The runner still decides replay safety from durable progress. An adapter cannot decide by HTTP code alone whether repeating a partially streamed inference would duplicate semantic work.

`context_exhausted` may sometimes be derived from a provider-specific `invalid_request`/500/limit error, while `request_too_large` is byte/transport-size failure. Keeping them distinct improves recovery.

## 13. Stateful provider IDs are not Cerebro identity

`previous_response_id`, `conversation`, `previous_interaction_id`, LM Studio sessions and similar handles can be retained by the adapter, but only in two categories:

```text
ContinuationHandle
  convenience/optimization if full durable replay exists
  correctness dependency only if no lossless stateless replay exists for the chosen feature
```

For the reviewed core client-tool flows:

- OpenAI Responses documents stateless replay.
- Gemini Interactions documents stateless replay if all generated steps are preserved exactly.
- Anthropic Messages is fundamentally client-history driven for ordinary client tools.
- DeepSeek Chat/Responses compatibility is client-history driven.
- Cerebro's LM Studio Chat path is client-history driven.

Therefore provider conversation IDs should not become `AgentTurn`, channel, thread or canonical history identity.

## 14. V1 invariant

A stronger portability/recovery test than the current “lose cache IDs” rule is:

> At every durable inference boundary, Cerebro must hold enough canonical semantic history **plus required adapter-owned replay items and native call references** to construct a provider-valid continuation without depending on process memory. Optional cache/session handles may improve performance but cannot be the only copy of correctness state.

This preserves Cerebro as the durable source of truth without pretending all provider state is semantically disposable.
