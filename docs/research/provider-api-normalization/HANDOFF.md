# Native Provider API Normalization Research Handoff

Issue: #204 — `Research: normalize native provider APIs for Harness v1`

Branch: `research/provider-api-normalization`

Status: **research complete; ready for reconciliation with Goose issue #203 before Harness v1 implementation**

Research date: 2026-08-29

## Scope completed

Pressure-tested Cerebro's proposed provider-neutral inference abstraction against current first-party documentation/current behavior for:

- OpenAI Responses API;
- Anthropic Messages API, tool use, thinking, prompt caching and context editing;
- Google Gemini Interactions API, function calling, thought signatures and caching;
- DeepSeek current OpenAI-compatible Chat/Responses behavior and thinking mode;
- Cerebro's existing LM Studio/OpenAI-compatible implementation plus current LM Studio API/tool behavior.

Research/design only. **No Cerebro runtime implementation was modified and no SDK dependency was added.**

## Baseline read before research

- `docs/research/codex-harness/CEREBRO_HARNESS_V1.md`
- `docs/research/codex-harness/PROVIDER_ABSTRACTION.md`
- `docs/research/codex-harness/CODEX_TO_CEREBRO_GAP.md`
- issue #204

The Codex-derived architecture remains conceptual inspiration only; this pass did not copy provider or harness implementation code.

## Deliverables

All issue #204 deliverables now exist under this directory:

1. `HANDOFF.md`
2. `API_BASELINES.md`
3. `CANONICAL_INFERENCE_MODEL.md`
4. `OPENAI_MAPPING.md`
5. `ANTHROPIC_MAPPING.md`
6. `GEMINI_MAPPING.md`
7. `DEEPSEEK_AND_OPENAI_COMPATIBLE.md`
8. `CAPABILITY_MATRIX.md`
9. `EDGE_CASES_AND_LOSSLESSNESS.md`
10. `HARNESS_V1_RECOMMENDATIONS.md`

## Main conclusion

The broad Harness v1 architecture is correct: keep a Cerebro-owned generic runner, `ProviderAdapter`, `ModelProfile`, immutable `StepSnapshot`, Cerebro-controlled ToolRuntime and Cerebro-owned durable semantic state.

The current type sketch needs one important refinement before implementation: **canonical inference history must be an ordered item stream with first-class provider-opaque replay items, not primarily a role/message list plus non-durable provider hints.**

Native APIs prove that some provider-originated state is required for valid/fidelity-preserving continuation:

- OpenAI reasoning/output items in stateless reasoning/tool continuations;
- Anthropic signed/redacted thinking blocks during thinking + tool use;
- Gemini signed `thought` steps in stateless Interactions history;
- DeepSeek `reasoning_content` during thinking + tool flows;
- provider-issued native client-tool call IDs needed to correlate results.

This state is not Cerebro conversation identity and generic Harness code must not interpret it. It is exact adapter-owned replay material that must be durably retained when marked required.

By contrast, provider conversation/cache fast paths remain optional wherever a lossless stateless replay path exists:

- OpenAI `previous_response_id` / conversation resource;
- Gemini `previous_interaction_id`;
- LM Studio Responses prior-response state;
- prompt-cache keys/entries, implicit caches and local KV caches;
- HTTP/WebSocket connection/session state.

## Canonical model recommendation

Use:

```text
Instruction(authority=system|developer, content, provenance)

InferenceItem =
  MessageItem(user|assistant, content, provenance)
  ToolCallItem(CerebroCallId, ToolKey, ToolInput, ProviderCallRef?)
  ToolResultItem(CerebroCallId, ToolKey, status, content, ProviderCallRef?)
  ReasoningSummaryItem(content, provenance)
  ProviderOpaqueItem(provider_id, kind, exact payload,
                     replay_requirement, retention_scope, sensitivity)
```

Keep native provider call IDs in durable `ProviderCallRef`s when required. They are not canonical ToolRuntime identity, but they are not disposable hints either.

Split provider state into:

```text
provider_options     # semantic provider-specific request configuration; snapshotted
cache_hints          # optional optimization/performance state
ProviderOpaqueItem   # exact ordered replay state; durable when required
ProviderCallRef      # native correlation state; durable when required
```

## Reasoning/chain-of-thought rule

Do not expose or reconstruct hidden chain-of-thought.

Use `ReasoningSummaryItem` / `ReasoningSummaryDelta` only for provider-supported summarized/visible reasoning that Cerebro policy intentionally exposes.

Provider reasoning needed only for replay is stored as sensitive opaque state and excluded from normal Hub/UI/log output. This includes DeepSeek plaintext `reasoning_content` when it is required to continue a tool flow.

## Strongest execution invariant added by this research

A side-effecting Cerebro tool must not execute merely because enough streaming fragments have arrived to infer its arguments.

Required sequence:

```text
provider stream
  > adapter finalizes ordered output items
  > persist completed ToolCallItem + ProviderCallRef
  > persist all preceding required ProviderOpaqueItems
  > commit executable inference/replay checkpoint
  > only then execute ToolRuntime side effects
```

This closes a crash-consistency hole where a tool side effect could exist but the provider signature/reasoning state required to continue the turn was never durably captured.

## Error-model correction

Add at least these canonical classes to the current Harness v1 list:

- `quota_or_billing`;
- `permission_denied`;
- `request_too_large`.

Keep them distinct from `rate_limited`, `authentication`, `policy_denied`, and `context_exhausted` because current provider APIs expose materially different recovery semantics.

## Compatibility-adapter rule

Treat “OpenAI-compatible” as a **wire dialect**, not a capability claim.

DeepSeek currently documents unsupported Responses fields that are silently ignored or given non-OpenAI semantics. LM Studio tool calling may be native or emulated/default depending on the loaded model/template.

Adapters should validate requested canonical semantics against known adapter-dialect + `ModelProfile` capabilities before serialization. Do not infer support from a request being accepted.

Recommended `ModelProfile` additions include:

- `tool_calling_mode: unsupported | emulated | native`;
- reasoning control modes / reasoning-summary support;
- required opaque replay behavior;
- instruction-role fidelity;
- stateless-lossless-replay support;
- model-specific parameter incompatibilities.

## Exact changes recommended for `CEREBRO_HARNESS_V1.md`

`HARNESS_V1_RECOMMENDATIONS.md` contains the complete 14-point patch plan. In short, before Phase 1:

1. resolve Section 6 to ordered `InferenceItem` history;
2. make opaque replay classes explicit/durable;
3. replace non-durable `provider_call_id` hint semantics with durable `ProviderCallRef` where required;
4. rename `ReasoningDelta` to summary-specific semantics;
5. add authoritative `OutputItemCompleted` events;
6. add canonical inference completion statuses including provider continuation;
7. split provider semantic options, cache hints, and replay state;
8. add provider replay checkpoint state to `StepSnapshot` and persist it before tool side effects;
9. expand error taxonomy;
10. enrich `ModelProfile` beyond booleans;
11. add explicit compatibility-dialect validation rules;
12. pin active required replay items against compaction;
13. define provider/model switching as a fresh semantic boundary when opaque continuation state is active;
14. strengthen Phase 1/Phase 6 acceptance fixtures around stateless recovery and opaque replay.

Do not otherwise rewrite the Harness v1 component architecture.

## Provider-specific resume notes

### OpenAI

Responses supports provider-side continuation and stateless manual replay. Treat response/conversation IDs as optional fast paths if full required output history is durable. Function `call_id` and required reasoning items are durable replay state in active continuations.

### Anthropic

Thinking + tool use is the clearest hard correctness case: latest thinking/redacted-thinking blocks must be returned complete/unmodified and signatures are opaque. `pause_turn` is provider-controlled continuation, not a Cerebro client tool call.

### Gemini

Use current **Interactions API** as the native target, not legacy `generateContent`. In stateless mode all model-generated steps, including signed `thought` and `function_call` steps, must be replayed exactly. `previous_interaction_id` is optional if that history is durable.

### DeepSeek

Current V4 docs are moving quickly. The dated 2026-08-13 V4-Pro GA release says native Responses support, while some compatibility/pricing pages still carried pre-GA text about V4-Pro support being upcoming. `API_BASELINES.md` records this source-version conflict and uses the newer release for availability while using the compatibility guide for wire semantics where not contradicted.

DeepSeek thinking + tools requires `reasoning_content` replay and can return 400 when it is missing. Treat the field as sensitive opaque replay state, not displayable chain-of-thought.

### LM Studio

Keep Cerebro's current `/v1/chat/completions` behavior as the Phase 1 compatibility target. The immediate goal is to remove protocol state from `Message.meta_json` by translating workspace rows to canonical inference items. LM Studio Responses/stateful features can be evaluated later as adapter features, not as canonical identity.

## Commit trail from this research pass

Key commits, in order:

- `0aeb25a9bb76309688eff67528114a4119cb17b6` — initialize handoff
- `8a1eb2081a88956db062fdedfc62b54496489daf` — initial API baselines
- `c60bd874dab5a3dd509675ac890bde85b4ce52e4` — canonical inference model
- `4834878a2b0c57d02046287bbe1050cf528f4e1d` — OpenAI mapping
- `0af4b52b161d2710b0dabf079b5af41bca73371d` — Anthropic mapping
- `53d12234bf24e95ee23066112d40582645ae29e9` — Gemini mapping
- `e6269ce32b32e4785aa2a8a240c3a9ea1742ecd5` — DeepSeek/OpenAI-compatible mapping
- `76f4dd2256d11b41d4ad1b46abdd618cc1ce12b9` — capability matrix
- `3473496e4ca0717d9ef2cac53752eb4e0b281567` — edge cases/losslessness
- `a0b31b952e39ab18123a0f5bcc007a2d2edaef99` — Harness v1 recommendations
- `e36c90159fb690a067bc7a70ea2fea043071d565` — provider source/freshness cleanup

This handoff update is the final research commit after those entries.

## What remains

No further broad native-provider research is needed for issue #204 before reconciliation.

Next durable step is **not implementation yet**: reconcile `HARNESS_V1_RECOMMENDATIONS.md` with the independent Goose findings from issue #203, then fold the agreed corrections into `docs/research/codex-harness/CEREBRO_HARNESS_V1.md` before opening the Phase 1 implementation PR.

Issue #204 can be considered research-complete; leaving it open until the coordinating/reconciliation pass is reasonable because the issue explicitly says this output and Goose's findings will be reconciled before implementation.
