# Configuration

Cerebro stores data in several JSON files in the application directory.

## agents.json
Defines every agent and their settings. The default configuration includes a **Default Agent** with all bundled tools enabled. If no agent configuration exists, its model is set to the first entry from `ollama list` when available.

## workflows.json
Stores the definitions of all created workflows. Each entry typically includes:
    - `name`: The unique name of the workflow.
    - `mode`: 'Agent Managed' or 'User Managed'.
    - `agents`: (For Agent Managed) A list of agent names involved.
    - `steps`: (For User Managed) A list of steps, each defining an `agent_name` and `prompt`.
    - `description`: An optional description for the workflow.

## automations.json
Contains recorded desktop automation sequences. Each entry usually includes:
    - `name`: The name of the automation.
    - `events`: A list of recorded mouse and keyboard events (e.g., type, click, coordinates, timing).
    - `duration`: The total duration of the recording.

## tools.json
Metadata and Python code for tools. Plugins placed in `tool_plugins` or installed via the `cerebro_tools` entry point are loaded automatically.

## tasks.json
Holds scheduled tasks. Each entry has `id`, `creator`, `agent_name`, `prompt`, `due_time`, `created_time`, `status` and `repeat_interval` fields. Tasks are also exported to the operating system scheduler using `run_task.py` so they can execute when Cerebro is closed.

## metrics.json
Records tool usage counts, task completions and average response times.

## chat_history.json
Stores conversation history for exporting or resuming later. The file is recreated each time the application starts unless you export the history.

## settings.json
Stores global preferences such as theme, screenshot interval and
``summarization_threshold``. Set the threshold to 0 to disable automatic
summaries.
It also stores:
    - `accent_color`: Defines the primary UI accent color for themes.
    - `screenshot_interval`: (Global) Sets the default interval in seconds between desktop screenshot captures for agents with Desktop History enabled. This can be overridden by individual agent settings.

## Understanding Debug Mode
Debug mode is enabled by default. Set `DEBUG_MODE=0` before launching to disable verbose console logging.
- When enabled (default), Cerebro outputs verbose logs to the console. This is invaluable for developers or users trying to diagnose issues, understand agent decision-making, or see detailed tool execution information.
- To disable debug mode, set the environment variable `DEBUG_MODE=0` before launching the application (e.g., `DEBUG_MODE=0 python main.py` on Linux/macOS or `set DEBUG_MODE=0 & python main.py` on Windows).
- Disabling debug mode can lead to a cleaner console output for regular use.
