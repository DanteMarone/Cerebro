# Cerebro User Guide

Cerebro is a cross‐platform desktop application for chatting with multiple AI agents powered by the
Ollama API. Each agent has a configurable role and capabilities. This document explains how to install
Cerebro and describes every tab and feature so you can quickly become productive.

## Installation

1. Clone the repository and change into the directory:
   ```bash
   git clone https://github.com/dantemarone/cerebro.git
   cd cerebro
   ```
2. (Optional) Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   # Linux/macOS
   source venv/bin/activate
   # Windows
   venv\Scripts\activate
   ```
3. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
4. Start the Ollama server separately and then run the application:
   ```bash
   python main.py
   ```
   Set the environment variable `DEBUG_MODE=1` to enable verbose logging.

To create a Windows installer, install PyInstaller and run `build_windows_installer.bat`. The resulting executable will appear in the `dist` directory.

## Application Overview

The main window is divided into several tabs. Use the numbered shortcuts `Ctrl+1` – `Ctrl+6` to switch
between them.

## Chat Tab

The Chat tab is the primary interface for interacting with your agents.
- Enter a prompt at the bottom and press **Send**.
- Messages appear in a scrollable pane. While an agent is generating a reply, a "typing" indicator is
  shown.
- Use the menu in the upper‑right corner to copy, export or clear the conversation history. Each
  session starts with a clean slate.
- When many messages accumulate they are automatically summarized so prompts remain short.

Agents with *desktop history* enabled attach recent screenshots at a configurable interval. This helps
provide visual context for desktop‑based tasks.

## Agents Tab

The Agents tab allows you to create, edit and delete AI agents. Each agent stores the following
settings:

- **Model** – select an installed Ollama model such as `llava` or `llama3.2-vision`.
- **Temperature** – controls randomness of responses.
- **Max Tokens** – maximum length of a single reply.
- **Custom System Prompt** – additional instructions sent before every conversation.
- **Enabled** – toggle to activate or disable the agent.
- **Role** – choose between *Assistant*, *Coordinator* or *Specialist*.
- **Description** – short summary used by Coordinators when delegating tasks.
- **Agent Color** – color used for chat messages.
- **Managed Agents** – for Coordinators, choose which agents they can delegate to.
- **Tool Use** – allow the agent to call tools.
- **Enabled Tools** – choose which tools are available when tool use is on.
- **Enable Thinking** – if checked, the agent will generate intermediate
  thoughts before answering.
- **Thinking Steps** – number of thinking iterations.
- **Desktop History Enabled** – capture screenshots to give the model visual context.
- **Screenshot Interval** – seconds between captures when desktop history is on.

Press **Save** after editing to persist your changes. Use **Add New Agent** to create a new entry.
Deleting an agent permanently removes it.

## Tools Tab

Tools extend Cerebro with custom Python scripts that agents can invoke. The tab lists tools from
`tools.json` and from any plugin modules.

1. **Add Tool** – provide a name, description and script defining `run_tool(args)`.
2. **Edit Tool** – modify an existing tool.
3. **Delete** – remove a tool and its script file.
4. **Run** – execute a tool manually with JSON arguments.

Bundled plugins include:
- **file-summarizer** – create a short summary of a text file or provided text.
- **web-scraper** – download and sanitize text from a URL.
- **math-solver** – evaluate mathematical expressions.
- **windows-notifier** – display a Windows 11 notification using `win10toast`.
- **desktop-automation** – launch programs or move files through OS commands.

Agents call tools by returning a JSON block in the format produced by
`generate_tool_instructions_message()`.

## Tasks Tab

Scheduled prompts appear in both a list and calendar view. Dates with tasks display a red dot and the
current day is highlighted.

- **Add Task** – create a prompt for a specific agent. The default due time is one minute from now.
- **Edit** – change an existing task.
- **Delete** – remove a task after confirmation.
- **Toggle Status** – mark the selected task as completed or pending.
- **Repeat Interval** – optional number of minutes after which the task should repeat.

When a task’s due time arrives the associated prompt is sent automatically. Combine this feature with
the `windows-notifier` tool to create desktop reminders on Windows 11. Use `desktop-automation` to act on
screenshot analysis when needed. Tasks can optionally register with
the operating system scheduler so they run even if Cerebro is not open. Windows uses Task Scheduler while
Unix-like systems use cron.

## Metrics Tab

This tab reads statistics from `metrics.json` and shows:
- **Tool Usage** – how many times each tool has been executed.
- **Task Completions** – number of tasks finished by each agent.
- **Average Response Times** – mean response time of each agent in seconds.

Metrics are updated whenever agents use tools or complete tasks.

## Documentation Tab

Displays this guide within the application so you can review instructions without leaving Cerebro.

## Settings Dialog

Global preferences are available under **Settings**.
- Toggle dark mode and change your displayed user name and color.
- Update the Ollama runtime or pull the latest version of a model using the provided buttons.
- Errors during updates are shown in a pop‑up message.

## Configuration Files

Cerebro stores its data in several JSON files located in the application directory.

### agents.json
Defines every agent and their settings. See the fields listed in the Agents Tab section for details.

### tools.json
Contains tool metadata and Python code. Plugins placed in `tool_plugins` or installed with the
`cerebro_tools` entry point are loaded automatically.

### tasks.json
Holds scheduled tasks. Each entry has `id`, `creator`, `agent_name`, `prompt`, `due_time`, `status` and
`repeat_interval` fields.
Tasks are also exported to the operating system scheduler using `run_task.py` so they can fire when Cerebro is closed.

### metrics.json
Records tool usage counts, task completions and average response times.

### chat_history.json
Stores conversation history for exporting or resuming later. The file is recreated each time the
application starts unless you explicitly export the history.

## Debug Mode

Set `DEBUG_MODE=1` before launching to enable verbose logging in the console. This is useful for
diagnosing issues with tools or agent configuration.

## Developing Plugins

You can extend Cerebro by creating additional tools. Place a Python file in the `tool_plugins`
directory with a `TOOL_METADATA` dictionary and a `run_tool(args)` function. Restart Cerebro and the
new tool will appear in the Tools tab.

---

With this guide you should be able to install Cerebro, configure agents and fully leverage every tab
of the application without prior experience.
