# Cerebro Harness v1

**Status:** Proposed implementation architecture after the Codex harness mining pass.

**Scope:** Design only. This research branch does not modify Cerebro runtime behavior.

**Cerebro baseline:** `research/codex-harness-mining` through `e938510dacda69a68b36ea4080e9e3c132e1ff07` before this document.

**Codex reference baseline:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

All Codex-derived ideas remain **conceptual inspiration only**. Harness v1 should be independently implemented in Cerebro's own architecture and naming.

## 1. Goal

Harness v1 is the smallest internal runtime that lets Cerebro call materially different model-provider APIs directly while preserving the engineering boundaries that make mature coding/agent harnesses reliable.

It should make this true:

> A Cerebro agent is a durable Cerebro identity operating on durable Cerebro workspace/task state. A provider model is a replaceable inference engine used by that agent for one step at a time.

Harness v1 is successful when native/provider-direct agents can approach vendor-harness reliability without making the provider SDK, process lifetime or provider conversation ID the source of truth.

## 2. Keep the product architecture above the harness

Harness v1 does **not** replace:

- `Hub` and WebSocket fanout;
- channels, teams, memberships and attribution;
- autonomous polling/mention behavior;
- completion-ordered final chat messages;
- tasks, cron jobs, budgets, audit events and distributed leases;
- agent profiles/homes/memory as product concepts;
- CLI-backed Codex/Claude/Antigravity agents during migration.

The harness sits beneath `AgentRuntime`'s product-facing orchestration role.

```text
Cerebro workspace
  channel/message/task wakes an agent
        |
        v
AgentRuntime / TurnCoordinator
        |
        v
Cerebro Harness v1
  durable AgentTurn
  ContextManager
  StepSnapshot
  ProviderAdapter
  ToolRuntime
  CompletionPolicy
        |
        v
final Cerebro message + task state
```

## 3. Explicit non-goals for v1

Do not block Harness v1 on:

- a JavaScript/Python Code Mode runtime that can make nested tool calls;
- vector/embedding tool search;
- remote/server-side compaction;
- reproducing every Codex hook;
- hidden sub-agent trees as the primary collaboration UX;
- every provider-specific feature;
- distributed multi-host workers;
- token-by-token durable event storage;
- automatic reviewer agents on every turn;
- copying any Codex source implementation.

Design seams may allow these later.

## 4. The v1 component map

Recommended logical components:

```text
TurnCoordinator
  creates/loads durable AgentTurn
  owns high-level run lifecycle
  commits final workspace message

ContextManager
  maintains canonical inference history + WorldState
  creates model-budgeted request context
  compacts/reconstructs when needed

StepSnapshot
  immutable exact state for one model sample + resulting tool calls

ProviderRegistry
  ProviderAdapter implementations
  ModelProfile resolution

InferenceRunner
  streams one provider inference
  normalizes events/errors

ToolCatalog
  canonical identities/specs/source provenance

ToolPlanner
  direct/deferred/hidden request exposure

ToolRuntime
  validates call against StepSnapshot
  permissions/cancel/timeout/execute
  produces typed ToolResult

CompletionPolicy
  decides allow | continue_with_feedback | fail

TurnStore
  durable AgentTurn + sparse events/checkpoints
```

These may begin as modules rather than classes/services. The boundary matters more than object count.

## 5. Suggested Python package shape

An incremental organization that fits the current repo:

```text
cerebro/
  harness/
    __init__.py
    types.py             # canonical inference/tool/error types
    runner.py            # generic model > tool > model loop
    snapshot.py          # immutable StepSnapshot
    context.py           # ContextManager + compaction/reconstruction
    events.py            # durable event/checkpoint types
    completion.py        # CompletionPolicy
    recovery.py          # retry/recovery decisions
    model_profiles.py    # ModelProfile resolution
    tools/
      catalog.py
      planner.py
      runtime.py
      outputs.py

  providers/
    base.py              # evolves to ProviderAdapter
    openai_compatible.py # compatibility adapter
    ...native provider...
```

Existing `cerebro/runtime.py` can become the product adapter/coordinator and call into `harness.runner` rather than being deleted at the start.

## 6. Canonical inference types

The current generic provider API consumes database `Message` rows. Harness v1 should insert a provider-neutral inference representation between workspace storage and provider adapters.

A practical v1 model:

```text
ModelRef
  provider_id: str
  model_id: str

ContentPart
  text
  image
  file/artifact reference
  optional provider-opaque part for lossless replay when required

InferenceMessage
  role: system | developer | user | assistant
  content: list[ContentPart]
  provenance metadata

InferenceToolCall
  call_id
  ToolKey
  arguments
  provider_call_id?       # opaque adapter hint, not canonical identity

InferenceToolResult
  call_id
  ToolKey
  model_content
  status

InferenceRequest
  model: ModelRef
  instructions/messages/items
  exposed tool definitions
  tool policy
  reasoning/output controls
  output schema?
  trace/task metadata
  provider_hints?         # explicitly non-durable optimization hints
```

Tool calls/results can either be separate input-item variants or represented beside message items. The critical rule is that they are **native canonical types**, not JSON hidden in `Message.meta_json`.

### 6.1 Preserve provider-specific losslessness without polluting generic control flow

Some providers may require opaque blocks/signatures/IDs to be replayed for correctness or caching. Allow an adapter-owned `opaque` field with a provider namespace, but generic Harness code must not inspect it for task semantics.

```text
opaque = {
  provider: "anthropic",
  kind: "...",
  payload: ...
}
```

If losing opaque data changes correctness rather than only performance, it must be checkpointed durably with the inference history.

## 7. ProviderAdapter contract

Replace the current smallest-common-denominator `Provider.stream(messages, tools, params)` with a richer semantic adapter.

Conceptually:

```text
ProviderAdapter
  provider_id

  discover_models() -> list[DiscoveredModel]
  resolve_profile(model_id) -> ProviderModelCapabilities

  prepare(request, auth/context) -> PreparedProviderRequest
  stream(prepared, cancel_token) -> AsyncIterator[InferenceEvent]

  classify_error(exc/response) -> InferenceError
  close()
```

Provider-owned responsibilities:

- authentication/refresh/signing;
- native endpoint/headers/wire schema;
- request serialization;
- stream parsing;
- provider-specific continuation/cache handles;
- native tool-call translation;
- raw provider error mapping;
- provider model discovery/capability hints;
- adapter-local HTTP transport retry when replay is unquestionably safe.

Harness-owned responsibilities:

- durable turn identity;
- context/history meaning;
- tool semantics and authorization;
- semantic retry/recovery policy;
- compaction;
- acceptance/completion;
- collaboration/workspace state.

### 7.1 Canonical inference events

Expand the useful existing `Delta` pattern into something close to:

```text
InferenceStarted
AssistantTextDelta
ReasoningDelta          # visibility/storage policy belongs to Cerebro
ToolCallStarted
ToolCallArgumentsDelta
ToolCallCompleted
UsageUpdate
ProviderMetadata
InferenceCompleted
```

The adapter should normalize provider-native streams into these events. The generic runner should not branch on provider names.

### 7.2 Canonical errors

At minimum:

```text
InferenceErrorKind
  transient_transport
  rate_limited
  authentication
  invalid_request
  context_exhausted
  provider_overloaded
  provider_internal
  cancelled
  policy_denied
  unsupported
  fatal_internal
```

Fields should include retryability, retry-after when known, provider code/message, and whether a retry may safely reuse the same semantic request.

## 8. ModelProfile

Cerebro needs a model behavior object independent of the provider adapter.

V1 fields should include only things the harness actually needs:

```text
ModelProfile
  model_ref
  context_window_tokens
  usable_context_tokens / compaction_threshold
  max_output_tokens

  supports_tools
  supports_parallel_tools
  supports_images
  supports_files
  supports_structured_output
  supports_reasoning_controls
  supports_native_web_search

  default_reasoning
  default_output_verbosity
  tool_name constraints
  tool/output truncation defaults
  optional model-specific instruction additions
```

Resolution order can be:

```text
provider discovery/capabilities
  + Cerebro maintained profile/override
  + agent-specific requested settings
  + turn/task policy
  > effective StepSnapshot
```

Never use a bare model-name prefix throughout the runner as the long-term capability system.

## 9. Durable AgentTurn

The collaboration-level `turn_id` currently represents the conversational impulse. Preserve that and introduce a distinct durable **agent execution turn** because multiple agents can act under one shared conversation turn.

Suggested table:

```sql
agent_turns(
    id TEXT PRIMARY KEY,
    conversation_turn_id TEXT NOT NULL,
    root_agent_turn_id TEXT,
    parent_agent_turn_id TEXT,
    trigger_message_id INTEGER,
    channel_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_id TEXT,

    provider_id TEXT,
    model_id TEXT,
    status TEXT NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 0,

    failure_kind TEXT,
    failure_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT
)
```

V1 statuses:

```text
queued
running
waiting_tool
waiting_retry
suspended
completed
cancelled
failed
```

Do not make `messages` carry these semantics.

## 10. Sparse durable turn events

Add an append-only execution/audit stream sufficient for reconstruction without persisting every streamed token.

Suggested events:

```text
turn.created
turn.started
step.snapshot_committed
inference.started
inference.completed
inference.failed

tool.call_started
tool.call_completed
tool.call_failed

context.compacted
completion.blocked
turn.suspended
turn.resumed
turn.cancelled
turn.completed
turn.failed
```

Payloads should use versioned JSON schemas or typed serializer models.

### 10.1 What not to persist

Do not put every `TextDelta`/reasoning delta in `turn_events`. Those remain live Hub/UI events unless a provider requires opaque streamed fragments for durable correctness.

### 10.2 Projection versus log

`agent_turns` is the current indexed projection. `turn_events` is the execution audit/reconstruction log. Final shared answer remains a `messages` row.

## 11. StepSnapshot: the strongest v1 invariant

For every provider sample, create an immutable `StepSnapshot` containing the exact state used to build that request.

Conceptually:

```text
StepSnapshot
  agent_turn_id
  step_index
  model_profile_version / ModelRef

  canonical inference history checkpoint/version
  context/world-state version
  token budget

  ToolPlanSnapshot
  permission profile/version
  workspace/environment/cwd snapshot

  task/completion policy version
  trace/root/parent metadata
```

The model-visible tool definitions and the executable bindings must be derived from the same `ToolPlanSnapshot`.

A tool call generated by inference step 3 executes against step 3's snapshot even if an MCP server reconnects or an administrator changes an allowlist before the tool finishes.

If the old binding is no longer executable, the terminal result is `unavailable/stale binding`; the runtime does not silently reinterpret the call using the new catalog.

## 12. Tool model

### 12.1 Canonical identity

```text
ToolKey
  source_type: core | mcp | connector | extension
  source_id: str
  namespace: str
  name: str
```

Provider wire names are generated from `ToolKey` late and mapped back through a collision-free table stored in `ToolPlanSnapshot`.

### 12.2 Definition

```text
ToolDefinition
  key
  title/description
  input_schema
  output_schema?
  annotations
  provenance/source metadata
  exposure eligibility
```

Useful annotations:

- read-only;
- destructive;
- open-world/network;
- parallel-safe;
- expected latency;
- default model-output budget;
- artifact-producing.

Annotations are hints/policy inputs, not trust boundaries.

### 12.3 Binding

```text
ToolBinding
  definition
  executor reference/source version
  permissions/policy version
  catalog_version
```

### 12.4 Result

```text
ToolResult
  call_id
  key
  status: success | error | cancelled | denied | timeout | unavailable
  structured/raw result or artifact reference
  model_content: typed bounded ContentParts
  original_size/token estimate
  truncation/omission metadata
  timing
  error details
```

Every admitted call gets exactly one terminal result.

## 13. ToolCatalog and planning

`ToolCatalog` is the full currently connected/installed universe. `ToolPlanSnapshot` is what one inference step can see/use.

Initial exposure modes:

```text
hidden
 direct
 deferred
```

Tool planning intersects:

```text
catalog
  intersect agent allowlist
  intersect workspace/team policy
  intersect provider/model capabilities
  intersect task/permission profile
  intersect source health/availability
  > request exposure
```

### 13.1 Collision policy

- core privileged/control identities are reserved;
- duplicate canonical identities fail registration or quarantine the external duplicate;
- external tools never replace core tools;
- provider wire-name collisions are detected during snapshot construction and deterministically escaped/disambiguated or rejected;
- mapping is saved in the snapshot.

### 13.2 Deferred search

V1 can ship direct tools first, but the data model should support deferred exposure immediately.

When implemented:

```text
search_tools(query, limit)
  searches only deferred tools in this StepSnapshot
  ranks name/namespace/description/input-field text
  returns exact loadable schemas
```

Use lexical/BM25-like ranking first. No vector service required.

## 14. Tool output budgeting

Separate the full result from what enters model context.

Default policy for large text/log output:

```text
raw result
  > durable artifact/store or bounded audit retention

model result
  > status/timing header
  > head + tail / middle truncation
  > explicit original-size + omitted marker
```

For structured/multimodal output, budget parts by type rather than flattening everything to one string.

The model must always be told when data was omitted.

Later, expose artifact read/slice tools so an agent can fetch the missing middle deliberately.

## 15. ContextManager v1

The existing `ContextBuilder` can feed the first version, but Harness v1 should introduce a canonical stateful layer around it.

### 15.1 Typed context sections

At minimum:

```text
identity/persona
operating manual / developer policy
workspace/channel frame
project instructions
permissions/tool policy summary
active task/plan state
agent memory/scratchpad
conversation history
world/environment state
```

Each section should carry:

```text
section_id
content
provenance
version/hash
priority
trimmable/replaceable flags
```

### 15.2 World state

Do not resend large identical mutable state forever. Maintain canonical current state and, when useful, record changes such as:

- cwd/workspace;
- project instructions;
- permissions;
- model/provider;
- tool catalog/exposure summary;
- current task;
- environment/time selections.

Harness v1 does not require an elaborate diff protocol on day one. It does require an explicit versioned source of truth so compaction/recovery can reinject current state.

### 15.3 Accurate enough token budgeting

Replace global four-chars-per-token budgeting with `ModelProfile`-specific estimators where available, retaining a conservative fallback for unknown/local models.

Budget categories separately:

```text
required governing context
active task/state
recent conversation
memory/retrieval
large tool outputs
reserved output headroom
```

The provider should not be the first component to discover that the request is oversized.

## 16. Compaction v1

Compaction should be a durable context transition, not only “drop oldest rows.”

Trigger before the usable context threshold is crossed.

Minimal algorithm:

1. choose an old history prefix that can be summarized;
2. create a compacting inference request using the active model or configured compaction model;
3. store a typed compaction checkpoint containing summary + covered history/event range;
4. retain recent real user/agent exchanges explicitly;
5. reinject current identity/policy/task/world-state from canonical sources;
6. recompute context usage;
7. continue the original logical `AgentTurn` with a new `StepSnapshot`.

If compaction fails, do not delete the pre-compaction state.

A hard provider `context_exhausted` after the harness already compacted becomes a typed failure/recovery decision rather than replaying the same oversized request.

## 17. Generic inference/tool loop

Conceptual v1 loop:

```text
load/create AgentTurn
acquire execution ownership

while not terminal:
    snapshot = build StepSnapshot
    persist snapshot/checkpoint metadata

    request = ContextManager.build_request(snapshot)
    stream = ProviderAdapter.stream(request)

    collect assistant content + canonical tool calls + usage

    if provider failure:
        classify
        recovery_policy decides retry/wait/fail/compact/auth-recover
        continue or terminate

    if tool calls:
        execute calls through ToolRuntime against SAME snapshot
        append terminal ToolResults to canonical inference history
        maybe compact
        continue

    decision = CompletionPolicy.evaluate(turn, evidence, assistant_output)

    if decision == continue_with_feedback:
        append policy feedback to canonical inference history
        continue

    if decision == fail:
        mark failed
        terminate

    persist final Cerebro message atomically
    mark AgentTurn completed
    emit completion event
    terminate
```

This loop replaces the provider-specific assumptions inside the current `_generate` without changing channel/poller behavior above it.

## 18. Tool execution semantics

`ToolRuntime.execute(call, snapshot, cancel_token)` should perform:

1. resolve canonical `ToolKey` from the snapshot's provider-name map;
2. verify the call existed in that snapshot and matches expected payload kind;
3. validate arguments against the snapshotted input schema;
4. evaluate permission/policy from the same snapshot;
5. emit durable `tool.call_started`;
6. execute with timeout and cancellation propagation;
7. normalize full result;
8. create bounded model result without destroying full result;
9. emit exactly one durable terminal tool event;
10. return canonical `ToolResult`.

MCP, core Python functions, GitHub connectors, filesystem primitives and future tools all fit behind this contract.

## 19. Recovery policy

Do not start with clever autonomous retry. Start with explicit classes.

### 19.1 Safe automatic retries

Reasonable v1 candidates:

- connection establishment failure before any response body;
- 429/503 with provider retry hint;
- stream disconnect before any semantic output/tool call was accepted, when adapter says replay-safe.

Use capped exponential backoff with jitter and a turn deadline/budget.

### 19.2 Ambiguous replay

If a stream disconnects after tool-call output or other side-effect-significant model output was observed, the adapter/runner must not blindly duplicate semantic execution. Mark the inference attempt interrupted and decide from canonical history what a fresh next step should contain.

### 19.3 Context failure

`context_exhausted`:

```text
if compaction not yet attempted at this boundary
  > compact + new snapshot
else
  > fail/recover at higher level
```

### 19.4 Cancellation

Cancellation propagates:

```text
AgentTurn cancellation token
  > provider stream
  > active tool calls
  > subprocess/MCP requests when supported
```

Give cleanup a short bounded grace window, then force termination of owned processes/tasks as needed.

### 19.5 Service/process restart

On startup, scan non-terminal durable `agent_turns` whose execution ownership is stale.

For v1:

- if the last durable boundary is safe and no side-effecting operation is indeterminate, requeue/recover;
- otherwise mark `suspended`/`failed_needs_attention` with explicit reason rather than guessing.

This can become automated worker leasing later.

## 20. CompletionPolicy

Default chat policy:

```text
assistant produced acceptable final content
  > allow
```

Coding/task policy may require evidence:

```text
required checks configured for task
  > inspect recorded tool/check evidence
  > if missing/failing: continue_with_feedback
  > if satisfied: allow
```

A v1 interface:

```text
CompletionDecision
  allow
  continue_with_feedback(text)
  fail(reason)
```

Potential evidence:

- test command result;
- lint/build command;
- expected artifact/file exists;
- Git diff non-empty/clean as appropriate;
- reviewer-agent result;
- task-specific verifier.

The worker model can still decide what to run, but the harness owns whether required evidence exists.

## 21. Multi-agent/delegation integration

Keep Cerebro's visible shared-channel model.

When an agent delegates a structured task, record:

```text
Task
  parent_task_id?
  root_task_id?
  originating_channel_id
  originating_message_id
  originating_agent_turn_id
  assigned_agent_id
```

The child's eventual `AgentTurn` records corresponding root/parent lineage.

Distinguish durable communication from scheduling:

```text
post/send information to another agent/channel
  != automatically start provider inference

assign/follow-up task or @mention wake
  = scheduling signal
```

This preserves the useful Codex message-vs-trigger distinction without adopting Codex's hidden sub-agent UX.

## 22. Provider cache and continuation state

Adapters may use:

- OpenAI response IDs/cache keys;
- Anthropic cache-control/prompt-cache metadata;
- Gemini cached content;
- local KV/session handles;
- HTTP/WebSocket connection/session state.

Rules:

1. these are adapter-owned optimization hints;
2. they may be persisted if useful;
3. generic Harness code never requires them to understand conversation semantics;
4. another worker without the hint must be able to construct a semantically equivalent full request from Cerebro durable state.

If a provider exposes state required for correctness, store the opaque state durably and mark that provider turn non-portable until proven otherwise.

## 23. Permissions and safety

Cerebro v2 deliberately favors autonomy without approval dialogs. Harness v1 should preserve that product decision while making policy runtime-enforced.

`PermissionProfile` should be a snapshot input describing capabilities such as:

- filesystem roots/read/write;
- network/open-world access;
- process/shell permission;
- MCP/server allowlist;
- destructive-tool allowance;
- external service/account scopes;
- delegation allowance;
- budget/turn limits.

Policy decisions occur before execution, not in prompts.

The existing journal/lease mechanisms remain valuable independent safety controls.

## 24. Observability

Every durable agent turn should be inspectable without provider logs.

Useful IDs on logs/events/metrics:

```text
conversation_turn_id
agent_turn_id
step_index
provider_id
model_id
inference_attempt
call_id
ToolKey
parent/root turn ids
```

Metrics:

- inference duration/time-to-first-token;
- input/output/cache tokens;
- retries by reason;
- context usage/compactions;
- tool latency/failure/denial;
- completion-policy blocks;
- provider errors;
- per-agent/task spend.

Do not log secrets or full sensitive tool output by default merely because raw output is retained elsewhere.

## 25. Migration from current code

### Phase 0 — characterization before refactor

Lock in current behavior with tests for:

- channel reply completion ordering;
- `PASS` semantics;
- tool-call sequence shape;
- provider concurrency limits;
- TurnGuard behavior;
- MCP allowlist refusal;
- cancellation terminal UI events;
- usage accounting.

### Phase 1 — canonical types behind compatibility adapters

Add Harness canonical inference/tool/error types.

Wrap the existing `OpenAICompatibleProvider` behind `ProviderAdapter` without changing user-visible behavior.

Translate current workspace `Message`s into canonical inference history before provider serialization.

Acceptance: existing tests still pass; no tool-call state needs to be hidden in `Message.meta_json` inside the provider adapter path.

### Phase 2 — ToolCatalog + StepSnapshot

Wrap existing `CoreTools` and `MCPRegistry` into canonical tool definitions/bindings.

Build immutable `StepSnapshot` before each inference sample.

Acceptance: mutate an MCP catalog/allowlist while a fake provider is streaming and prove the resulting call executes against or fails against the original snapshot, never a new interpretation.

### Phase 3 — durable AgentTurn/events

Add migrations/tables and make every native-provider run create/update a durable execution turn.

Acceptance: final chat remains completion-ordered; execution state can be inspected while no chat row yet exists.

### Phase 4 — typed recovery + cancellation

Normalize provider errors and implement bounded retry/cancellation/restart classification.

Acceptance: tests cover pre-response network retry, 429 retry-after, cancellation during provider stream, cancellation during tool execution and stale-running-turn startup recovery.

### Phase 5 — ContextManager + compaction

Move current packet assembly behind canonical context sections and add compaction checkpoints.

Acceptance: a synthetic long history compacts, preserves governing state/recent turns, and continues without provider context failure.

### Phase 6 — second native wire protocol

Implement a provider whose native API is materially different from OpenAI Chat Completions (Gemini or Anthropic is ideal).

Acceptance: the generic runner contains no provider-specific branch and the same fake tool/task tests pass through both adapters.

### Phase 7 — completion policy + deferred tools

Add task-specific completion evidence and tool search when catalogs justify it.

Acceptance: a coding task cannot complete while a configured verifier is failing; a large MCP catalog does not require every full schema in the initial provider request.

## 26. What should be one PR versus separate PRs

Do not land Harness v1 as one mega-refactor.

Recommended independent slices:

1. canonical inference/error/provider types + compatibility adapter;
2. canonical tools + immutable snapshot;
3. durable turn/event schema;
4. generic runner cutover;
5. retry/cancellation/recovery;
6. context sections/token budget;
7. compaction;
8. second native provider;
9. completion policy;
10. deferred tool search/output artifact enhancements.

Each slice should preserve a runnable Cerebro and update durable architecture docs.

## 27. Test strategy

The existing `FakeProvider` is a major asset. Extend it into a deterministic event-script provider capable of:

- streaming text/reasoning/tool fragments;
- disconnecting at precise points;
- returning typed 429/5xx/context errors;
- delaying until cancelled;
- emitting multiple parallel tool calls;
- exposing usage/cache metadata.

Add fake tool sources capable of:

- changing catalog version mid-turn;
- blocking until cancelled;
- producing huge output;
- producing structured/image/file output;
- producing side effects counted exactly once;
- failing permission/schema validation.

Critical invariants to test:

1. every accepted tool call gets exactly one terminal result;
2. a call uses the same snapshot that advertised it;
3. retries never duplicate a committed tool side effect;
4. model truncation never destroys the retained full result;
5. compaction never removes current governing state;
6. dropped/restarted workers leave a durable explainable state;
7. provider-specific fields do not leak into the generic runner;
8. final shared messages remain completion-ordered and correctly attributed.

## 28. Initial database additions

Keep schema additions minimal.

Required:

```text
agent_turns
turn_events
context_checkpoints
```

Likely useful soon:

```text
tool_artifacts / artifacts
provider_hints (or JSON field on checkpoint)
```

Do not normalize every JSON subfield into its own table before usage proves the need.

## 29. Initial implementation choices

Recommended for v1:

- Python/asyncio, same process as current Cerebro;
- Pydantic models for canonical boundary types;
- SQLite WAL, existing single-writer discipline;
- deterministic integer/event sequence per `AgentTurn`;
- lexical deferred-tool index when needed;
- file/blob artifact directory with DB metadata for large raw outputs;
- existing Hub for transient UI events;
- existing provider semaphores retained above or moved into ProviderRegistry;
- existing CLI agents retained as parallel external-harness agents.

Avoid introducing Kafka, Redis, a workflow engine, vector database or distributed queue solely for Harness v1.

## 30. Design decisions that should be made before implementation starts

These are the few choices worth resolving explicitly:

1. canonical inference item/message schema, especially tool calls/results and provider-opaque parts;
2. exact durable `agent_turns`/`turn_events` schema and what constitutes a safe checkpoint;
3. `ToolKey` namespace/wire encoding rules;
4. first non-OpenAI-shaped native provider used to validate the abstraction;
5. artifact storage location/retention policy;
6. which coding-task verifier policy should be the first hard completion gate.

Everything else can evolve behind these seams.

## 31. Harness v1 acceptance bar

Do not call the architecture complete until a test/demo can show this scenario:

1. a user message in a normal Cerebro channel wakes a native-provider agent;
2. Cerebro creates a durable `AgentTurn` and immutable step snapshot;
3. the provider streams a tool call;
4. the tool executes against the exact snapshotted binding and returns a large result;
5. Cerebro keeps the full result but feeds a bounded explicit representation back to the model;
6. the provider stream transiently fails and the typed recovery policy handles it without duplicating the tool side effect;
7. context crosses the threshold, compacts, and preserves task/instruction/tool state;
8. a completion verifier blocks one premature “done” and sends feedback into the next model step;
9. the next step satisfies the verifier;
10. the final response is atomically appended to the existing channel and the `AgentTurn` becomes completed;
11. repeating the same harness-level test with a materially different native provider changes only the adapter/profile, not the generic runner.

That exercise proves the important architecture rather than merely proving that an API can return text.

## 32. Codex-derived idea classification

| Harness v1 idea | Classification |
| --- | --- |
| Request-scoped immutable step state | conceptual inspiration > independent Cerebro implementation |
| Provider runtime/config/model-profile separation | conceptual inspiration > independent Cerebro implementation |
| Provider stream normalization | conceptual inspiration + already present in Cerebro; evolve independently |
| Typed retryability/recovery | conceptual inspiration > independent Cerebro implementation |
| Context/world-state sections | conceptual inspiration > independent Cerebro implementation |
| Compaction as durable state transition | conceptual inspiration > independent Cerebro implementation |
| Registry/exposure/router tool separation | conceptual inspiration > independent Cerebro implementation |
| MCP collision fail-closed behavior | conceptual inspiration > independent Cerebro implementation |
| Deferred tool search | conceptual inspiration > independent Cerebro implementation |
| Raw-vs-model output separation/middle truncation | conceptual inspiration > independent Cerebro implementation |
| Durable session/turn reconstruction | conceptual inspiration > independent Cerebro implementation |
| Completion gate with continuation feedback | conceptual inspiration > independent Cerebro implementation |
| Visible Slack-like multi-agent collaboration | Cerebro-native; retain |
| TurnGuard, leases, attribution, usage board | Cerebro-native; retain |

No Codex source implementation should be copied into these components without a future explicit provenance decision.

## 33. Recommended immediate next step

The research phase has enough architecture to stop mining Codex for now.

The next engineering task should be a **design/implementation issue for Phase 1**:

> Introduce canonical Cerebro inference/provider/error types and adapt the existing OpenAI-compatible provider behind them, with behavior-preserving tests.

Before coding, use Gemini or Anthropic's current native API documentation as a second-wire design review of the canonical schema so the new abstraction is not accidentally just OpenAI Chat Completions renamed.

Codex should remain a reference implementation to revisit when a concrete implementation question arises, not a source to continue mining indefinitely without a hypothesis.
