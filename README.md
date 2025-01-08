# Cerebro Chat Application

A Python desktop application built with **PyQt5** that provides a multi-agent chat interface, task scheduling, and tool management. The UI has been restructured into tabs for improved clarity and organization:

- **Chat** — Displays and interacts with the conversation.  
- **Agents** — Manages agent configurations such as model details, temperature, prompts, and colors.  
- **Tools** — Allows adding/editing/deleting custom tools.  
- **Tasks** — Schedules prompts to run at specific times for particular agents.

## Features

1. **Tabbed Interface**  
   - **Chat Tab**: Shows conversation with user input, “Send” and “Clear Chat” buttons.  
   - **Agents Tab**: List of agents with per-agent settings (model, temperature, prompts, etc.).  
   - **Tools Tab**: Manage tools (scripts) that can be invoked by agents.  
   - **Tasks Tab**: Schedule tasks with due times for specific agents.

2. **Multiple Agents**  
   - Configure multiple agents with different model settings.  
   - Enable or disable agents, or run them in “desktop historian” mode.  

3. **Tool Integration**  
   - Agents can call external “tools” if they cannot directly answer a user’s query.  
   - Tools are Python scripts that define a `run_tool(args)` function.  

4. **Task Scheduling**  
   - Schedule “prompts” to be automatically posted to specific agents at a given time.  
   - Tasks are stored in `tasks.json`.

5. **Dark Mode**  
   - Toggle Dark Mode for improved readability in low-light environments.

6. **Debug Mode**  
   - Set `DEBUG_MODE=1` to see additional debug outputs in the console.

## Installation

1. **Clone the Repository**:

   ```bash
   git clone https://github.com/username/cerebro-chat-app.git
   cd cerebro-chat-app

2. Create and Activate a Virtual Environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate

3. Install Requirements:
   '''bash
   pip install -r requirements.txt

4. Run the Application:
   '''bash
   python main.py

Usage
Launching:

Run python main.py. The main window will appear with four tabs: Chat, Agents, Tools, and Tasks.
Chatting:

Go to the Chat tab, type your message, and click Send or press Enter.
Enable at least one agent in the Agents tab to receive responses.
Agents:

Add or remove agents, enable/disable them, or tweak their Model Name, Temperature, Max Tokens, etc.
Set an optional System Prompt for specialized behavior.
Tools:

Add custom tools with Python scripts. Agents can call these tools if they encounter queries best handled by external functions.
Tasks:

Create tasks that will automatically send prompts to specified agents at scheduled times.
Dark Mode:

Enable or disable Dark Mode under Global Preferences in the Agents tab.
File Overview
main.py: Entry point; starts the AIChatApp.
app.py: Main application file, orchestrating window setup, tabs, and logic.
worker.py: AIWorker class that handles AI requests in a separate thread.
tab_chat.py: Contains the ChatTab class for the Chat interface.
tab_agents.py: Contains the AgentsTab class for managing agent configurations.
tab_tools.py: Contains the ToolsTab class for managing external tools.
tab_tasks.py: Contains the TasksTab class for scheduling tasks.
dialogs.py: Contains ToolDialog and TaskDialog for creating/editing tools and tasks.
tools.py: Functions to load, save, add, edit, and delete custom tools.
tasks.py: Functions to load, save, add, edit, and delete scheduled tasks.
Customization
API URL: By default, the application sends requests to http://localhost:11434/api/chat (Ollama API). You can change this in worker.py.
Debug Mode:
Set export DEBUG_MODE=1 before running to see debug messages.
Data Files:
agents.json: Stores agent configurations.
tools.json: Stores tool definitions.
tasks.json: Stores scheduled tasks.
settings.json: Stores global user settings (username, color, dark mode, etc.).
Contributing
Contributions are welcome! Feel free to open issues or submit pull requests for improvements or new features.

License
This software is available under the MIT License.