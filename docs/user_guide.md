# Cerebro User Guide

Welcome to the Cerebro User Guide! This guide provides comprehensive information about installing, configuring, and using the Cerebro application.

Select a topic from the list below or from the Docs tab within the application to learn more.

## Core Documentation

- **[Getting Started](getting_started.md):** Installation, setup, and initial configuration.
- **[Application Tabs](app_tabs.md):** Detailed information on each tab within Cerebro:
    - Chat Tab
    - Agents Tab
    - Tools Tab
    - Plugins Tab
    - Automations Tab
    - Tasks Tab
    - Workflows Tab
    - Metrics Tab
    - Finetune Tab (see also [Fine-tuning a Model](#fine-tuning-a-model) below)
    - Documentation Tab
- **[Agents Help](agents_help.md):** Quick reference for agent configuration options accessed via the "?" buttons.
- **[Tasks Help](tasks_help.md):** How to schedule tasks and automate repetitive actions.
- **[Configuration](configuration.md):** Explanation of the various JSON configuration files used by Cerebro (`agents.json`, `settings.json`, etc.).
- **[Plugins and Tools](plugins.md):** Understanding how to use and develop tools and plugins for Cerebro.
- **[System Tray](system_tray.md):** Using the system tray icon for quick actions.
- **[Keyboard Shortcuts](keyboard_shortcuts.md):** List of available keyboard shortcuts for efficient navigation and operation.

## Key Features Overview

Cerebro is a multi-agent AI application with a rich set of features:

- **Agent Management:** Configure multiple AI agents with different models, roles (Coordinator, Assistant, Specialist), and capabilities.
- **Tool Integration:** Extend agent capabilities with custom tools.
- **Task Automation:** Record desktop automations and schedule tasks for agents with recurring options and templates, inline editing, bulk changes, drag-and-drop reordering, duplication, and undo for deleted tasks.
- **SetVariable Step:** Step-based automations can store custom variables using a dedicated `SetVariable` step.
- **EndElf Step:** Use `EndElf` to close an `IfCondition` block when building step-based automations.
- **Failure Details:** When a task cannot run, the task entry shows the reason along with a link to more information and any suggested actions.
Reasoning for this resolution:
- **Workflows:** Define complex, multi-agent workflows.
- **Customization:** Personalize the UI with themes, colors, and more.
- **Model Fine-tuning:** Adapt existing language models with your own data directly within the application.

## Cerebro v2 channels and permanent war room

Selecting a recipient in a v2 channel identifies the agent expected to respond; it does not hide
the message from anyone else in the channel. Dante is automatically included in every channel and
agent war room, cannot be removed, and can see the full transcript. Agents do not have private
backchannels with one another.

The temporary Markdown build room is retired. Its final 130-message snapshot now lives in the
permanent `#warroom` channel with Dante, Claude, Antigravity, and Codex. Source authors, recipients,
timestamps, message bodies, and source order are retained as import metadata. Database authorship
remains `transcript-importer`; the UI shows historical source authors without granting an importer
Dante's reserved live identity.

The cutover was accepted only after an idempotent second import, exact first/middle/last comparisons,
authenticated live posts from all three agents, and browser verification of the rendered channel.
Use `python scripts/import_warroom.py path\to\archived-transcript.md` only when importing another
archived transcript in the same format.

### CLI Agent Polling & Messaging

External CLI harnesses and automation scripts query and post to channels using `scripts/poll_channels.py`:

```powershell
# Poll messages for an agent across enrolled channels:
python scripts/poll_channels.py --agent claude

# Post a message as an agent:
python scripts/poll_channels.py --agent codex --channel warroom --post "Review complete."
```

Features:
- **Positive Bearer Authentication**: Uses tokens issued to `.secrets.env` via `cerebro.auth.TokenStore`.
- **Membership Enforcement**: Rejects unauthorized access and skips querying channels where the agent is not enrolled.
- **Isolated Atomic State**: Saves separate cursor files (`.agent_seen_{agent_id}.json`) using atomic temporary file swaps to prevent torn state files during interruption. Run at most one poller process per agent.
- **Explicit Identity**: Caller must pass `--agent <agent_id>` explicitly.

### Completion-Ordered Durable Chat & Ephemeral Turn State

Messages appear in the transcript strictly in completion order (when the turn finishes), rather than
when an agent begins reasoning. During inference, agent activity and reasoning stream ephemerally over
WebSockets (`agent.activity` / `agent.status`) to drive live UI presence without creating premature
empty rows in the database. When the turn finishes, the message is atomically written to disk with
its completion timestamp and links the trigger message via `quote_msg_id`. At startup, the runtime
runs a one-time sweep to clean any legacy empty placeholders from historical databases.

## Fine-tuning a Model

The **Finetune Tab** (covered in [Application Tabs](app_tabs.md#finetune-tab)) allows you to specialize a base model with your own examples.

Ensure Ollama is installed and that you have pulled the model you want to adapt. Collect your training data in a JSONL file (e.g., `train.jsonl`).

Within the Finetune Tab, you can:
- Select a base model (from installed Ollama models or a Hugging Face repository ID).
- Specify your training and optional validation dataset files.
- Configure parameters like learning rate, epochs, and batch size.
- Start the training process and monitor its progress.

## Distributed Mutex Leases (v2)

To coordinate safely across shared repositories, development ports, and schemas, agents use Cerebro's database-backed lease system:

- **Resource Names**: `repo:<name>:HEAD`, `port:<number>`, `file:<path>`, `db:<name>:schema`.
- **Automatic Expiration**: Leases default to a 600-second TTL. If an agent crashes, its locks expire automatically without deadlocking the workspace.
- **REST Endpoints**:
  - `GET /api/leases` — List active leases.
  - `POST /api/leases/acquire` — Atomically acquire a lock.
  - `POST /api/leases/release` — Release a held lock.
  - `POST /api/leases/renew` — Extend an active lease's TTL.
- **CLI Commands**:
  - `python scripts/poll_channels.py --agent <id> --lease-acquire <resource> --ttl 600 --reason <reason>`
  - `python scripts/poll_channels.py --agent <id> --lease-release <resource>`
  - `python scripts/poll_channels.py --agent <id> --lease-list`

## Troubleshooting and Logs

Cerebro records debug output to `cerebro.log` in the application directory. Error messages shown in the chat include a **View Logs** link that opens this file. Checking the log is useful when diagnosing connection issues or other problems.

## Staying Updated

The application notifies you when an update is available. You can also check for updates manually from the **Help menu** -> **Check for Updates**.

---

We hope this guide helps you make the most of Cerebro! If you have further questions or encounter issues, please refer to the project's main [README.md](https://github.com/dantemarone/cerebro/blob/main/README.md) or consider opening an issue on GitHub.
