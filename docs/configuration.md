# Configuration

Cerebro stores data in several JSON files in the application directory.

## agents.json
Defines every agent and their settings. The default configuration includes a **Default Agent** with all bundled tools enabled. If no agent configuration exists, its model is set to the first entry from `ollama list` when available.

## tools.json
Metadata and Python code for tools. Plugins placed in `tool_plugins` or installed via the `cerebro_tools` entry point are loaded automatically.

## tasks.json
Holds scheduled tasks. Each entry has `id`, `creator`, `agent_name`, `prompt`, `due_time`, `created_time`, `status` and `repeat_interval` fields. Tasks are also exported to the operating system scheduler using `run_task.py` so they can execute when Cerebro is closed.

## metrics.json
Records tool usage counts, task completions and average response times.

## chat_history.json
Stores conversation history for exporting or resuming later. The file is recreated each time the application starts unless you export the history.

## Debug Mode

Set `DEBUG_MODE=1` before launching to enable verbose console logging. This helps diagnose issues with tools or agent configuration.
