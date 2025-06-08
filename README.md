# Cerebro: A Multi-Agent AI Chat Application

Cerebro is a desktop chat application built with PyQt5 that allows you to interact with multiple AI agents powered by the Ollama API. It provides a flexible and extensible framework for creating and managing AI agents with different roles, capabilities, and personalities.

**Full documentation is available within the application under the 'Docs' tab or online in the [User Guide](docs/user_guide.md).**

## Key Features

Cerebro offers a rich set of features to enhance your interaction with AI models:

*   **Multiple AI Agents:** Create and manage multiple AI agents, each with its own model, system prompt, role (Coordinator, Assistant, Specialist), and appearance. (Details: [Application Tabs - Agents](docs/app_tabs.md#agents-tab), [Configuration - agents.json](docs/configuration.md#agentsjson))
* **Tool Integration:** Grant agents the ability to use tools (Python scripts) to perform actions and retrieve information. Tools can be bundled, custom-developed, or installed as plugins. Tools that need extra setup are marked **Needs Configuration** and provide a Setup button. (Details: [Plugins and Tools](docs/plugins.md), [Application Tabs - Tools](docs/app_tabs.md#tools-tab), [Tools Issue #4 Response](docs/tools_issue_4_response.md))
* **Tool Status Indicators:** The Tools tab now shows a status column with color-coded icons so you can easily see if a tool is enabled or disabled.
*   **Thinking Mode:** Enable agents to iteratively generate a series of thoughts before producing a final answer. (Details: [Application Tabs - Agents](docs/app_tabs.md#agents-tab))
*   **Automations:** Record and replay desktop actions (mouse and keyboard sequences). Step-based automations can be composed by double-clicking available steps and rearranged via drag and drop. (Details: [Application Tabs - Automations](docs/app_tabs.md#automations-tab))
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

## Requirements

*   Python 3.7 or higher
*   PyQt5
*   Requests
*   win10toast (Windows only, for notification support via the bundled `windows-notifier` plugin)
*   SymPy (for the bundled `math-solver` plugin)
*   pyautogui, pynput (for Automations and `desktop-automation` plugin)
*   SpeechRecognition (for voice input)
*   A running Ollama instance with desired language models installed (see [Ollama](https://ollama.ai/))

For a full list of dependencies for development and testing, see `requirements.txt` and `requirements-dev.txt`.

## Installation

For detailed installation and setup instructions, please see the **[Getting Started Guide](docs/getting_started.md)**.

1.  **Clone the repository.**
2.  **Create a virtual environment (recommended).**
3.  **Activate the virtual environment.**
4.  **Install dependencies:** `pip install -r requirements.txt`
    *   QScintilla is optional but enables syntax highlighting in the tool editor.
5.  **(Optional)** Install Ollama and models using the helper: `python local_llm_helper.py install`

## Usage

1.  **Start the Ollama server.** (e.g., `ollama serve` or `python local_llm_helper.py serve`)
2.  **Run the Cerebro application:** `python main.py`
    *   Debug mode is enabled by default. To disable, set `DEBUG_MODE=0` (see [Configuration - Debug Mode](docs/configuration.md#understanding-debug-mode)).
    *   Errors are saved to `cerebro.log` in the application directory.

## Configuration

Cerebro uses several JSON files to store configurations for agents, tools, tasks, settings, etc. For a detailed explanation of these files and their structures, please refer to the **[Configuration Guide](docs/configuration.md)**.

## Fine-tuning a Model

Cerebro allows you to fine-tune existing Ollama models with your own datasets using the **Finetune Tab**. For detailed instructions on preparing data and using this feature, please see the **[Fine-tuning a Model section in the User Guide](docs/user_guide.md#fine-tuning-a-model)**.

## Windows Installer

To create a stand-alone Windows installer, install PyInstaller and then run `build_windows_installer.bat` from a command prompt. The executable will be created in the `dist` directory. (More details: [Getting Started Guide](docs/getting_started.md))

## Testing

Install development dependencies and run the linter and test suite:
```bash
pip install -r requirements-dev.txt
flake8 .
PYTHONPATH=. pytest -q
```

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

## License

This project is licensed under the MIT License.
