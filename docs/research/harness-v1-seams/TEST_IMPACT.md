# Harness v1 test-impact inventory

Issue: #207

Source baseline: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

This maps current tests to the migration seams. It is not a proposed Harness v1 test plan and does not modify tests.

## Highest-value behavior contracts already pinned

### Turn coordination and completion policy — `tests/test_runtime.py`

This is the main compatibility suite around `cerebro/runtime.py::AgentRuntime`.

It currently pins, among other behaviors:

- final messages are persisted only after generation completes (`test_reply_is_persisted_only_on_completion`);
- streamed `turn.delta` events carry turn/agent identity;
- context reaches the provider before the answer;
- `TurnGuard` denial prevents provider inference (`test_a_frozen_turn_never_reaches_the_provider`);
- provider failures become durable error messages instead of crashing the service;
- a tool call is executed and its result is supplied to a subsequent provider round;
- malformed tool JSON and tool execution failure are fed back as model-visible errors rather than ending the process;
- tool rounds are bounded;
- status/activity events bracket turns;
- reasoning is private to filesystem logs and is neither channel-persisted nor published;
- `message.new` and `message.done` final envelopes match UI expectations;
- `PASS` and valid silent `stop` produce no collaboration row outside DMs;
- empty/length/error completion handling and DM-specific no-silence/no-PASS policy;
- overlapping turns persist in completion order rather than invocation order;
- `quote_msg_id` is preserved;
- same-agent overlapping turns keep distinct `turn_id`s;
- cancellation emits `turn.cancelled` and leaves no incomplete message row;
- finish reason is request-local under concurrency;
- outstanding/unserviceable tool calls are not treated as clean silence.

Migration implication: many assertions are product contracts that should survive even if `AgentRuntime` is replaced internally. Assertions that inspect `provider.calls[*]["messages"]` or synthetic `Message(kind="tool")` are coupled to the current provider/history shape and will need reinterpretation if canonical `InferenceItem` becomes the adapter input.

Important gap: current runtime tests prove an in-memory tool round, not restart/re-entry between “provider emitted side-effecting tool call” and “tool executed/result returned.” They do not establish a durable pre-side-effect checkpoint.

### Context/history — `tests/test_context.py`

Pins `ContextBuilder` identity, channel roster, scratchpad, memory inclusion, budget trimming, newest-history retention, preservation of the triggering message, and the current compatibility workaround of exactly one system `Message`.

Migration implication: the semantic content/budget behaviors are compatibility candidates; the exact `list[Message]` output and single-system-role encoding are chat-template/provider projection details rather than inherently canonical Harness v1 semantics.

Gap: tests budget only `Message.body`-based context. They do not cover cost/retention of structured tool items, provider-opaque items, multimodal content, provider-native replay references or per-call immutable snapshots.

### OpenAI-compatible provider — `tests/test_provider_openai_compatible.py`

Pins:

- `to_chat_messages()` attribution: own agent > `assistant`, Dante > `user`, peer agents > prefixed `user`;
- `/chat/completions` streaming text/usage normalization;
- reasoning and fragmented tool-call normalization;
- OpenRouter headers/model resolution;
- HTTP error mapping.

Migration implication: these tests define the current OpenAI-chat adapter behavior. They are directly touched by replacing `Message` as provider input or by adding native OpenAI Responses/other provider adapters.

Gap: this file does not directly test reconstruction of an assistant `tool_calls` message and following `tool_call_id` tool result from persisted `Message.meta_json`; runtime tests exercise the in-memory shape indirectly. A migration must not infer durable replay coverage from this suite.

### LM Studio — `tests/test_lmstudio_provider.py`

Covers the existing LM Studio/OpenAI-compatible path. This remains an important compatibility surface even when native provider adapters are added; issue #204 owns the provider-normalization conclusions.

### External CLI harnesses — `tests/test_cli_agent_provider.py`

Pins `CliAgentProvider` subprocess semantics:

- subprocess stdout becomes reply text and stderr does not;
- non-zero exit, empty output, timeout and missing binary become provider errors;
- cancellation kills the child process;
- `render_prompt()` labels system/human/self/peer messages;
- registered backend names (`claude`, `codex`, `agy`, `goose`) stay synchronized with seeded profiles;
- Codex-style output-file mode ignores noisy stdout and drains stderr;
- Goose reasoning tags are removed from reply text and represented separately;
- Claude/Sonnet provider selection builds the expected CLI model command.

Migration implication: these are external-agent-adapter behaviors even though the class currently implements `Provider`. Separating `ExternalAgentAdapter` should preserve the subprocess/cancellation/output contracts without forcing it through native-provider protocol semantics.

Gap: no durable external-session/re-entry contract; each turn is effectively a fresh subprocess invocation with a flattened prompt.

### Wake/dispatch — `tests/test_service.py` and `tests/test_poller.py`

`tests/test_service.py` pins muted DM responder exclusion, muted membership exclusion from polling, and sandboxed default CLI cwd.

`tests/test_poller.py` pins first-sight/no-backlog wake, one wake for batched new messages, interval handling, no re-wake for same messages, one in-flight poll turn per agent, pause/resume, channel membership filtering, retry backoff/give-up, success reset, self-reply cursor advancement, and legacy empty-placeholder cleanup.

Migration implication: these tests belong above the harness. The safest migration boundary is to preserve `RuntimeService`/`ChannelPoller` wake decisions while swapping the implementation behind `run_turn`; #206 decides the exact boundary.

Gap: poller cursor/backoff/give-up/in-flight state is intentionally tested only in process memory. Restart continuity is not covered.

### Turn limits/concurrency — `tests/test_turnguard.py`

Pins depth, agent-message and wall-clock freeze limits; frozen-turn refusal; explicit freeze; state sweep; unique turn IDs; and `AgentRateLimiter` behavior.

Migration implication: preserve admission ceilings, but current tests do not prove durable guard state. `AgentRateLimiter` is unit-tested independently; no current wiring from `RuntimeService`/`AgentRuntime` was found in the mapped source.

### Core tools/trust/confinement — `tests/test_tools.py`

Pins:

- fail-safe default `sandboxed` tier;
- catalogue omission and execution-time refusal for unavailable tools;
- memory/scratchpad path/name confinement including symlink/junction escape resistance;
- sandboxed vs standard catalogue difference;
- filesystem confinement;
- collaboration channel/message tools;
- task CRUD tool lifecycle.

Migration implication: these are safety/product contracts around the tool catalog/policy/runtime split. They should remain independent of provider adapters.

Gaps relevant to #206:

- no durable “admitted tool call > exactly one terminal outcome” record;
- no restart/idempotency test around side-effect execution;
- no explicit raw-result versus bounded-model-result contract;
- current `CoreTools` event publication behavior when constructed without a Hub is not characterized here.

### MCP — `tests/test_mcp.py`

Pins rejection of dynamic `npx -y`/`uvx` downloads, stdio JSON-RPC initialization/tool execution/wire names, failure-closed server crash, and composite CoreTools/MCP routing.

Migration implication: these tests cover transport/catalog mechanics and should map under Cerebro-owned ToolRuntime/ToolCatalog rather than provider adapters.

Gaps: no test establishes `MCPServerConfig.trust` enforcement, configured environment propagation, durable tool-call lifecycle, or policy-decision persistence.

### Persistence/schema — `tests/test_store.py`, `tests/test_db_migrations.py`, `tests/test_db_loop_affinity.py`

These pin current CRUD/schema migration behavior, write serialization assumptions and event-loop affinity. Any Harness v1 durable-state schema will extend this area.

Important preservation point: `db.run_in_writer()` is already an atomic transaction seam and should be covered by any new checkpoint atomicity tests if #206 chooses it.

### Usage — `tests/test_usage.py`

Pins measured-token accumulation, non-fatal accounting writes, self-reported external-harness quota attribution/staleness, and strict separation of measured versus self-reported data.

Migration implication: provider call tracking can be added without collapsing those provenance categories. Existing aggregate accounting is not a per-step replay record.

### Hub/WebSocket/channel API — `tests/test_hub.py`, `tests/test_routes_channels.py`, `tests/test_ws.py`, `tests/test_ws_integration.py`, `tests/test_slice2_invariants.py`, `tests/test_agent_channel_creation.py`

These protect the Slack-like layer above the harness: authorship, membership, visibility, channel mutation, message history, event fan-out and WebSocket envelopes.

Migration implication: Harness v1 should not require the UI/API to consume provider-native or reducer-internal state. Final collaboration messages/events remain a compatibility boundary.

## Tests most likely to need direct adaptation in Phase 1

| Test area | Why directly touched |
| --- | --- |
| `tests/test_runtime.py` | Current monolithic loop is the primary object being decomposed/replaced. |
| `tests/test_provider_openai_compatible.py` | Provider input is currently `Message`; native/provider-neutral history changes this seam. |
| `tests/test_fake_provider.py` | Fake provider likely encodes the existing `Provider`/Delta protocol used by runtime tests. |
| `tests/test_context.py` | Context output is `list[Message]`; canonical inference-item projection changes representation. |
| `tests/test_cli_agent_provider.py` | External harness should be separated conceptually/API-wise from native ProviderAdapter. |
| `tests/test_db_migrations.py` / `tests/test_store.py` | Durable turn/checkpoint/history state requires new migrations/storage access. |

## Tests that should mostly remain product-level regression coverage

- `tests/test_service.py`
- `tests/test_poller.py`
- `tests/test_tools.py`
- `tests/test_mcp.py`
- `tests/test_turnguard.py` behavior ceilings, even if implementation ownership changes
- `tests/test_routes_channels.py`
- `tests/test_ws.py`
- `tests/test_ws_integration.py`
- `tests/test_slice2_invariants.py`
- `tests/test_usage.py`

They may require fixture/adapter changes, but their observable product/safety invariants are useful migration guards.

## Missing characterization exposed by #207

The current test tree does not appear to prove these #206-critical cases on `main`:

1. Restart/re-entry after a provider has finalized a tool call but before tool execution.
2. Restart/re-entry after a side-effect tool executes but before the provider consumes its result.
3. Exactly one durable terminal outcome for every admitted tool call.
4. Idempotent recovery of side-effecting tools.
5. Provider-native replay/reference persistence.
6. Immutable per-request snapshot across mid-turn model/config/tool-policy changes.
7. Canonical history that can represent tool/provider-opaque items without `Message.meta_json`.
8. Safe model/provider switch boundaries within an existing durable turn.
9. Typed retry/recovery/suspend state across process restart.
10. Durable cancellation state and recovery semantics after restart.
11. Separation of semantic durable execution events from lossy Hub telemetry.
12. Raw/full tool result retention separately from bounded model-visible content.

Those are gaps for #206/Phase 1 planning, not instructions to add tests on this research branch.

## Relationship to issue #205

Issue #207’s current-source inventory is pinned to `main@57e9c4e...`. Any Phase 0 characterization work living only on the #205 test branch should be evaluated separately before implementation and should not be misreported here as tests already present on this pinned `main` baseline.
