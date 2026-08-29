# Gemini Interactions Mapping

**Baseline:** Google Gemini Interactions API and related first-party docs accessed 2026-08-29. Main/API-version docs were last updated 2026-08-26 UTC. See `API_BASELINES.md`.

## Bottom line

Gemini Interactions validates an item/step-oriented Cerebro history model more strongly than a message abstraction. Google explicitly supports both stateful and stateless operation. Stateless operation is lossless only if Cerebro preserves **all model-generated steps exactly as returned**, including signed `thought` steps and function calls.

Therefore `previous_interaction_id` is optional server-side continuation state, but signed thought steps are correctness-relevant durable replay material when Cerebro uses stateless recovery.

## Why Interactions is the baseline

Google's current documentation says Interactions became the default Gemini API interface in June 2026. It is the current agent-capable API with:

- ordered steps;
- stateful or stateless continuation;
- custom function calling;
- provider-hosted tools;
- thought signatures;
- streaming step events;
- background execution and managed-agent features.

`generateContent` remains relevant for compatibility/legacy behavior, but Cerebro should design the native Gemini adapter against Interactions, not freeze the generic contract around the legacy Content/Part wire model.

## Request mapping

| Cerebro semantic | Gemini Interactions mapping | Notes |
| --- | --- | --- |
| `ModelRef.model_id` | `model` | Interactions can also target managed agents; those are provider extensions. |
| `Instruction` | `system_instruction` | Re-specify on each interaction; it is interaction-scoped. |
| `MessageItem` | user/model content steps | Adapter owns exact step/content encoding. |
| `ToolDefinition` | custom function declaration | Client JSON-function tools map cleanly. |
| `ToolCallItem` | `function_call` step | Preserve native call ID. |
| `ToolResultItem` | `function_result` step | Match native function-call ID. |
| `ReasoningSummaryItem` | thought summary/content only if provider exposes it and policy allows | Separate from replay signature. |
| `ProviderOpaqueItem` | exact `thought` step/signature and any provider step required for stateless continuation | Ordered and durable. |
| `provider_options` | built-in tools, background, managed agents/environment, provider-specific generation controls | Not generic ToolRuntime by default. |
| `cache_hints` | implicit cache observations/legacy explicit cache handles | Optimization only. |

## Stateful vs stateless continuation

Stateful mode:

```text
store=true
previous_interaction_id=<prior id>
```

The server retains interaction history and automatically manages thought blocks/signatures. Google notes that interaction-scoped controls such as tools, system instruction and generation configuration must still be supplied as appropriate for each new interaction.

Stateless mode:

```text
store=false
input=<full accumulated step history>
```

Google explicitly requires preservation and resend of all model-generated steps exactly as received, including `thought` and `function_call` steps. This is the mode Cerebro should use as the architectural recovery reference even if the adapter normally uses stateful continuation for latency/token convenience.

Classification:

```text
previous_interaction_id
  > optional ContinuationHandle when full step history is durable

model-generated thought/function/provider steps required by stateless replay
  > durable ordered inference/replay items
```

This lets a new Cerebro worker continue without trusting Google's interaction retention window as the only copy of state.

## Thought signatures

Google documents thought signatures as encrypted representations of internal reasoning that are required to maintain reasoning continuity.

In Interactions stateless mode:

- all `thought` blocks must be resent exactly as received;
- they must not be removed or modified;
- signatures are provider state, not something the application should interpret.

Cerebro mapping:

```text
thought step exact payload
  > ProviderOpaqueItem(
       provider_id="gemini",
       kind="thought_step",
       replay_requirement=required_for_correctness,
       sensitivity=signature_or_encrypted_reasoning
     )

provider-supported thought summary, if separately exposed/approved
  > ReasoningSummaryItem
```

The generic Harness must not decode, synthesize or reconstruct thought signatures. It only preserves exact provider output and its ordered position.

This is cleaner than the legacy `generateContent` rules, where signatures are embedded in parts and parallel/sequential call placement creates additional positional edge cases. Interactions' dedicated thought steps are another reason to use the current API as the native adapter target.

## Function calling

Custom function calls have provider-issued IDs; function results must reference the corresponding ID. Gemini supports parallel calls and sequential/compositional calling.

Mapping:

```text
function_call step
  > ToolCallItem(
       call_id=<CerebroCallId>,
       tool_key=<resolved ToolKey>,
       input=JsonToolInput(...),
       provider_ref=ProviderCallRef(
          provider_id="gemini",
          native_call_id=<Gemini function call id>,
          replay_required=true
       )
     )

function_result
  > ToolResultItem using same CerebroCallId
  > adapter serializes native call-id linkage
```

In stateless mode, the prior function-call step itself remains in history exactly as received; a normalized call item may therefore carry an attached/exact provider replay representation where the wire step contains fields not safely reconstructible from canonical fields alone.

Parallel calls remain multiple canonical calls from one inference. ToolRuntime decides scheduling according to snapshotted tool annotations/policy, not Gemini's wire ordering alone.

## Built-in tools and mixed tool flows

Gemini built-in tools execute provider-side. Custom functions execute client-side. Current docs allow mixed flows that can produce provider-hosted tool steps, signed thought state and a client function call in the same interaction.

Cerebro should distinguish:

```text
custom client function
  > canonical ToolCallItem / ToolResultItem

provider built-in tool call/result
  > ProviderOpaqueItem or provider-extension semantic item
     unless Cerebro deliberately promotes that built-in into a portable abstraction
```

The generic runner may retain/forward the provider-owned steps and enforce turn budgets/cancellation without pretending it executed the provider tool.

## Streaming

Current Interactions streaming is organized around typed interaction/step events (for example interaction creation and step deltas/completion).

Recommended adapter mapping:

```text
interaction created/started
  > InferenceStarted

text/content step delta
  > AssistantTextDelta

provider-supported thought-summary delta
  > ReasoningSummaryDelta

function input delta, if exposed incrementally
  > ToolCallInputDelta

completed step
  > OutputItemCompleted(canonical InferenceItem)

interaction completed
  > InferenceCompleted

SSE error event
  > InferenceFailed
```

The completed step is authoritative. Required signatures/IDs can be captured there without making every raw streaming fragment durable.

## Caching

Current Interactions supports implicit caching. Google reports cached token usage but does not require a client cache object to preserve semantics.

Legacy `generateContent` supports explicit cached content; that remains an adapter/provider feature if Cerebro ever uses the legacy endpoint.

Classification:

```text
implicit/explicit cache identity   optimization only
cache token accounting             normalized usage metadata
cache policy/provider config       model/provider option
```

A cache miss must not prevent reconstructing the request.

## Background and managed-agent state

Interactions also supports background execution and managed agents/environments. Those introduce provider resource lifecycle/state beyond ordinary model inference.

Do not force these into Harness v1 core just because they share the endpoint. Treat them as provider extensions with explicit capability gates. If Cerebro later adopts them, any provider resource ID required for a running background/managed-agent operation should be durable operational state, but it is not generic conversation identity.

One concrete rule already documented: a `previous_interaction_id` cannot be chained from an interaction that is still in progress. The adapter must map such provider lifecycle restrictions rather than leaking them into generic runner branches.

## Errors

The current Interactions error reference gives machine-readable codes that map well to canonical errors:

- `invalid_request`, `parameter_unknown` > `invalid_request`;
- `authentication` > `authentication`;
- `permission_denied` > `permission_denied`;
- `not_found` / `model_not_found` > `invalid_request` or `unsupported` depending context;
- `rate_limit_exceeded` > `rate_limited`;
- `quota_exceeded` / billing prerequisite failures > `quota_or_billing`;
- `cancelled` > `cancelled`;
- `api_error` > `provider_internal`;
- `service_unavailable` > `provider_overloaded`/transient;
- `deadline_exceeded` > transient/provider timeout;
- `unimplemented` > `unsupported`.

Errors can appear as standard HTTP responses or typed SSE error events.

Legacy `generateContent` sometimes reports oversize/context failures through broad backend errors; the adapter should use provider details plus token budgeting to distinguish `context_exhausted` when reliable.

## ModelProfile implications

Gemini model profiles should include:

- context/output limits;
- input modalities (including image/audio/video/document where supported);
- custom function tools and parallel calls;
- structured output and tool+structured-output compatibility;
- thinking level/summary support;
- signed thought replay requirement;
- built-in tool support per model;
- any tool combinations or preview-only constraints.

The adapter/dialect owns whether the selected API version/endpoint is Interactions v1/v1beta and exact wire fields. ModelProfile should not carry URL/version serialization logic.

## State classification

### Required for correctness in stateless thinking/tool flows

- exact model-generated `thought` steps/signatures;
- exact function-call step/provider ID needed to correlate a function result;
- any provider-generated step Google requires to be resent unchanged in the chosen mixed/provider-tool flow.

### Optional continuation state

- `previous_interaction_id`, provided Cerebro retained the full replayable step history;
- provider interaction resource ID after completed ordinary inference, except where needed for explicit background/resource operations.

### Caching/performance only

- implicit cache state;
- legacy explicit cache object/handle when canonical source content remains available;
- HTTP connection/session state.

## Harness v1 pressure-test result

Gemini requires these pre-implementation corrections:

1. make canonical inference history an ordered item/step sequence;
2. make exact opaque replay items durable when marked required;
3. make provider native call IDs durable references;
4. keep provider continuation IDs optional when lossless stateless replay exists;
5. model provider-hosted tools as extensions, not fake Cerebro client calls;
6. prefer current Interactions API as the first genuinely non-OpenAI-shaped implementation validation target or co-equal with Anthropic.
