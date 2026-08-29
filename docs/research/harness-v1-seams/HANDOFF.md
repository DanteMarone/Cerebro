# Harness v1 current-seams research handoff

Issue: #207 — `Research: map current Cerebro seams for Harness v1 migration`

Branch: `research/harness-v1-seam-inventory`

Pinned source baseline: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

Status: complete for the #207 current-source seam inventory.

## Scope and constraints

This branch is documentation-only. It maps current Cerebro source to the proposed Harness v1 responsibilities without implementing Harness v1 or freezing architecture decisions reserved for #206.

No production code or test code was changed.

## Deliverables

- `CURRENT_SEAMS.md` — exact current owners, responsibilities, coupling, persisted representation, tests, likely seams and Phase 1 classification.
- `MIGRATION_TOUCHPOINTS.md` — exact files/classes/functions most likely to meet a Harness v1 migration, separated from product-layer boundaries.
- `DATA_MODEL_IMPACT.md` — current SQLite/message/tool/task/audit/usage representations and missing durable harness state.
- `TEST_IMPACT.md` — existing regression coverage, tests directly coupled to current runtime/provider shapes, and characterization gaps.
- this handoff.

## Incremental commit chain

- `68a31e7835076e7ff36693a7eef58a1d0b85d939` — start durable handoff.
- `9e351f7f789b152c81633eb02e4c5f504ef0d36d` — map current Harness v1 source seams.
- `03cdf08da7f5e6a24f1647ca6c694c8b981353f8` — document Harness v1 data-model touchpoints.
- `81c3e77a4e8d15c5a8832a479112c865f7bdc4c0` — map Harness v1 test impact.
- `d11d26787376b5ed6539f92d60bbb85c3099150b` — identify Harness v1 migration touchpoints.

This final handoff update is an additional documentation-only commit after those findings commits.

## Inputs read

- root `AGENTS.md`
- issue #207
- issue #206
- current `main` source and relevant current tests at the pinned SHA above

## Durable conclusions

1. `cerebro/runtime.py::AgentRuntime` is the current concentration point for harness responsibilities. `run_turn`, `_generate` and `_run_tool` jointly own guard admission, provider inference, tool protocol assembly, tool execution, completion policy, usage, persistence, event publication, concurrency and cancellation behavior.

2. The current provider contract is collaboration-message shaped. `cerebro/providers/base.py::Provider.stream()` accepts `list[Message]`, and `cerebro/context.py::ContextBuilder.build()` also returns `list[Message]`. There is no first-class provider-neutral ordered inference-history type or immutable request snapshot.

3. OpenAI-chat protocol state is coupled to `Message.meta_json`. `AgentRuntime._generate()` synthesizes assistant `tool_calls` and tool-result `tool_call_id` metadata, while `cerebro/providers/openai_compatible.py::to_chat_messages()` reconstructs OpenAI assistant/tool turns from it. Those live tool-round messages are only appended to the in-memory `transcript`; they are not durably appended to the collaboration `messages` table. A restart between provider/tool steps therefore cannot reconstruct the live tool round from current SQLite state.

4. `cerebro/service.py::RuntimeService` and `cerebro/poller.py::ChannelPoller` are the current wake/dispatch layer above `AgentRuntime`. Immediate Hub-driven dispatch currently handles eligible DMs; opted-in channel polling is the second wake mechanism. Poll cursors, failure/backoff state and in-flight state are process-memory only.

5. Provider selection is centralized and hard-coded in `cerebro/service.py::_provider_for`. `cerebro/providers/cli_agent.py::CliAgentProvider` currently implements the same `Provider` protocol as LM Studio/OpenAI-compatible inference even though it launches an external Claude/Codex/Antigravity/Goose harness subprocess. That is the clearest current seam corresponding to #206's native-provider versus external-agent distinction.

6. Context collection has a useful existing boundary in `ContextBuilder`, but its projection is chat-template shaped. Its single-system-message rule is a current compatibility workaround for local chat templates, not evidence that canonical Harness v1 history should itself be system/user/assistant chat messages.

7. Cerebro-owned tool responsibilities are spread across `CoreTools`, `MCPRegistry`, `CompositeToolExecutor`, service composition and `AgentRuntime._run_tool`. Core trust-tier catalog filtering is rechecked at execution and filesystem confinement resolves paths/symlinks. MCP exposure is filtered by profile `tools_enabled` globs. `MCPServerConfig.trust` and `env` exist as fields but are not current proof of an enforced server-trust boundary/environment propagation.

8. The SQLite schema contains `tool_calls` and `audit_events`, and `cerebro/models.py` defines corresponding models, but current `AgentRuntime`/`store.py` do not write a durable tool-call lifecycle or audit execution stream. Their presence should not be treated as existing Harness v1 replay/checkpoint state.

9. `cerebro/turnguard.py::TurnGuard`, provider semaphores, RuntimeService live-task ownership, poller in-flight state and cancellation coordination are process-local. `messages.turn_id` and `messages.depth` survive, but live turn/reducer/guard/cancellation state does not.

10. `cerebro/hub.py::Hub` is deliberately lossy, bounded, in-process telemetry/fan-out with process-local sequence numbers. It is also used for some internal dispatch. It is not a durable semantic execution-event store.

11. `cerebro/db.py::run_in_writer()` is the existing atomic `BEGIN IMMEDIATE` transaction primitive most relevant to any future pre-side-effect checkpoint. Current tool execution does not use it to persist replay state before executing a side effect.

12. Current usage semantics deliberately distinguish measured provider token usage (`budget_usage`) from self-reported/relayed external-harness quota (`agent_quota`). A migration should not collapse that provenance simply because CLI harnesses are currently typed as providers.

## Current behaviors worth preserving/characterizing rather than silently changing

- `CoreTools` is composed in `service.py` without a Hub, so its current `post_message` path persists a message but does not publish the live `message.new` event through that optional CoreTools Hub hook.
- `AgentRateLimiter` is unit-tested in `tests/test_turnguard.py`, but no current wiring from `RuntimeService`, `AgentRuntime` or `ChannelPoller` was found in this inventory.
- `messages.meta_json` is not exclusively provider protocol state; imported transcript provenance also uses it.
- Collaboration `tasks` are product work items, not harness reducer effects/turn tasks.

These are source facts for later design/characterization, not fixes proposed by #207.

## Architecture questions intentionally left to #206

- What durable object owns turn lifecycle and reducer state independently of collaboration messages?
- What is the canonical `InferenceItem` representation and persistence layout?
- How are provider-native replay ids/opaque items associated with canonical history?
- What exactly must be committed atomically before a side-effecting tool executes?
- Should the existing unused `tool_calls`/`audit_events` schema be reused, migrated or left as legacy state?
- How is an immutable `StepSnapshot` represented and recovered?
- What is the exact `ProviderAdapter` versus `ExternalAgentAdapter` interface boundary?
- Which execution events are durable semantics and which remain lossy Hub/UI telemetry?
- How are typed retry, suspend, cancellation and restart recovery represented?

## Test impact

The strongest current compatibility coverage lives in `tests/test_runtime.py`, `tests/test_context.py`, `tests/test_provider_openai_compatible.py`, `tests/test_cli_agent_provider.py`, `tests/test_service.py`, `tests/test_poller.py`, `tests/test_turnguard.py`, `tests/test_tools.py`, `tests/test_mcp.py`, persistence tests, usage tests, and channel/WebSocket/auth invariant suites.

The largest missing characterization is restart/re-entry across provider/tool side-effect boundaries. Current tests prove an in-memory multi-round tool loop and cancellation behavior, not durable replay/checkpoint semantics.

Issue #205 characterization work is separate from this pinned `main` inventory and should not be reported as current-main coverage unless/when it lands.

## Verification and testing

The branch should differ from the pinned `main` baseline only under `docs/research/harness-v1-seams/`. A final compare should verify that before handoff.

Tests/lint were not run because this branch changes documentation only; root `AGENTS.md` permits skipping them for docs-only changes.

## Resume note

Treat `57e9c4ecd8b470145afc51c2c1f6771a2f560fd7` as the source baseline for every statement in these documents. If `main` advances before implementation or architecture reconciliation, revalidate affected seams rather than assuming this inventory describes later source.
