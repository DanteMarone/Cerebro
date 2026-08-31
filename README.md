# Cerebro: A Multi-Agent AI Chat Application

> **Cerebro v2 is in design.** The current PyQt5 + Ollama application described below is what
> ships on `main` today. The next major version — a local, Slack-shaped agentic workspace on
> LM Studio and Gemini, with MCP tools, per-agent memory and autonomous scheduling — is specified
> in **[Cerebro v2 Architecture & Build Plan](docs/CEREBRO_V2_ARCHITECTURE.md)**
> (vision: [v2 Spec](docs/CEREBRO_V2_SPEC.md)). It will be built on the `v2` branch.

Cerebro is a desktop chat application built with PyQt5 that allows you to interact with multiple AI agents powered by the Ollama API. It provides a flexible and extensible framework for creating and managing AI agents with different roles, capabilities, and personalities.

**Full documentation is available within the application under the 'Docs' tab or online in the [User Guide](docs/user_guide.md).**

## Key Features

Cerebro offers a rich set of features to enhance your interaction with AI models:

*   **Multiple AI Agents:** Create and manage multiple AI agents, each with its own model, system prompt, role (Coordinator, Assistant, Specialist), and appearance. (Details: [Application Tabs - Agents](docs/app_tabs.md#agents-tab), [Configuration - agents.json](docs/configuration.md#agentsjson))
* **Tool Integration:** Grant agents the ability to use tools (Python scripts) to perform actions and retrieve information. Tools can be bundled, custom-developed, or installed as plugins. Tools that need extra setup are marked **Needs Configuration** and provide a Setup button. (Details: [Plugins and Tools](docs/plugins.md), [Application Tabs - Tools](docs/app_tabs.md#tools-tab), [Tools Issue #4 Response](docs/tools_issue_4_response.md))
* **Tool Status Indicators:** The Tools tab now shows a status column with color-coded icons so you can easily see if a tool is enabled or disabled.
*   **Thinking Mode:** Enable agents to iteratively generate a series of thoughts before producing a final answer. (Details: [Application Tabs - Agents](docs/app_tabs.md#agents-tab))
* **Automations:** Record and replay desktop actions. Step-based automations can be composed by double-clicking steps, rearranged via drag and drop, and can use a dedicated step to store custom variables. (Details: [Application Tabs - Automations](docs/app_tabs.md#automations-tab))
* **Task Scheduling:** Schedule prompts for agents to run at specific times, with recurring options (daily/weekly/monthly or custom minutes), drag-and-drop reordering, duplication, undo after deletion, inline editing, bulk editing, and reusable templates. (Details: [Application Tabs - Tasks](docs/app_tabs.md#tasks-tab))
* * **Task Progress Indicators:** View elapsed time and an ETA for scheduled tasks.
*   **Failure Details:** When tasks fail or are put on hold the reason, a link to more information, and suggested actions appear in the task list.
*   **Workflow Builder:** Design and execute reusable, multi-agent workflows. (Details: [Application Tabs - Workflows](docs/app_tabs.md#workflows-tab))
* **Chat Management:** Save, export, clear, and search chat history. Messages include avatars, colored names and timestamps grouped by date. Use the chat menu to search saved history. Long conversations are automatically summarized. (Details: [Application Tabs - Chat](docs/app_tabs.md#chat-tab))
*   **Desktop History:** Allow agents to receive periodic screenshots of your desktop for visual context. (Details: [Application Tabs - Agents](docs/app_tabs.md#agents-tab))
*   **Customizable UI:** Includes light/dark modes, configurable colors, and a system tray icon for quick actions. (Details: [System Tray](docs/system_tray.md), [Configuration - settings.json](docs/configuration.md#settingsjson))
*   **Configurable Ollama Port:** Change the port used to contact the Ollama server in the Settings dialog.
*   **Metrics & Fine-tuning:** Monitor application metrics and fine-tune language models with your own datasets. (Details: [Application Tabs - Metrics](docs/app_tabs.md#metrics-tab), [Application Tabs - Finetune](docs/app_tabs.md#finetune-tab), [User Guide - Fine-tuning](docs/user_guide.md#fine-tuning-a-model))

## In-App Documentation

The most comprehensive and up-to-date documentation is available directly within the Cerebro application. Navigate to the **Docs** tab (or press `Ctrl+0`) to browse the full user guide, including detailed explanations of all features, configuration options, and development guides.

Contextual help buttons (`?`) appear in the Agents tab next to complex settings. Clicking these opens the new **Agents Help** section of the documentation for quick reference.

You can also view the documentation online here: **[Cerebro User Guide](docs/user_guide.md)**

## Requirements (v2)

*   Python 3.14 or higher
*   Dependencies managed via hash-locked `requirements.txt` / `requirements-dev.txt`
*   LM Studio local server (`http://127.0.0.1:1234`) and/or Google Gemini API key

## Getting Started (v2)

1.  **Clone and switch to branch `v2`:**
    ```bash
    git checkout v2
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    .venv\Scripts\activate  # Windows
    # source .venv/bin/activate  # macOS/Linux
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements-dev.txt
    ```
4.  **Run the application server:**
    ```bash
    python main.py
    ```
5.  **Verify health:**
    ```bash
    curl http://127.0.0.1:8765/api/health
    ```

### Channel visibility and permanent war room (v2)

Recipient selection routes attention; it does not create a private audience. Dante is added to
every channel automatically, cannot be removed, and sees the complete shared transcript including
agent war rooms. Cerebro does not support hidden agent-to-agent channels.

The temporary append-only Markdown build room has been retired. Its complete 130-message snapshot
was imported into the permanent `#warroom` channel and verified for count, ordering, representative
content, attribution metadata, and idempotency before the legacy source and viewer were removed.

For an archived Markdown transcript using the same format, an explicit path can still be imported:

```powershell
python scripts/import_warroom.py path\to\archived-transcript.md
```

The importer creates the Cerebro Core team, seeds missing Claude, Antigravity, and Codex CLI-agent
profiles, includes Dante as the permanent owner member, and preserves source author, recipient,
timestamp, order, and body metadata. Imported rows are stored as `transcript-importer` so historical
content cannot claim Dante's live identity; the UI uses separate source-attribution metadata for
display. Rerunning an import against the same archived source adds no duplicate messages.

### CLI Agent Poller & Messaging (`scripts/poll_channels.py`)

External CLI agent harnesses (e.g. Antigravity, Codex, Claude) or automated scripts interact with
Cerebro channels via `scripts/poll_channels.py`:

```powershell
# Poll all enrolled channels for unseen messages:
python scripts/poll_channels.py --agent antigravity

# Post a message as an agent to a specific channel:
python scripts/poll_channels.py --agent antigravity --channel warroom --post "Status update"
```

The CLI tool authenticates using positive bearer tokens from `.secrets.env`, verifies channel
membership before polling messages, and maintains isolated per-agent cursor files
(`.agent_seen_{agent_id}.json`) using atomic temporary file swaps to prevent torn state files.
Run at most one poller process per agent identity. Identity (`--agent`) is required.

### Distributed Mutex Leases (§8.7)

Cerebro implements an automated, database-backed mutual exclusion (mutex) lock manager:
* **Endpoints**: `/api/leases`, `/api/leases/acquire`, `/api/leases/release`, `/api/leases/renew`.
* **Events**: Real-time WebSocket event broadcasts (`lease.acquired`, `lease.released`, `lease.expired`).
* **CLI Management**:
  ```powershell
  # Acquire a lease on a shared resource:
  python scripts/poll_channels.py --agent antigravity --lease-acquire "repo:Cerebro:HEAD" --ttl 600 --reason "merging slice"

  # Renew an active lease:
  python scripts/poll_channels.py --agent antigravity --lease-renew "repo:Cerebro:HEAD" --ttl 600

  # Release an active lease:
  python scripts/poll_channels.py --agent antigravity --lease-release "repo:Cerebro:HEAD"

  # List active leases:
  python scripts/poll_channels.py --agent antigravity --lease-list
  ```
* **Conflict & Expiry Enforcement**: Prevents collision across unshareable global state (`repo:<name>:HEAD`, `port:<num>`, `file:<path>`). Unrenewed leases automatically expire safely via TTL.

### Lease Commit Guard (advisory)

An optional pre-commit hook refuses commits touching files you do not hold a lease on. It is a
**workflow guard, not a security boundary** — `--no-verify` bypasses it. Full detail:
**[docs/LEASE_GUARD.md](docs/LEASE_GUARD.md)**.

```bash
git config core.hooksPath .githooks
git config cerebro.agent <your-agent-id>
```

It asks `GET /api/leases/check` rather than reimplementing the matching rules, covers directory
leases, requires holding both ends of a rename, and fails closed when it cannot verify.

### Deployment (landing is not shipping)

Python changes need a service restart; static assets do not. See
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

```bash
python scripts/deploy.py --check     # is the running service current?
python scripts/deploy.py             # backup, verify, restart, health-check
```

`/api/health` reports `running_commit`, `repo_commit`, `stale` and `schema_version`. The running
commit is captured once at process start, never re-read -- a process can only honestly report the
code it loaded. The UI shows a banner while the service is stale.

### Usage & Quota Board (§13.2)

Cerebro tracks what the team costs in two ways and never mixes them, because only one of them is
something Cerebro actually observed. Full detail: **[docs/USAGE_BOARD.md](docs/USAGE_BOARD.md)**.

* **Measured** — for providers Cerebro calls itself (LM Studio, Gemini, any OpenAI-compatible
  endpoint), real token counts from each turn accumulate per agent per day in `budget_usage`.
* **Self-reported** — for CLI-backed agents (`claude`, `codex`, `agy`) the governing number is how
  much of a five-hour or weekly *harness* window remains. That lives in another vendor's process and
  Cerebro cannot see it, so the agent reports it and Cerebro records who said it and when.

Self-reported figures always carry their age and are marked stale after 90 minutes — kept, not
deleted, because "Codex said 16% four hours ago" is still information; showing it as current is the
bug.

| Route | Method | Who |
|---|---|---|
| `/api/usage` | GET | Any authenticated principal. Agents can see each other's usage and route work accordingly. |
| `/api/usage/quota` | POST | An agent may report **only for itself**; Dante may relay for any agent. |

```bash
# An agent reports its own remaining window:
curl -X POST http://127.0.0.1:8765/api/usage/quota   -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json"   -d '{"window": "5h", "pct_remaining": 62, "note": "plenty of headroom"}'
```

`reported_by` comes from the authenticated bearer principal and is never read from the request body.
An agent sending another agent's `agent_id` is refused with `403` and nothing is written.

### Backing up your data

The database runs in SQLite **WAL mode**. Recent writes live in `data/cerebro.db-wal` until they are
checkpointed into `data/cerebro.db`, and the WAL can hold far more than the main file — during the v2
build it reached 4 MB against a 520 KB main database.

**Copying `data/cerebro.db` on its own can lose almost everything.** A copy of the main file alone,
taken mid-session, restored to 0 messages while the live database held 363. The restore reports
success and hands you an empty workspace.

Copying all three files with `cp` while Cerebro is running is **also** unsafe — the files are read
one after another while writes continue, so the snapshot can be torn. Do one of these instead:

```bash
# Preferred: backup + verify, service untouched. Uses SQLite's own backup API.
python scripts/deploy.py --no-restart
```

```bash
# Alternative, if you have the sqlite3 CLI (it is NOT installed on this machine):
sqlite3 data/cerebro.db "VACUUM INTO '/your/backup/cerebro.db'"
```

```bash
# Or stop Cerebro first, then copy all three files together.
cp data/cerebro.db data/cerebro.db-wal data/cerebro.db-shm /your/backup/location/
```

### Completion-Ordered Durable Chat & Ephemeral Turn State (v2)

Messages appear strictly in the order they become communicable (when the turn completes), rather than
when an agent began thinking. During inference, reasoning and tool activity stream ephemerally over
WebSockets (`agent.activity` / `agent.status`) to drive live UI presence without creating premature
empty rows in the database. Upon completion, the finalized message is atomically appended with its
completion timestamp and broadcasted, linking the triggering prompt via `quote_msg_id`.

### Historical Placeholder Cleanup

Under v2 completion-ordered chat, turns never create uncommitted or empty rows in the database.
At startup, the runtime runs a one-time sweep to clean any legacy placeholders left behind from
historical database migrations.

### Harness v1 contracts and durable execution store (`cerebro/harness`)

Provider-neutral contracts for durable agent execution: prefixed identities, an ordered
`InferenceItem` history with per-item format versions, provider attempts with an explicit
pre-dispatch barrier, tool execution state that distinguishes "never dispatched" from "may have
escaped", and two separate adapter boundaries — `ProviderAdapter` for direct native inference and
`ExternalAgentAdapter` for CLI/vendor harnesses.

The additive Harness store persists turns, causal admission, sparse transition evidence, immutable
snapshot identity seams, conversation-owned inference history, provider attempts, and tool
execution uncertainty in dedicated SQLite tables. Writes use versioned compare-and-set semantics
inside the existing single-writer transactions. Durable escaped-effect truth protects causal
history during abandoned-attempt supersession, and terminal turns reject new snapshots, attempts,
tool admissions, or dispatch marks while still allowing an already uncertain effect to reconcile.
Discovery validates canonical payloads before lifecycle, attention, unresolved-effect, or
supersession filtering. A standalone, failure-isolated recovery scan durably suspends each loadable
turn that later Harness phases cannot safely resume; one damaged candidate cannot prevent later
turns from being classified, and the scan never invokes a provider or tool.

`cerebro/runtime.py::AgentRuntime` remains the live execution path. The durable Harness code is not
wired into `RuntimeService.start()` and cannot produce provider or tool side effects. Full detail:
**[docs/harness_v1_contracts.md](docs/harness_v1_contracts.md)**.

## Development & Testing

Run the linter and test suite:
```bash
flake8 .
PYTHONPATH=. pytest -q
```

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

## License

This project is licensed under the MIT License.
