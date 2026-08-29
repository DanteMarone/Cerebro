# Native Provider API Normalization Research Handoff

Issue: #204 — `Research: normalize native provider APIs for Harness v1`
Branch: `research/provider-api-normalization`
Status: in progress

## Scope

Pressure-test Cerebro's proposed provider-neutral inference abstraction against the current native/provider APIs for OpenAI Responses, Anthropic Messages, Google Gemini, DeepSeek's OpenAI-compatible API, and Cerebro's existing LM Studio/OpenAI-compatible path.

Research/design only. No runtime changes and no new SDK dependencies.

## Starting point

Read and preserve the completed Codex harness research as the architectural baseline:

- `docs/research/codex-harness/CEREBRO_HARNESS_V1.md`
- `docs/research/codex-harness/PROVIDER_ABSTRACTION.md`
- `docs/research/codex-harness/CODEX_TO_CEREBRO_GAP.md`

## Required outputs

- A provider-by-provider capability and wire-semantics comparison.
- Canonical recommendations for `InferenceRequest`, `InferenceEvent`, `InferenceError`, content parts, tool calls/results, reasoning, caching, and continuation.
- Explicit classification of provider state/opaque blocks that must be retained for correctness vs state retained only for caching/performance.
- No reconstruction or exposure of hidden chain-of-thought.
- A durable recommendation stating exactly what should change, if anything, in `CEREBRO_HARNESS_V1.md` before implementation.

## Current state

Handoff created before substantive research. Next step is to read the three baseline documents and issue #204, then verify all provider-specific claims against current first-party documentation where possible.
