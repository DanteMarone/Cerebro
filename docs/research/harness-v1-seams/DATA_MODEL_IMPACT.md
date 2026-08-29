# Harness v1 data-model impact inventory

Issue: #207

Source baseline: `main@57e9c4ecd8b470145afc51c2c1f6771a2f560fd7`

This document records current persistence semantics and the data-model pressure created by the #206 Harness v1 responsibilities. It does not select the final schema.

## Current storage primitives

`cerebro/db.py` owns one `aiosqlite` connection, WAL mode, a single asynchronous writer queue, and `run_in_writer(fn)` for atomic `BEGIN IMMEDIATE` transactions. `cerebro/store.py` is the main CRUD layer. `cerebro/persistence.py::StoreAdapter` is the adapter used by `AgentRuntime`.

The current migrations at the pinned baseline are:

- `cerebro/migrations/001_init.sql`
- `cerebro/migrations/002_add_last_read_message_id.sql`
- `cerebro/migrations/003_add_leases.sql`
- `cerebro/migrations/004_agent_quota.sql`

`cerebro/schema.sql` mirrors the base schema but migrations are the startup path through `db.migrate()`.

## Current persisted representations relevant to Harness v1

### `agents`

Important fields: `provider`, `model`, `params_json`, `api_key_ref`, `home_path`, `enabled`, `delegation_enabled`.

Current owners:

- `cerebro/models.py::Agent`
- `cerebro/store.py::get_agent/list_agents/upsert_agent`
- `cerebro/agents_loader.py`
- `cerebro/service.py::_provider_for`, `_agent_params`, `_polling_agents`

Impact: provider transport identity, model selection, inference parameters, poll settings and CLI-harness settings are currently collapsed into the agent row/untyped JSON. A distinct Harness v1 model/provider configuration may need a new representation or a compatibility projection; #207 does not choose which.

### `messages`

Columns: `id`, `channel_id`, `author_id`, `author_kind`, `kind`, `body`, `quote_msg_id`, `turn_id`, `depth`, `created_at`, `meta_json`.

Current owners:

- `cerebro/models.py::Message`
- `cerebro/store.py::append_message/get_message/list_messages`
- `cerebro/persistence.py::StoreAdapter.append_message/history`
- `cerebro/runtime.py`
- channel REST/WS routes and transcript import

This table is the most important migration boundary because it currently serves three roles:

1. Durable Slack-like collaboration transcript.
2. Input history for model inference through `Provider.stream(list[Message], ...)`.
3. Escape hatch for protocol metadata through `meta_json`.

Those roles are not equivalent.

#### `Message.meta_json` protocol state

Current OpenAI-compatible translation recognizes:

- assistant message metadata: `{"tool_calls": [{"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}]}`
- tool message metadata: `{"tool_call_id": ..., "name": ...}`

`cerebro/runtime.py::AgentRuntime._generate()` creates those shapes as synthetic `Message` instances for subsequent tool rounds. `cerebro/providers/openai_compatible.py::to_chat_messages()` reads them and reconstructs OpenAI `assistant.tool_calls` / `tool` messages.

Crucially, those synthetic messages are appended only to the local `transcript` variable. They are not written through `StoreAdapter.append_message()`. The durable channel transcript normally receives only the final accepted agent message (or an error/system message). Therefore `meta_json` is capable of storing protocol state, but the current live tool loop generally does not persist that state at all.

Other current `meta_json` use exists in `store._normalize_message_row()` for imported transcript provenance (`imported`, `source.author`). That means treating the entire column as “provider protocol JSON” would also conflate unrelated metadata.

Impact for #206: durable canonical inference items, provider-opaque items/provider call refs and pre-side-effect checkpoints do not have an existing first-class representation. `messages.meta_json` is not an adequate existing proof of durability and should be handled as compatibility debt in migration planning.

### `tool_calls`

Schema/model fields already exist: `id`, `message_id`, `agent_id`, `server`, `tool`, `args_json`, `result_json`, `status`, `error`, `started_at`, `ended_at`, `duration_ms`.

Current owner: schema + `cerebro/models.py::ToolCall` only in the current inventory. `cerebro/store.py` has no tool-call CRUD and `AgentRuntime._run_tool()` does not insert/update this table.

Impact: the table’s presence does not mean Cerebro already has durable tool admission/execution semantics. In particular, it currently does not establish the #206 “exactly one terminal outcome per admitted tool call” invariant, an execution idempotency boundary, or a checkpoint before side effects. If reused later, semantics and migration would need to be made explicit by #206/implementation work.

### `tasks`

Product work-item fields: `id`, `title`, `body`, `owner_agent_id`, `channel_id`, `team_id`, `status`, `artifacts_json`, timestamps/due date.

Current owners: `cerebro/store.py` task CRUD and `cerebro/tools.py` task core tools.

Impact: these are collaboration/work-management tasks, not harness reducer effects, provider requests, child turns or execution checkpoints. Harness v1 terminology should avoid silently overloading this table.

There is also a small semantic mismatch worth preserving in the inventory: `models.Task.status` comments `open/in_progress/blocked/done/cancelled`, while `store.create_task()` currently defaults to `pending`.

### `audit_events`

Schema/model exists (`cerebro/models.py::AuditEvent`), with `ts`, actor, action, target, `detail_json`, revert fields.

No store CRUD or live runtime writer/subscriber was found in the pinned source. `cerebro/hub.py`’s module documentation says an audit log can be a subscriber, but that is not a current durable execution-event implementation.

Impact: this should not be counted as an existing Harness v1 semantic event log. Whether it can be reused is an architecture decision for #206.

### `budget_usage`

`cerebro/usage.py::record_turn_usage()` accumulates native/provider-observed token counts per agent/day. `AgentRuntime._generate()` calls it when a `Usage` delta is emitted. Accounting failure is intentionally non-fatal to the turn.

Impact: current usage is aggregate accounting, not a provider-call record. If Harness v1 needs usage attached to individual durable provider calls/steps, the current table alone cannot identify which request consumed the tokens.

### `agent_quota`

Added by migration 004. This records self-reported external-harness quota windows with attribution and freshness. It is deliberately distinct from measured token usage.

Impact: preserve that provenance distinction. External harness quota should not be inferred to be provider-native usage merely because `CliAgentProvider` currently satisfies the same `Provider` protocol.

### `leases`

Durable resource lease state is handled by `store.acquire_lease/release_lease/renew_lease/list_leases/sweep_expired_leases` and migration 003. It already uses `db.run_in_writer()` for atomic ownership changes.

Impact: this is an example of durable, transactional coordination state, but it is not current turn admission/cancellation/checkpoint state.

### Channel/member/read state

`channels`, `channel_members`, `messages`, plus migration 002’s `last_read_message_id` form the Slack-like durable product layer. `ChannelPoller` does not persist its own per-agent polling cursor; it derives channel movement from max message id but keeps “seen,” backoff and in-flight state in memory.

Impact: Harness migration should preserve channel/message semantics above the harness while recognizing that wake delivery state is not currently restart-durable.

## What is not persisted today

At the pinned baseline, the following Harness v1-relevant state has no first-class durable representation:

- a turn lifecycle/status record independent of collaboration messages;
- reducer state or effect queue;
- immutable provider-call `StepSnapshot`;
- canonical ordered inference items distinct from channel `Message`;
- provider-native response/call ids or opaque replay items;
- the live assistant tool-call item before execution;
- live tool result item fed back to the model;
- admitted tool call lifecycle/terminal outcome despite the unused `tool_calls` table;
- raw tool result versus bounded model-visible projection;
- retry/recovery/suspend state;
- cancellation request/outcome state beyond transient Hub event + task cancellation;
- `TurnGuard` counters/freeze/start time;
- provider semaphore state;
- poller cursor/backoff/in-flight state;
- exact context/model/tool catalog/params used for a particular provider request;
- per-provider-call usage linkage;
- Hub event sequence/event history.

## Atomicity already available

`db.run_in_writer(fn)` executes a caller-supplied operation in the single writer under `BEGIN IMMEDIATE`, with commit/rollback. This is the existing primitive most relevant to #206’s requirement to checkpoint replay state before a side-effecting tool executes. #207 does not prescribe a table layout, but any migration design should account for the fact that current `AgentRuntime._generate()` performs no such durable transaction before invoking `_run_tool()`.

## Compatibility pressure around `messages`

A migration that changes harness persistence cannot assume `messages` is private harness storage. It is directly consumed by:

- REST history in `cerebro/api/routes_channels.py::get_channel_messages`;
- WebSocket/UI event payloads;
- `ChannelPoller` max-id wake detection;
- read/unread cursor logic;
- context/history projection;
- transcript import;
- collaboration/authorship tests.

That makes a compatibility projection or parallel harness state likely to be relevant to #206, but the choice between those approaches is intentionally left open here.

## Phase 1-critical data questions for #206

These are questions exposed by current source, not recommendations:

1. What durable object owns turn lifecycle independently of a channel `Message`?
2. Where are canonical inference items stored, and how are collaboration messages projected into them?
3. What must be committed atomically before a side-effect tool call begins?
4. How are provider-native replay ids/opaque items associated with a canonical turn/step without leaking provider schema into `messages.meta_json`?
5. Does the existing unused `tool_calls` table get migrated/redefined or left as legacy schema?
6. How is an immutable provider-call snapshot represented so model/provider/tool-policy changes cannot alter an in-flight replay?
7. Which execution events are durable semantics versus transient Hub/UI telemetry?
8. How are cancellation/recovery states represented across restart?
