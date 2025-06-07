# Application Tabs

Use `Ctrl+1` through `Ctrl+7` to switch between tabs.

## Chat Tab

The Chat tab is the main interface for sending prompts to your agents.
- Enter a prompt and press **Send**.
- Messages appear in a scrollable pane. A typing indicator shows when an agent is responding.
- Use the menu to copy, save, export or clear the conversation.
- Click the 🔍 button to search the current conversation.
- Long conversations are automatically summarized to keep prompts short.
- Agents with *desktop history* enabled attach periodic screenshots for visual context.

## Agents Tab

Create, edit and delete agents.
- **Model** – select an installed Ollama model such as `llava` or `llama3.2-vision`.
- **Temperature** – controls randomness of responses.
- **Max Tokens** – maximum reply length (up to 100000 tokens).
- **Custom System Prompt** – instructions sent before each conversation.
- **Enabled** – toggle the agent on or off.
- **Role** – Assistant, Coordinator or Specialist.
- **Description** – short summary used by Coordinators.
- **Agent Color** – color used for chat messages.
- **Managed Agents** – Coordinators can delegate to selected agents.
- **Tool Use** – allow the agent to call tools.
- **Enabled Tools** – choose which tools are available.
- **Enable Thinking** – generate intermediate thoughts before answering.
- **Thinking Steps** – number of thinking iterations.
- **Text-to-Speech Enabled** – speak replies aloud using the system voice.
- **Desktop History Enabled** – capture screenshots for the model.
- **Screenshot Interval** – seconds between captures.

Press **Save** after editing or **Add New Agent** to create one.

## Tools Tab

Manage scripts that agents can invoke.
1. **Add Tool** – supply a name, description and script with `run_tool(args)`.
2. **Edit Tool** – modify an existing tool.
3. **Delete** – remove a tool.
4. **Run** – execute a tool manually with JSON arguments.
   The editor supports syntax highlighting when QScintilla is installed.

Bundled plugins include:
- **file-summarizer** – summarize text files.
- **web-scraper** – download and sanitize text from a URL.
- **math-solver** – evaluate mathematical expressions.
- **windows-notifier** – show Windows 11 notifications.
- **notification-hub** – cross-platform alerts with optional sound.
- **ar-overlay** – display a small on-screen message.
- **desktop-automation** – launch programs or move files.
- **credential-manager** – securely store credentials.
- **update-manager** – download new Cerebro versions on Windows 11.
- **run-automation** – execute a recorded button sequence.

Tools are triggered when an agent returns a JSON block in the format produced by `generate_tool_instructions_message()`.

## Plugins Tab

Install and manage plugin-based tools.
1. **Install Plugin** – choose a Python file to copy into the plugins directory.
2. **Reload** – refresh the list of installed plugins.
3. **Enable/Disable** – check or uncheck a plugin to toggle availability.

## Automations Tab

Record and play back desktop actions.
- **Record** – capture mouse and keyboard events for a duration.
- **Run** – replay the selected sequence using `pyautogui`. Mouse moves are
  skipped so the cursor jumps to each click or drag location. Each step waits
  0.5 seconds by default but the delay can be customized when you run it.
- **Delete** – remove a saved automation.

## Tasks Tab

Schedule prompts to run later. Dates with tasks show a red dot in the calendar.
- **Add Task** – create a prompt for a specific agent. Defaults to one minute from now.
- **Edit** – change an existing task.
- **Delete** – remove a task after confirmation.
- **Toggle Status** – mark a task as completed or pending.
- **Filters** – filter by agent or status.
- **Row Actions** – each row includes Edit, Delete and Complete buttons.
- **Progress Bar** – indicates how close the task is to its due time.
- **Repeat Interval** – optional minutes after which the task repeats.
- **Time Format** – ISO 8601 or `YYYY-MM-DD HH:MM:SS` local time.

When a task becomes due the prompt is sent automatically. Tasks can also be registered with the operating system scheduler so they run even if Cerebro is not open.

## Workflows Tab

Design multi-agent workflows that can be executed repeatedly.
- **Agent Managed** – a coordinator assigns subtasks to other agents. Select
  multiple agents using the check box list.
- **User Managed** – specify the number of steps and for each step choose an agent
  and an additional prompt to send alongside the chat history.
Run a workflow manually using the **Run** button and provide a starting prompt.
The runner shows each coordinator decision and agent reply until completion.
Workflows may also be started from chat with `/run workflow <name> [prompt]`.

## Metrics Tab

View statistics from `metrics.json`.
- **Tool Usage** – how many times each tool has run.
- **Task Completions** – number of tasks finished by each agent.
- **Average Response Times** – mean response time per agent.

## Documentation Tab

Browse these documents without leaving the application.
