# Cerebro: A Multi-Agent AI Chat Application

Cerebro is a desktop chat application built with PyQt5 that allows you to interact with multiple AI agents powered by the Ollama API. It provides a flexible and extensible framework for creating and managing AI agents with different roles, capabilities, and personalities.

## Key Features

*   **Multiple AI Agents:** Create and manage multiple AI agents, each with its own:
    *   Underlying language model selected from a dropdown of available Ollama models (e.g., `llama3.2-vision`, `llava`).
    *   Custom system prompt to define its behavior and personality.
    *   Temperature and max tokens settings to control response randomness and length (up to 100000 tokens).
    *   Assigned role:
        *   **Coordinator:** Manages other agents and delegates tasks.
        *   **Assistant:** Responds directly to user queries.
        *   **Specialist:** Responds only to requests from a Coordinator.
     *   Configurable color in the chat UI.
     *   Rename agents on the edit page and press **Save** to apply changes.
*   **Agent Roles:**
    *   **Coordinator:**  The Coordinator agent acts as a central hub. It receives user input, intelligently selects the most appropriate Specialist or Assistant agent to handle the request (based on agent descriptions and the nature of the query), and then displays the chosen agent's response. The Coordinator can also add context or modify the user's prompt before passing it on. When a Coordinator is done, it will pass the conversation on to another agent by specifying the phrase "Next Response By: [Agent Name]".
    *   **Assistant:** Assistant agents behave like traditional chatbots, responding directly to user input in the chat window.
    *   **Specialist:** Specialist agents are designed to handle specific types of tasks or answer questions within a particular domain. They do not engage directly with the user in the chat. Instead, they receive instructions or queries from a Coordinator agent and send their responses back to the Coordinator.
*   **Tool Integration:**
    *   Agents can be granted the ability to use tools.
    *   Tools are implemented as Python scripts that define a `run_tool(args)` function.
    *   Agents can invoke tools by including a specific JSON format in their response.
    *   When a tool is triggered, the chat displays a 🛠️ icon with the tool name.
        Expanding the entry reveals the call and its result. The result becomes
        the next user message for the requesting agent so it can refine its
        answer and share the output when appropriate.
    *   Each agent has an individual setting to toggle tool usage on or off.
*   Each agent can enable or disable individual tools.
*   **Thinking Mode:** When enabled, an agent iteratively generates a series of
    thoughts before producing its final answer. The number of thinking steps is
    configurable per agent.
*   Tools can also be discovered automatically from the `tool_plugins` directory
        or from packages exposing the `cerebro_tools` entry point.
    *   The distribution includes a `web-scraper` plugin for retrieving text
        from websites.
    *   Includes a built-in **File Summarizer** tool for generating quick summaries of text files.
    *   Provides a **Desktop Automation** plugin for launching programs or moving files via OS commands.
    *   Includes a **Credential Manager** plugin for securely storing API keys using the system keyring.
    *   Includes an **Automated Update Manager** plugin for checking for new versions and downloading updates on Windows 11.
    *   Bundles a **Task Sequence Recorder** plugin to capture mouse and keyboard actions and replay them later.
    *   Tools can be updated using the **Edit Tool** button in the Tools tab.
    *   The Tool script editor features Python syntax highlighting when QScintilla is installed.
    *   The Settings dialog provides buttons to update the Ollama runtime and refresh individual models. Model names are cached so the dialog opens quickly.

*   **Automations Tab:** Record desktop actions and replay them later. Playback
    jumps directly to click and drag positions for quicker execution.

*   **Task Scheduling:**
    *   Agents can schedule tasks to be executed at a specific time. New tasks default to one minute from the current time.
    *   Tasks are stored in `tasks.json`.
    *   Tasks appear on a drag-and-drop calendar for easy rescheduling and completion.
    *   Filter tasks by agent or status using drop-down menus above the list.
    *   Each row contains Edit, Delete and Complete buttons for quick changes.
    *   A progress bar shows how close each task is to its due time.
    *   Tasks can optionally repeat at a set interval.
    *   Due times must be in ISO 8601 format or `YYYY-MM-DD HH:MM:SS` local time.
        Today's date is highlighted and any date with tasks shows a small red dot.
    *   Tasks can register with the operating system's scheduler so they run even when Cerebro is closed. Windows 11 uses **Task Scheduler** and Unix-like systems rely on `cron`.
    *   The included **Windows Notifier** tool can display Windows 11 notifications when a scheduled task runs.
*   **Workflow Builder:**
    *   Create reusable workflows that coordinate multiple agents.
    *   Supports **Agent Managed** and **User Managed** modes.
    *   In **User Managed** mode, set the number of steps then select an agent
        and prompt for each step.
    *   Workflows are edited on a dedicated tab with drag-and-drop ordering.
*   **Chat History Management:**
    *   Each session begins with a blank conversation.
    *   History can be saved, exported or cleared from the chat menu if desired.
    *   Click the 🔍 icon to search within the current conversation.
*   **Conversation Summaries:**
    *   Older messages are automatically condensed when a chat grows large to
        keep prompts short.
*   **Desktop History:**
    *   Agents with `desktop_history_enabled` enabled receive recent screenshots of your desktop.
        Screens are captured at the configured interval and sent to the model as base64 images.
    *   The screenshot interval can be set globally in the **Settings** dialog.
*   **Customizable UI:**
    *   Light and dark mode support.
    *   Configurable user name, chat color and accent color.
*   **System Tray Icon:**
    *   Access quick actions from the tray to open the window, add a task or toggle dark mode.
*   **Debug Mode:**
    *   Enables verbose logging for debugging purposes.
*   **Metrics Dashboard:**
    *   View tool usage frequency, completed tasks, and agent response times.
*   **Documentation Tab:**
    *   Browse the built-in user guide. Documentation is split across multiple pages for easier navigation.

## In-App Documentation
Open the "Docs" tab or press `Ctrl+7` to view the full user guide.

## Requirements

*   Python 3.7 or higher
*   PyQt5
*   Requests
*   win10toast (only needed on Windows for notification support)
*   SymPy
*   pyautogui
*   pynput
*   A running Ollama instance with the desired language models installed (see [Ollama](https://ollama.ai/))

## Installation

1.  **Clone the repository:**

    ```bash
    git clone [https://github.com/dantemarone/cerebro.git](https://github.com/dantemarone/cerebro.git)
    cd cerebro
    ```

2.  **Create a virtual environment (recommended):**

    ```bash
    python3 -m venv venv
    ```

3.  **Activate the virtual environment:**
    *   **Linux/macOS:**
        ```bash
        source venv/bin/activate
        ```
    *   **Windows:**
        ```bash
        venv\Scripts\activate
        ```

4.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```
    QScintilla is optional but enables syntax highlighting in the tool editor.

5.  *(Optional)* **Install the Ollama runtime and a model:**

    ```bash
    python local_llm_helper.py install
    python local_llm_helper.py download llama3
    ```

## Usage

1.  **Start the Ollama server:**
    Make sure your Ollama server is running in the background. You can launch it manually with `ollama serve` or run:

    ```bash
    python local_llm_helper.py serve
    ```

2.  **Run the Cerebro application:**

    ```bash
    python main.py
    ```

    *   To enable debug mode, set the `DEBUG_MODE` environment variable to 1:
        *   **Linux/macOS:** `DEBUG_MODE=1 python main.py`
        *   **Windows:** `set DEBUG_MODE=1 & python main.py`

## Windows Installer

Use PyInstaller to create a stand-alone Windows build. First install PyInstaller and then run `build_windows_installer.bat` from a command prompt. The executable will be created in the `dist` directory.


## Configuration

### `agents.json`

This file stores the configuration for each agent.

*   **`model`:** The name of the Ollama model to use (e.g., "llama3.2-vision", "llava").
*   **`temperature`:** Controls the randomness of the AI's response (0.0 - 1.0).
*   **`max_tokens`:** Limits the length of the AI's response.
*   **`system_prompt`:** Sets the initial instructions for the agent.
*   **`enabled`:** Enables or disables the agent.
*   **`color`:** Sets the agent's display color in the chat.
*   **`role`:** Defines the agent's role: "Coordinator", "Assistant", or "Specialist".
*   **`description`:** A brief description of the agent's capabilities (used by Coordinators).
*   **`managed_agents`:** (Coordinator only) A list of agents managed by this Coordinator.
*   **`desktop_history_enabled`:** Enables access to desktop screenshots.
*   **`screenshot_interval`:**  Interval in seconds between captured screenshots.
*   **`tool_use`:** Boolean value to enable or disable an agent's access to tools.
*   **`tools_enabled`:** A list of tools that an agent can access, assuming `tool_use` is set to true.
*   The bundled `Default Agent` comes enabled with all built-in tools for general use.
*   On first launch, the app selects the first model returned by `ollama list` for this agent.

**Example:**

```json
{
    "Coordinator Agent": {
        "model": "llama3.2-vision",
        "temperature": 0.7,
        "max_tokens": 512,
        "system_prompt": "You are a coordinator agent. Your role is to select the most appropriate agent...",
        "enabled": true,
        "color": "#0000FF",
        "role": "Coordinator",
        "description": "This agent coordinates the activities of other agents.",
        "managed_agents": ["Spiderman", "Coding Assistant"],
        "tool_use": false,
        "tools_enabled": []
    },
    "Coding Assistant": {
        "model": "llava",
        "temperature": 0.5,
        "max_tokens": 1024,
        "system_prompt": "You are a coding assistant. You can help with tasks like writing code...",
        "enabled": true,
        "color": "#008000",
        "role": "Specialist",
        "description": "An agent specialized in coding tasks.",
        "tool_use": true,
        "tools_enabled": ["schedule-task"]
    }
}

settings.json
This file stores global application settings.

debug_enabled: Enables debug mode (boolean).
include_image: Currently unused.
include_screenshot: Deprecated.
image_path: Currently unused.
user_name: The user's display name.
user_color: The user's chat message color.
accent_color: The primary UI accent color used in the application theme.
dark_mode: Enables dark mode (boolean).
tools.json
This file defines available tools.

name: The name of the tool.
description: A brief description of the tool.
args: (optional) List of argument names the tool accepts.
script: The content of the Python script that implements the tool. The script must define a function called run_tool(args) that takes a dictionary of arguments and returns a string.
script_path: (optional) Path to a Python file containing the tool implementation. If script_path is missing but script is provided, the application will run the script from a temporary file.
Tools placed in the `tool_plugins` directory or installed via the `cerebro_tools` entry point
are loaded automatically on startup. Built-in plugins include `math-solver` for complex calculations and `credential-manager` for secure credential storage.
Example:

'''JSON
[
  {
    "name": "schedule-task",
    "description": "Schedule a future prompt to run at the specified time.",
    "args": ["agent_name", "prompt", "due_time"],
    "script": "def run_tool(args):\\n  import os\\n  import sys\\n  from tasks import load_tasks, save_tasks, add_task\\n  # The agent will pass arguments like:\\n  # {\\n  # \\"agent_name\\": \\"Agent X\\",\\n  # \\"prompt\\": \\"some scheduled prompt\\",\\n  # \\"due_time\\": \\"2024-12-31T23:59:59\\"\\n  # }\\n  agent_name = args.get(\\"agent_name\\", \\"Default Agent\\")\\n  prompt = args.get(\\"prompt\\", \\"No prompt provided\\")\\n  due_time = args.get(\\"due_time\\", \\"\\")\\n  tasks = load_tasks(False) #\\n  # load current tasks\\n  if not due_time:\\n   return \\"[schedule-task Error] No due_time provided.\\"\\n  # Add the task, marking creator as 'agent' or 'user' as you prefer.\\n  add_task(tasks, agent_name, prompt, due_time, creator=\\"agent\\", debug_enabled=False)\\n  return f\\"Task scheduled: Agent '{agent_name}' at '{due_time}' with prompt '{prompt}'.\\""
  }
]

Another bundled plugin named `web-scraper` fetches and sanitizes text from a URL.
The repository also provides a `windows-notifier` plugin that relies on the
`win10toast` package to display a Windows 11 notification. Pair it with the
`schedule-task` tool to create reminders or daily summaries.
The new `notification-hub` plugin offers cross-platform desktop alerts with optional sound effects and push webhooks for forwarding messages to mobile devices.
The new `ar-overlay` plugin pops up a small HUD-style window with a short
message, and the `desktop-automation` plugin can launch programs or move files
after a model analyzes your screen captures. Replies can now be spoken aloud
when Text-to-Speech is enabled for an agent.
Scheduled tasks are also written to the OS task scheduler using the helper
script `run_task.py` so they execute even when Cerebro is not running.

tasks.json
This file stores the list of scheduled tasks. Each task entry includes an ``id``, ``creator``,
``agent_name``, ``prompt``, ``due_time``, ``created_time`` and ``status`` field. The status field defaults to ``pending``.
You typically won't edit this file directly.

## Testing
Install the dependencies and run the linter and test suite before submitting
changes:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
flake8 .
PYTHONPATH=. pytest -q
```

## Contributing
Contributions are welcome! Please feel free to submit pull requests or open issues.

## License
This project is licensed under the MIT License.
