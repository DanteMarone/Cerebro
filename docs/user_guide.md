# Cerebro User Guide

This guide provides a detailed overview of Cerebro's features. Each section corresponds to one of the application's tabs.

## Chat Tab
The Chat tab is the primary interface for interacting with your agents. Use the text box at the bottom to send a prompt. Messages appear in a scrollable window above the input field. The chat history can be copied, exported or cleared using the menu in the top right corner. Each time the application starts you begin with a fresh conversation. While an agent is generating a response a "typing" indicator is displayed.

## Agents Tab
The Agents tab lets you create and configure AI agents. Every agent stores the following settings:

- **Model** – select the language model from a dropdown of installed Ollama models (for example `llava` or `llama3.2-vision`).
- **Temperature** – controls randomness of the output.
- **Max Tokens** – maximum length of a single response.
- **Custom System Prompt** – additional instructions sent before every conversation.
- **Enabled** – toggle to activate or disable the agent.
- **Role** – choose between *Assistant*, *Coordinator* or *Specialist*.
- **Description** – short description used by Coordinators when delegating tasks.
- **Agent Color** – color used for chat messages.
- **Managed Agents** – for Coordinators, select which agents they can delegate to.
- **Tool Use** – allow the agent to call tools.
- **Enabled Tools** – choose which tools are available when tool use is on.

After adjusting any fields press **Save** to store your changes. You can also
rename an agent using the **Agent Name** field. The Agents tab opens to a table
listing all agents with an **Edit** button next to each one. Use **Add New
Agent** to create a new entry. When editing an agent you can return to the list
with **Back** or remove it with **Delete Agent**.

## Tools Tab
Manage the tools that agents can invoke. Add new tools or edit existing ones. 
- The built-in **File Summarizer** tool can create short summaries of text files for quick reference.
- Built-in plugins include `math-solver` for solving equations.
- The app ships with a `web-scraper` plugin that fetches text from a URL.
- The **Windows Notifier** tool can be used to display Windows 11 notifications when triggered by a scheduled task.

Tools extend Cerebro with custom Python scripts. The Tools tab shows all tools loaded from `tools.json` and any plugin modules. You can:

1. **Add Tool** – open a dialog to provide a name, description and Python script. The script must define a `run_tool(args)` function.
2. **Edit Tool** – modify the selected tool's metadata or script.
3. **Delete** – permanently remove a tool and its script file.
4. **Run** – test a tool by providing JSON arguments.

Plugin tools are loaded automatically from the `tool_plugins` directory or entry points.
They behave like regular tools and can be edited or removed from the UI.

Agents with tool use enabled can invoke these tools by returning a JSON block in the format described in `generate_tool_instructions_message()`.


## Tasks Tab
The Tasks tab manages scheduled prompts. Tasks are displayed in a list and on a calendar. The current day is highlighted and dates with tasks show a red dot in the corner. You can drag tasks to different dates to reschedule them. Double-clicking a task toggles its status between **pending** and **completed**. Buttons allow you to:

- **Add Task** – create a new task specifying agent, prompt and due time. The due time defaults to one minute from now.
- **Edit** – change an existing task.
- **Delete** – remove a task after confirmation.
- **Toggle Status** – mark the selected task as completed or pending.

Tasks may also be set to repeat automatically after a specified number of minutes.

When a task reaches its due time the associated prompt is automatically sent to the chosen agent.

## Metrics Tab
Metrics track tool usage, completed tasks and average response times. This tab reads data from `metrics.json` and displays three sections:

- **Tool Usage** – how many times each tool has been run.
- **Task Completions** – number of tasks finished by each agent.
- **Average Response Times** – the mean response time of each agent in seconds.

These metrics are updated whenever agents use tools or complete tasks.

## Documentation Tab
The Documentation tab simply renders this `user_guide.md` file. It allows in-app viewing of the full user guide without leaving Cerebro.

## Settings Dialog
The Settings dialog contains global preferences for the application.

- Toggle dark mode and set your user name.
- Use **Update Ollama** to download the latest Ollama release.
- If the update fails, an error message will be displayed.
- Select a model in the drop-down and click **Update Model** to pull its newest version.

