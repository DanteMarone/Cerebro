# Harness v1 current-seams research handoff

Issue: #207 — `Research: map current Cerebro seams for Harness v1 migration`

Branch: `research/harness-v1-seam-inventory`

Pinned source baseline: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

Status: in progress.

## Scope and constraints

This branch is documentation-only. It maps current Cerebro source to the proposed Harness v1 responsibilities without implementing Harness v1 or freezing architecture decisions reserved for #206.

Required deliverables under this directory:

- `CURRENT_SEAMS.md`
- `MIGRATION_TOUCHPOINTS.md`
- `DATA_MODEL_IMPACT.md`
- `TEST_IMPACT.md`
- this handoff

## Inputs read

- root `AGENTS.md`
- issue #207
- issue #206
- current `main` at the pinned SHA above

## Early findings

- `cerebro/runtime.py::AgentRuntime` is the current turn coordinator and is heavily entangled with provider streaming, tool-loop protocol shaping, completion policy (`PASS`, silent-stop/DM behavior), usage publication/accounting, persistence, event publication, concurrency semaphores, and cancellation handling.
- `cerebro/service.py::RuntimeService` owns inbound `message.new` wake/dispatch plus timer polling; provider selection is also centralized in `cerebro/service.py::_provider_for`.
- `cerebro/context.py::ContextBuilder` builds a message-shaped prompt packet, not a provider-neutral ordered inference history.
- OpenAI-chat protocol state is represented by synthetic `Message` objects and JSON stored in `Message.meta_json` (`tool_calls`, `tool_call_id`, tool name). `cerebro/providers/openai_compatible.py::to_chat_messages` reconstructs OpenAI assistant/tool turns from that metadata.
- `cerebro/providers/cli_agent.py::CliAgentProvider` is currently made to satisfy the same `Provider` protocol as native inference backends even though it invokes an external harness subprocess; this is a direct migration seam for the proposed `ExternalAgentAdapter` separation.
- Tool exposure/execution is split across `cerebro/tools.py::CoreTools`, `cerebro/mcp.py::MCPRegistry` / `CompositeToolExecutor`, `cerebro/service.py::_tools_for` / `_run_tool`, and `AgentRuntime._run_tool`.
- Trust/confinement is enforced partly through profile-file trust tiers in `CoreTools`, filesystem confinement helpers in `cerebro/tools.py`, and per-agent MCP allowlist filtering in `MCPRegistry`.
- `cerebro/turnguard.py::TurnGuard` stores turn budget/freeze state only in memory; `turn_id` and `depth` are persisted on messages, but live guard state is not durable.

## Next research steps

Finish exact symbol/storage/test mapping for persistence, Hub/events, polling/wake behavior, usage, API/channel routes, and the existing tests. Then complete the four inventory docs and update this handoff with final commit SHAs and unresolved questions for #206.
