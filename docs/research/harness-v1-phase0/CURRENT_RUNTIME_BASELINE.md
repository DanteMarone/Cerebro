# Harness v1 Phase 0: Current AgentRuntime Behavior & Baseline Characterization

## 1. Executive Summary & Context

This document captures the Phase 0 characterization baseline for the Cerebro `AgentRuntime` subsystem and associated providers, tools, TurnGuard, MCP, and channel dispatch layers prior to the upcoming Harness v1 refactor (Issue #205).

All characterization work and test additions were executed on the dedicated branch:
`test/harness-v1-phase0-characterization` created from unmodified `main` (`57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`).

In strict accordance with Phase 0 constraints:
* **Zero production code changes were made.** No runtime, provider, context, tool, prompt, profile, or service files differ from `main`.
* **Zero paid/external agent APIs were invoked.** All tests use `FakeProvider` or local script fakes.
* **46 new deterministic characterization tests** were added in `tests/test_harness_characterization.py`.

This document establishes the durable, observable behavioral invariants of the Cerebro runtime so that subsequent Harness v1 refactoring phases can proceed with regression guarantees without altering the product contracts established in Cerebro v2 architecture.

---

## 2. Baseline Test Execution & Initial State

### 2.1 Baseline Commands & Environment
* **OS / Environment**: Windows 11, Python 3.14.0
* **Virtual Environment**: `.venv`
* **Test Runner**: `pytest` 9.1.1 (with `anyio-4.14.2`, `asyncio-1.4.0`)
* **Linter**: `flake8` 7.3.0
* **Commands Run**:
  ```powershell
  $env:PYTHONPATH="."
  .venv\Scripts\flake8.exe tests/test_harness_characterization.py
  .venv\Scripts\pytest.exe -v
  ```

### 2.2 Baseline Test Results
* **Baseline on Unmodified `main` (`57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`)**:
  - Total items collected: 405
  - Result: **402 passed, 3 skipped in 15.66s**
* **Post-Characterization Test Suite Run (with `tests/test_harness_characterization.py`)**:
  - Total items collected: 451
  - Test result: **448 passed, 3 skipped in 16.46s**
  - Characterization test suite (`tests/test_harness_characterization.py`): **46 passed in 1.48s**
  - Linting (`flake8 tests/test_harness_characterization.py`): **0 lint errors**

---

## 3. Observable Invariants Characterized & Confirmed

The following 10 core runtime behavior categories were thoroughly characterized and locked down with deterministic tests against unchanged `main`:

### 3.1 Completion-Ordered Final Channel Replies
1. **Zero Intermediate Placeholder Rows**: During model inference and streaming text deltas, zero message rows exist in the persistent database transcript. The message row is written exactly once upon turn completion.
2. **Completion Timestamp Ordering**: When multiple agent turns run concurrently with overlapping lifecycles, message sequence IDs and order in the channel history reflect the exact completion time, not invocation or dispatch time.
3. **Turn Attribution & Metadata**: The completed message preserves the invoking `turn_id`, `depth`, `quote_msg_id`, `author_id`, `author_kind="agent"`, and `kind="chat"`.
4. **Dual Event Publication**: Upon turn completion, the runtime publishes both `message.new` and `message.done` to the Hub with identical message payload envelopes (`{"channel_id": ..., "message": {...}}`).

### 3.2 PASS & Silent Completion Semantics
1. **Topic / War Room PASS**: In topic channels, an agent output of `PASS` (case-insensitive, whitespace-trimmed, optional trailing period) discards the turn cleanly. No row is persisted, `turn.discarded` is published with `reason="pass"`, and agent status resets to `idle`.
2. **Strict Matching**: Non-exact PASS text (e.g. `"PASS - I have nothing to add"` or `"I'll pass"`) is treated as real content and persisted as a chat message.
3. **Silent Stop in Topic Channels**: An empty text reply with `Done(reason="stop")` in a topic channel is treated as a valid silent completion. It publishes `turn.discarded` with `reason="silent_stop"` and writes zero rows.
4. **Direct Message (DM) Fail-Closed**: In direct message channels (`dm-*` or channels with `kind="dm"`):
   - Saying `PASS` is strictly forbidden and produces an error message row: `⚠ said PASS in a direct message (silence is not allowed in DMs)`.
   - Silent stop with empty text is strictly forbidden and produces an error message row: `⚠ produced no answer in a direct message (silence is not allowed in DMs)`.

### 3.3 Assistant > Tool Call > Tool Result > Follow-Up Sequencing
1. **Strict Chat Protocol Shape**:
   - Round 1: Model outputs one or more `ToolCallDelta`s and `Done(reason="tool_calls")`.
   - Runtime records assistant message carrying `meta_json={"tool_calls": [{"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}]}`.
   - Runtime executes each tool and appends a tool result message: `author_id="tool"`, `author_kind="system"`, `kind="tool"`, body containing tool result string, `meta_json={"tool_call_id": ..., "name": ...}`.
   - Round 2: Model receives full formatted history and outputs final text or subsequent tool calls.
2. **Parallel Tool Call Support**: Multiple tool calls in a single assistant turn are executed in sequence, publishing individual `tool.call` and `tool.result` events, and their responses are appended in matching order.
3. **Unserviced Tool Calls**: If an agent requests tool calls but `tool_executor` is `None`, the runtime breaks the loop and fails the turn with an error message rather than silently dropping the turn.

### 3.4 Provider Concurrency & Semaphore Behavior
1. **Per-Provider Concurrency Limits**: `AgentRuntime` maintains an `asyncio.Semaphore` per provider name (`self._limits`, e.g. `{"lmstudio": 2, "gemini": 4}`, defaulting to 2 for unlisted providers).
2. **Stream Isolation**: Saturated concurrency on Provider A does not block or delay turns executing against Provider B.
3. **Safe Release Under Failure**: If a provider stream raises an exception or is cancelled, the semaphore is released cleanly in the `async with` block, immediately unblocking queued turns.

### 3.5 TurnGuard & Maximum Tool-Loop Behavior
1. **Pre-Inference Verification**: `TurnGuard.check(turn_id, depth)` runs before calling provider streaming to avoid paying for runaway inferences.
2. **Depth Limit**: When `depth > limits.max_depth`, TurnGuard refuses the turn. The runtime posts a system message (`"Paused: conversation depth X exceeded the limit of Y. Reply to pick this back up."`), publishes `turn.frozen`, and returns `None` without invoking the provider.
3. **Message Count Limit**: When `agent_messages >= limits.max_agent_messages` on a `turn_id`, TurnGuard freezes the turn.
4. **Tool Iteration Bound**: If an agent loops on tool calls indefinitely, the loop terminates after `max_tool_iterations` (default 12) and appends `\n\n_Stopped after X tool rounds without finishing._` to the message text.

### 3.6 MCP & Tool Allowlist Refusal & Confinement
1. **Trust Tier Filtering**: CoreTools filters specs based on agent trust tiers (`sandboxed`, `standard`, `full`). Unrecognized or missing tiers fail safe to `sandboxed`.
2. **Allowlist Refusal**: Sandboxed agents attempting to execute un-offered tools (e.g. `fs_read` or `task_create`) receive `error: '<name>' is not available to <agent_id>.`
3. **Filesystem Confinement**: Path traversal attempts (e.g. `../../outside.txt` or escaping directory roots) raise `ToolError` and return confinement violation errors.
4. **Memory Note Safe Naming**: Memory notes reject path separators and invalid filenames to prevent escaping the agent's memory folder.
5. **Composite MCP Execution**: `CompositeToolExecutor` verifies that MCP tools (`server__tool`) match the agent's `tools_enabled` glob patterns. Unoffered MCP tools are rejected before invoking the client.
6. **Dynamic Package Download Prohibition**: `StdioMCPClient` rejects dynamic download commands (`npx -y`, `uvx`) at initialization per supply-chain hardening directives.

### 3.7 Cancellation & Terminal UI / Runtime State
1. **Deterministic Cleanup**: When an in-flight turn task is cancelled via `asyncio.CancelledError`:
   - Sets status to `"cancelled"` via `agent.status` and `agent.activity`.
   - Publishes `turn.cancelled` event containing `channel_id`, `turn_id`, `agent_id`.
   - Leaves zero partial or empty database message rows.
2. **Subprocess Termination**: For `CliAgentProvider`, cancellation immediately terminates and kills the child process, preventing orphan background processes on Dante's host.

### 3.8 Usage Accounting & Persistence
1. **Measured Token Accounting**: When a provider emits a `Usage(input=..., output=...)` delta:
   - Publishes `usage` event on the Hub for real-time UI display.
   - Persists accumulated daily token metrics into the `budget_usage` database table.
2. **Resilience**: Database write failures during usage recording are caught and logged, ensuring accounting errors never crash an active agent turn.
3. **Zero Token Filter**: Turns yielding 0 input and 0 output tokens do not create unnecessary database usage rows.

### 3.9 Provider & Tool Failure Handling Without Orphaning Turns
1. **Provider Failures**:
   - `ProviderUnavailable` -> persists error message `⚠ backend offline — <details>`, publishes `error`, `message.new`, `message.done`, resets status to `idle`.
   - `ProviderError` -> persists error message `⚠ provider error — <details>`, resets status to `idle`.
   - Unexpected exceptions -> persists error message `⚠ unexpected error — <details>`, resets status to `idle`.
2. **Tool Execution Exceptions**: Exceptions in `tool_executor` are captured as string data `error: <exc!r>`, published as `tool.result`, and passed back into the conversation for model recovery.
3. **Malformed Tool Arguments**: Invalid JSON emitted by local models is captured as `error: arguments were not valid JSON: ...`, published as `tool.result`, and fed back to the model for retry.

### 3.10 CLI-Provider Behavior (Deterministic Testing)
1. **Prompt Flattening**: `render_prompt` formats multi-role conversation history with `[Dante]`, `[System]`, `[<agent_id> (you)]`, and `[<peer_agent>]`.
2. **Reasoning & Banner Separation**: `parse_cli_output` strips startup headers/banners and extracts inner reasoning tags (`<think>`, `<thought>`, `<|channel>thought...<channel|>`) into `ReasoningDelta` while streaming clean answer text into `TextDelta`.
3. **Exit & Error Handling**: Non-zero exit codes raise `ProviderError` with captured stderr; empty stdout replies raise `ProviderError`; timeouts terminate child processes.
4. **File Output Backends**: Backends using `--output-last-message` (e.g. Codex) ignore noisy stdout traces and read the clean final output file.

---

## 4. Characterization Test Suite Added

All 46 new deterministic characterization tests are implemented in:
`tests/test_harness_characterization.py`

### Test Suite Breakdown:
| Test Function | Target Invariant Category |
| :--- | :--- |
| `test_completion_ordered_replies_commit_at_completion_time_not_start_time` | Completion ordering |
| `test_streaming_deltas_do_not_create_intermediate_database_rows` | Clean persistence |
| `test_completion_publishes_message_new_and_message_done_events` | Hub events |
| `test_reply_preserves_turn_metadata_and_attribution` | Metadata & depth |
| `test_pass_in_topic_channel_discards_turn_without_persisting_row` | Topic PASS |
| `test_pass_strict_matching_preserves_non_exact_sentences` | Strict PASS matching |
| `test_silent_stop_in_topic_channel_discards_turn_without_row` | Silent stop in topic |
| `test_pass_in_dm_channel_fails_closed_with_error_message` | DM PASS fail-closed |
| `test_silent_stop_in_dm_channel_fails_closed_with_error_message` | DM silence fail-closed |
| `test_single_tool_round_protocol_shape_and_follow_up` | Tool round sequencing |
| `test_parallel_multiple_tool_calls_in_single_round` | Parallel tool calls |
| `test_multi_round_tool_loop_sequencing` | Multi-round tool loops |
| `test_unserviced_tool_calls_without_executor_produce_error` | Missing executor failure |
| `test_provider_semaphore_bounds_concurrent_streams` | Provider concurrency |
| `test_independent_providers_do_not_block_each_other` | Provider semaphore isolation |
| `test_semaphore_is_released_on_stream_exception` | Semaphore release on error |
| `test_semaphore_is_released_on_turn_cancellation` | Semaphore release on cancel |
| `test_turnguard_depth_limit_freezes_turn_and_posts_system_message` | TurnGuard depth limit |
| `test_turnguard_message_count_limit_freezes_turn` | TurnGuard message limit |
| `test_max_tool_iterations_terminates_infinite_tool_loop` | Max tool iterations bound |
| `test_core_tools_sandboxed_tier_refuses_fs_and_task_tools` | Sandboxed tier filtering |
| `test_core_tools_execution_tier_refusal` | CoreTools execution refusal |
| `test_filesystem_path_confinement_traversal_refusal` | Path traversal protection |
| `test_memory_note_safe_name_confinement_refusal` | Safe note name validation |
| `test_composite_tool_executor_refuses_unoffered_mcp_tools` | Composite MCP gating |
| `test_stdio_mcp_client_rejects_npx_uvx_dynamic_downloads` | Supply chain hardening |
| `test_cancellation_emits_cancelled_status_and_leaves_clean_database` | Cancellation cleanup |
| `test_cancellation_propagates_to_cli_subprocess` | CLI subprocess cancellation |
| `test_usage_delta_publishes_event_and_persists_to_budget_usage` | Usage accounting |
| `test_usage_persistence_failure_is_non_fatal` | Usage persistence resilience |
| `test_provider_unavailable_persists_error_and_returns_idle_status` | Provider offline error |
| `test_provider_error_persists_error_and_returns_idle_status` | Provider error handling |
| `test_unexpected_exception_persists_error_and_returns_idle_status` | Unexpected error handling |
| `test_tool_execution_exception_is_captured_and_reported_to_model` | Tool error recovery |
| `test_malformed_tool_args_reported_to_model` | Bad tool JSON recovery |
| `test_cli_agent_renders_prompt_with_role_labels` | CLI prompt rendering |
| `test_cli_agent_extracts_reasoning_and_strips_banner` | CLI banner & reasoning extraction |
| `test_cli_agent_handles_nonzero_exit_and_drains_stderr` | CLI error & stderr handling |
| `test_cli_agent_output_file_mode_ignores_stdout_noise` | CLI file output mode |

---

## 5. Gaps, Ambiguities & Edge Cases Discovered

During characterization of unmodified `main`, the following behaviors and nuances were documented:

1. **Poller Initialization on @Mention Cursor Advance**:
   - `ChannelPoller.mark_seen(agent_id, channel_id, message_id)` only updates cursor state if `agent_id` is already in `self._states`. If called before the poller loop has completed its first tick for that agent, cursor updates are ignored. Recorded as a discovered gap; no production code was modified in Phase 0.
2. **Freeze Message Body Format**:
   - `TurnGuard.freeze_message` formats messages with prefix `"Paused: conversation depth X exceeded the limit of Y. Reply to pick this back up."` (using `"Paused:"` rather than `"Frozen:"`).
3. **Malformed JSON Tool Arguments Loop Protection**:
   - When a model outputs malformed JSON in tool arguments, `_run_tool` returns an error string without calling `tool_executor`. If the model continues to emit malformed JSON on subsequent rounds, it terminates cleanly at `max_tool_iterations` rather than hanging.
4. **Reasoning Log File Isolation**:
   - `AgentRuntime._log_thinking` anchors agent home directories to `settings.agents_path`. Characterization tests use isolated agent fixtures with explicit `home_path` to guarantee tests never write reasoning logs into live `agents/` workspace directories.

---

## 6. Production Code Adjustments & Testability Seams

* **Zero production code changes were made.**
* No files in `cerebro/`, `agents/`, `data/`, or `scripts/` were modified.
* All characterization tests run cleanly against unmodified `main` (`57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`).

---

## 7. Impact & Constraints for Upcoming Harness v1 Refactor

The following architectural constraints must be preserved when implementing Harness v1:

1. **Keep Completion-Ordered Persistence**:
   - Do not re-introduce pre-allocated empty message rows or streaming database updates. Messages must only be inserted into the database when completely finished.
2. **Maintain DM Silence Prohibition**:
   - Direct messages require explicit replies. Neither `PASS` nor silent stop may be converted into a no-op in DMs; both must fail-closed with clear error messages.
3. **Preserve Subprocess Lifecycle Isolation**:
   - Any new harness process abstraction must guarantee that subprocess termination signals (SIGTERM/SIGKILL) propagate immediately upon turn cancellation or timeout.
4. **Maintain Non-Fatal Accounting**:
   - Usage accounting must remain detached from core turn execution so that storage exhaustion or database locks on metrics tables never block agent collaboration.
5. **Enforce Strict Tool Turn Framing**:
   - Assistant turns containing tool calls must match provider schema requirements (one assistant message with `tool_calls` list followed by one tool message per call carrying `tool_call_id`).

---

## 8. Exact Handoff / Resume Section

* **Branch**: `test/harness-v1-phase0-characterization`
* **Branch Base**: `main` (`57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`)
* **Test Verification**:
  - Full test suite: `448 passed, 3 skipped in 16.46s`
  - New characterization suite: `46 passed, 0 failed in 1.48s`
  - Linter: `flake8 tests/test_harness_characterization.py` clean (0 errors)
* **New Test File**: `tests/test_harness_characterization.py`
* **Next Steps (Harness v1 Phase 1)**:
  - Proceed with Harness v1 architecture design and modular provider/harness decoupling based on the confirmed invariants in this baseline.
