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

## Fine-tuning a Model

The **Finetune Tab** (covered in [Application Tabs](app_tabs.md#finetune-tab)) allows you to specialize a base model with your own examples.

Ensure Ollama is installed and that you have pulled the model you want to adapt. Collect your training data in a JSONL file (e.g., `train.jsonl`).

Within the Finetune Tab, you can:
- Select a base model (from installed Ollama models or a Hugging Face repository ID).
- Specify your training and optional validation dataset files.
- Configure parameters like learning rate, epochs, and batch size.
- Start the training process and monitor its progress.

Alternatively, for manual fine-tuning outside Cerebro using Ollama directly, you would typically create a `Modelfile` like this:

```Modelfile
FROM llama3
ADAPTER ./train.jsonl
```


Then run `ollama create my-model -f Modelfile` and `ollama run my-model` to test the result. Once created, you can select `my-model` in your agent settings within Cerebro.

## Troubleshooting and Logs

Cerebro records debug output to `cerebro.log` in the application directory. Error messages shown in the chat include a **View Logs** link that opens this file. Checking the log is useful when diagnosing connection issues or other problems.

## Staying Updated

The application notifies you when an update is available. You can also check for updates manually from the **Help menu** -> **Check for Updates**.

---

We hope this guide helps you make the most of Cerebro! If you have further questions or encounter issues, please refer to the project's main [README.md](https://github.com/dantemarone/cerebro/blob/main/README.md) or consider opening an issue on GitHub.
