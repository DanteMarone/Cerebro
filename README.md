# Cerebro: A Multi-Agent AI Chat Application

Cerebro is a desktop chat application built with PyQt5 that allows you to interact with multiple AI agents powered by the Ollama API. It provides a flexible and extensible framework for creating and managing AI agents with different roles, capabilities, and personalities.

## Key Features

*   **Multiple AI Agents:** Create and manage multiple AI agents, each with its own:
    *   Underlying language model (e.g., `llama3.2-vision`, `llava`).
    *   Custom system prompt to define its behavior and personality.
    *   Temperature and max tokens settings to control response randomness and length.
    *   Assigned role:
        *   **Coordinator:** Manages other agents and delegates tasks.
        *   **Assistant:** Responds directly to user queries.
        *   **Specialist:** Responds only to requests from a Coordinator.
    *   Configurable color in the chat UI.
*   **Agent Roles:**
    *   **Coordinator:**  The Coordinator agent acts as a central hub. It receives user input, intelligently selects the most appropriate Specialist or Assistant agent to handle the request (based on agent descriptions and the nature of the query), and then displays the chosen agent's response. The Coordinator can also add context or modify the user's prompt before passing it on. When a Coordinator is done, it will pass the conversation on to another agent by specifying the phrase "Next Response By: [Agent Name]".
    *   **Assistant:** Assistant agents behave like traditional chatbots, responding directly to user input in the chat window.
    *   **Specialist:** Specialist agents are designed to handle specific types of tasks or answer questions within a particular domain. They do not engage directly with the user in the chat. Instead, they receive instructions or queries from a Coordinator agent and send their responses back to the Coordinator.
*   **Tool Integration:**
    *   Agents can be granted the ability to use tools.
    *   Tools are implemented as Python scripts that define a `run_tool(args)` function.
    *   Agents can invoke tools by including a specific JSON format in their response.
    *   Each agent has an individual setting to toggle tool usage on or off.
    *   Each agent can enable or disable individual tools.
*   **Task Scheduling:**
    *   Agents can schedule tasks to be executed at a specific time.
    *   Tasks are stored in `tasks.json`.
*   **Desktop History:**
    *   Agents can be granted access to screenshots of the user's desktop.
    *   Currently, this feature is not implemented, but the groundwork has been laid.
*   **Customizable UI:**
    *   Light and dark mode support.
    *   Configurable user name and color.
*   **Debug Mode:**
    *   Enables verbose logging for debugging purposes.

## Requirements

*   Python 3.7 or higher
*   PyQt5
*   Requests
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

## Usage

1.  **Start the Ollama server:**
    Make sure your Ollama server is running in the background. Refer to the Ollama documentation for instructions. You can use the command `ollama serve` to start it.

2.  **Run the Cerebro application:**

    ```bash
    python main.py
    ```

    *   To enable debug mode, set the `DEBUG_MODE` environment variable to 1:
        *   **Linux/macOS:** `DEBUG_MODE=1 python main.py`
        *   **Windows:** `set DEBUG_MODE=1 & python main.py`

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
*   **`desktop_history_enabled`:** Enables access to desktop screenshots (currently not implemented).
*   **`screenshot_interval`:**  Sets the screenshot interval (currently not implemented).
*   **`tool_use`:** Boolean value to enable or disable an agent's access to tools.
*   **`tools_enabled`:** A list of tools that an agent can access, assuming `tool_use` is set to true.

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
include_screenshot: Currently unused.
image_path: Currently unused.
user_name: The user's display name.
user_color: The user's chat message color.
dark_mode: Enables dark mode (boolean).
tools.json
This file defines available tools.

name: The name of the tool.
description: A brief description of the tool.
script: The content of the Python script that implements the tool. The script must define a function called run_tool(args) that takes a dictionary of arguments and returns a string.
Example:

'''JSON
[
  {
    "name": "schedule-task",
    "description": "Schedule a future prompt to run at the specified time.",
    "script": "def run_tool(args):\\n  import os\\n  import sys\\n  from tasks import load_tasks, save_tasks, add_task\\n  # The agent will pass arguments like:\\n  # {\\n  # \\"agent_name\\": \\"Agent X\\",\\n  # \\"prompt\\": \\"some scheduled prompt\\",\\n  # \\"due_time\\": \\"2024-12-31T23:59:59\\"\\n  # }\\n  agent_name = args.get(\\"agent_name\\", \\"Default Agent\\")\\n  prompt = args.get(\\"prompt\\", \\"No prompt provided\\")\\n  due_time = args.get(\\"due_time\\", \\"\\")\\n  tasks = load_tasks(False) #\\n  # load current tasks\\n  if not due_time:\\n   return \\"[schedule-task Error] No due_time provided.\\"\\n  # Add the task, marking creator as 'agent' or 'user' as you prefer.\\n  add_task(tasks, agent_name, prompt, due_time, creator=\\"agent\\", debug_enabled=False)\\n  return f\\"Task scheduled: Agent '{agent_name}' at '{due_time}' with prompt '{prompt}'.\\""
  }
]
tasks.json
This file stores the list of scheduled tasks. You typically won't edit this file directly.

Contributing
Contributions are welcome! Please feel free to submit pull requests or open issues.

License
This project is licensed under the MIT License