# Application Tabs

Use `Ctrl+1` through `Ctrl+7` to switch between tabs.

## Chat Tab

- The Chat tab is the main interface for sending prompts to your agents.
- Enter a prompt and press **Send** or use the 🎤 button to dictate a prompt.
- Messages show in speech bubbles with avatars or initials next to the sender name. Each message includes a timestamp and conversations are grouped by date so you can quickly see when a discussion happened.
- Use the menu to copy, save, export or clear the conversation.
- Click the 🔍 button to search the current conversation.
- From the same menu choose **Search saved history** to look across chats.
- Long conversations are automatically summarized to keep prompts short.
  You can adjust or disable this threshold in the **Settings** dialog.
- Agents with *desktop history* enabled attach periodic screenshots for visual context.

## Agents Tab

Create, edit and delete agents.
Agents are automated workers that perform tasks for you.
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
- **Text-to-Speech Enabled** – speak replies aloud.
- **Voice** – choose which system voice to use when speaking.
    - *Prerequisites: TTS functionality relies on the text-to-speech engines available on your operating system. Ensure you have voices installed and configured at the OS level if you encounter issues.*
- **Desktop History Enabled** – capture screenshots for the model.
- **Screenshot Interval** – seconds between captures.

### Agent Roles in Detail

- **Coordinator/Specialist Interaction Example:**
    - A Coordinator agent, upon receiving a complex query, might identify that a 'MathSpecialist' agent is best suited.
    - The Coordinator's response (which is logged in the chat) could include: `I need help with a calculation. Next Response By: MathSpecialist`
    - The 'MathSpecialist' then receives the original user query (plus any context from the coordinator) and its response is directed back through the coordinator or directly to the chat, depending on the system's flow. The key is the explicit delegation.

Press **Save** after editing or **Cancel** to discard changes. Use **Add New Agent** to create one.
Deleting an agent will prompt for confirmation. If the agent is assigned to any tasks, the warning will show how many tasks may be affected.

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
- **New Task** – create a prompt for a specific agent. Defaults to one minute from now.
- **Edit** – change an existing task.
- **Delete** – remove a task after confirmation.
- **Duplicate** – create a copy of an existing task.
- **Toggle Status** – mark a task as completed or pending.
- **Filters** – filter by agent or status.
- **Row Actions** – each row includes Edit, Duplicate, Delete and Complete buttons.
- **Drag and Drop** – reorder tasks by dragging them up or down.
- **Undo Toast** – after deleting a task a popup allows you to undo.
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

## Finetune Tab

Prepare datasets and parameters to train a custom model.
- **Base Model** – select an installed Ollama model or type a Hugging Face repo id or local path. The repo id is the portion of the model URL after `https://huggingface.co/`.
- **Model Name** – optional name for the trained model.
- **Training Dataset** – path to your training file.
- **Validation Dataset** – optional file for validation.
- **Learning Rate** – optimizer step size.
- **Epochs** – number of passes over the dataset.
- **Batch Size** – how many samples per batch.
Start training with the **Start Training** button. Logs stream to a dialog while
the process runs in the background.

## Documentation Tab

Browse these documents without leaving the application.
