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

### Harness v1 Durable Recovery Substrate

Cerebro now has additive SQLite storage for future restart-safe Harness execution. It records
causal wake admission, turn state, ordered inference history, provider dispatch barriers, and tool
outcomes whose external truth is uncertain. On an explicit Harness recovery scan, non-terminal work
that the current phase cannot safely continue becomes durably `suspended` with a reason; uncertain
tool effects remain visible as needing attention after restart. Recovery isolates damaged records
per turn so a corrupt or missing reference cannot prevent later turns from receiving a safe
disposition. Canonical history cannot be superseded across an effect that may have escaped, even
after the database is closed and reopened.

Cerebro also records an immutable **executable snapshot** of what one agent step could run: which
provider and model, which exact tools with which exact executable bindings, which permissions, and
which security-revocation epoch. A tool call from that snapshot can only become runnable after one
atomic checkpoint commits every durable fact it depends on, and an external tool can only actually be
invoked after Cerebro has durably written down that the call may have escaped. If the machine dies
before that point, no external tool ran. If it dies after, the uncertainty stays visible instead of
being tidied into a fabricated failure.

If the thing behind a tool changes between the snapshot and the call — an MCP server restarts, a
permission is revoked, a trust tier is lowered — the old call is refused under its original identity.
It is never quietly redirected to whatever now answers to the same name.

When a tool does return, Cerebro keeps the complete output as durable evidence and shows the model a
bounded excerpt that says explicitly how much was left out. The full output never goes into the chat
transcript, the event stream or the logs.

This is currently an internal storage and diagnostic substrate, not a user-facing execution mode.
The production service still uses `AgentRuntime`, and startup does not invoke the Harness recovery
driver. The new code does not send provider requests during normal chat, and no ordinary agent turn
is routed through it. Terminal Harness rows cannot authorize new provider/tool dispatch, but an
effect already marked uncertain can still be reconciled without erasing any other outstanding
attention.

### Agent Silence & Silent Completion (§9.3)

In multi-agent channels, agents speak only when they have additive domain knowledge to contribute.
An agent can decline to speak in two valid ways:
- **Explicit PASS Token**: Emitting `PASS` (case-insensitive, ignoring whitespace and trailing period).
- **Silent Completion**: Completing with provider `finish_reason: "stop"`, zero visible content tokens, and no tool calls.

Both cases are treated as valid silent completions:
- No durable message or error row is appended to the channel transcript.
- The agent's activity status cleanly transitions back to `idle`.
- An ephemeral `turn.discarded` WebSocket event (carrying structured `reason: "silent_stop"` or `reason: "pass"`) is published for runtime observability.
- Genuine failures (such as `finish_reason: "length"` token exhaustion or backend errors) continue to produce descriptive error messages.

### Usage and quota board

See what each agent has spent today and what each says it has left. Full detail:
[USAGE_BOARD.md](USAGE_BOARD.md).

Two things are deliberately *not* done:

- Measured tokens and self-reported percentages are never added together or shown in one column.
  They are different kinds of fact, and only one is something Cerebro observed.
- A self-reported number is never shown without its age. After 90 minutes it is marked stale.

An agent with no measured tokens and no reported window is still listed. "We do not know what this
agent is costing" is worth seeing; dropping the row would hide it.

**Relaying a quota by hand.** If an agent cannot see its own meter, you can report for it:

```bash
curl -X POST http://127.0.0.1:8765/api/usage/quota   -H "Content-Type: application/json"   -d '{"agent_id": "codex", "window": "weekly", "pct_remaining": 16}'
```

That entry appears as **relayed**, attributed to you rather than to the agent. An agent attempting
the same thing for a teammate is refused.

### Backing up your Cerebro data

Cerebro's database uses SQLite WAL mode, so recent activity lives in `data/cerebro.db-wal` rather
than in `data/cerebro.db`. Copying the main file alone can hand back an empty workspace with no
error, and copying all three files while Cerebro runs can produce a torn snapshot.

Take a consistent online snapshot in one command:

```bash
sqlite3 data/cerebro.db "VACUUM INTO '/your/backup/cerebro.db'"
```

Or stop Cerebro first and copy `data/cerebro.db`, `data/cerebro.db-wal` and `data/cerebro.db-shm`
together.

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

## Core Tools & Trust Tiers (§10.2, §8.8)

Cerebro implements in-process system tools gated by trust tier:

- **Trust Tiers**:
  - `sandboxed` (default): Private agent memory and scratchpad only (`scratchpad_read`, `scratchpad_append`, `memory_write`, `memory_list`, `memory_read`). Gated from filesystem, channels, and task modification.
  - `standard` / `full`: Expanded capabilities including `fs_read` (confined file read), `fs_list` (confined directory listing), `list_agents` / `get_agent_profile`, `create_channel` / `post_message`, and durable `task_create` / `task_list` / `task_get` / `task_update`.

- **Confinement**:
  All file access tools strictly enforce workspace and home directory confinement, preventing path traversal across boundaries.

## Staying Updated

The application notifies you when an update is available. You can also check for updates manually from the **Help menu** -> **Check for Updates**.

---

We hope this guide helps you make the most of Cerebro! If you have further questions or encounter issues, please refer to the project's main [README.md](https://github.com/dantemarone/cerebro/blob/main/README.md) or consider opening an issue on GitHub.

