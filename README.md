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
