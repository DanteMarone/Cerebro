#app.py
import os
import json
from datetime import datetime
from PyQt5 import QtCore
from PyQt5.QtCore import QThread, Qt
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QApplication, QAction, QMenu, QDialog
)

from worker import AIWorker
from tools import load_tools, run_tool
from tasks import load_tasks, save_tasks, add_task, delete_task
from tab_chat import ChatTab
from tab_agents import AgentsTab
from tab_tools import ToolsTab
from tab_tasks import TasksTab

AGENTS_SAVE_FILE = "agents.json"
SETTINGS_FILE = "settings.json"
TOOLS_FILE = "tools.json"
TASKS_FILE = "tasks.json"

class AIChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Check for debug mode
        if os.environ.get("DEBUG_MODE", "") == "1":
            self.debug_enabled = True
        else:
            self.debug_enabled = False

        # Basic window settings
        self.setWindowTitle("Cerebro 1.0")
        self.setGeometry(100, 100, 800, 600)

        # Variables
        self.chat_history = []
        self.current_responses = {}
        self.agents_data = {}
        self.include_image = False
        self.include_screenshot = False
        self.current_agent_color = "#000000"
        self.user_name = "You"
        self.user_color = "#0000FF"
        self.dark_mode = False
        self.active_worker_threads = []

        # Load Tools and Tasks
        self.tools = load_tools(self.debug_enabled)
        self.tasks = load_tasks(self.debug_enabled)

        # Prepare UI with tabs
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # Create tabs
        self.chat_tab = ChatTab(self)
        self.agents_tab = AgentsTab(self)
        self.tools_tab = ToolsTab(self)
        self.tasks_tab = TasksTab(self)

        self.tab_widget.addTab(self.chat_tab, "Chat")
        self.tab_widget.addTab(self.agents_tab, "Agents")
        self.tab_widget.addTab(self.tools_tab, "Tools")
        self.tab_widget.addTab(self.tasks_tab, "Tasks")

        # Load settings and agents
        self.load_settings()
        self.populate_agents()
        self.update_send_button_state()
        
        # Create a menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')

        # Add a settings action to the file menu
        settings_action = QAction('Settings', self)
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)

        # Add a quit action to the file menu
        quit_action = QAction('Quit', self)
        quit_action.setShortcut('Ctrl+Q')
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Apply dark mode if relevant
        if self.dark_mode:
            self.apply_dark_mode_style()

        # Check tasks regularly
        self.task_timer = QtCore.QTimer(self)
        self.task_timer.timeout.connect(self.check_for_due_tasks)
        self.task_timer.start(30_000)

    # -------------------------------------------------------------------------
    # Settings Dialog
    # -------------------------------------------------------------------------
    def open_settings_dialog(self):
        # Create a QDialog for settings
        from dialogs import SettingsDialog
        settings_dialog = SettingsDialog(self)
        if settings_dialog.exec_() == QDialog.Accepted:
            # Update settings based on user input
            settings_data = settings_dialog.get_data()
            self.dark_mode = settings_data["dark_mode"]
            self.user_name = settings_data["user_name"]
            self.user_color = settings_data["user_color"]
            self.debug_enabled = settings_data["debug_enabled"]
            self.apply_updated_styles()
            self.agents_tab.load_global_preferences()
            self.save_settings()

    def apply_updated_styles(self):
        if self.dark_mode:
            self.apply_dark_mode_style()
        else:
            self.apply_light_mode_style()

    # -------------------------------------------------------------------------
    # Chat / UI Utility
    # -------------------------------------------------------------------------
    def send_message(self, user_text):
        # Disable send button to prevent multiple clicks
        self.chat_tab.send_button.setEnabled(False)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_message_html = f'<span style="color:{self.user_color};">[{timestamp}] {self.user_name}:</span> {user_text}'
        self.chat_tab.append_message_html(user_message_html)

        user_message = {"role": "user", "content": user_text}
        self.chat_history.append(user_message)

        # If a Coordinator agent is enabled, send the message to the Coordinator agents only.
        enabled_coordinator_agents = [
            (agent_name, agent_settings)
            for agent_name, agent_settings in self.agents_data.items()
            if agent_settings.get('enabled', False) and agent_settings.get('role') == 'Coordinator'
        ]

        # If no Coordinator is enabled, fall back to the old logic of sending to all enabled agents, except Specialists.
        if not enabled_coordinator_agents:
            enabled_agents = [
                (agent_name, agent_settings)
                for agent_name, agent_settings in self.agents_data.items()
                if agent_settings.get('enabled', False)
                and not agent_settings.get('desktop_history_enabled', False)
                and agent_settings.get('role') != 'Specialist'
            ]

            if not enabled_agents:
                QMessageBox.warning(self, "No Agents Enabled", "Please enable at least one Assistant agent or a Coordinator agent.")
                self.chat_tab.send_button.setEnabled(True)  # Re-enable send button
                return
        else:
            enabled_agents = enabled_coordinator_agents

        def process_next_agent(index):
            if index is None or index >= len(enabled_agents):
                self.chat_tab.send_button.setEnabled(True)  # Re-enable send button after all agents have responded
                return

            agent_name, agent_settings = enabled_agents[index]
            if self.debug_enabled:
                print(f"[Debug] Processing agent: {agent_name}")

            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            if not model_name:
                QMessageBox.warning(self, "Invalid Model Name", f"Agent '{agent_name}' has no valid model name.")
                process_next_agent(index + 1)
                return

            temperature = agent_settings.get("temperature", 0.7)
            max_tokens = agent_settings.get("max_tokens", 512)
            
            # Build appropriate chat history
            if agent_settings.get('role') == 'Coordinator':
                chat_history = self.build_agent_chat_history(agent_name, user_message)
            elif agent_settings.get('role') == 'Specialist':
                chat_history = self.build_agent_chat_history(agent_name)
            else: # Default to old behavior for Assistant agents
                chat_history = self.build_agent_chat_history(agent_name)
            
            thread = QThread()
            # Pass the agents_data to the AIWorker
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self.worker_finished_sequential(worker, thread, agent_name, index, process_next_agent)

            worker.response_received.connect(self.handle_ai_response_chunk)
            worker.error_occurred.connect(self.handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()

        process_next_agent(0)

    def clear_chat(self):
        if self.debug_enabled:
            print("[Debug] Clearing chat.")
        self.chat_tab.chat_display.clear()
        self.chat_history = []

    def handle_ai_response_chunk(self, chunk, agent_name):
        if agent_name not in self.current_responses:
            self.current_responses[agent_name] = ''
        self.current_responses[agent_name] += chunk

    def handle_worker_error(self, error_message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_tab.append_message_html(f"[{timestamp}] {error_message}")

    def worker_finished_sequential(self, sender_worker, thread, agent_name, index, process_next_agent):
        assistant_content = self.current_responses.get(agent_name, "")
        if agent_name in self.current_responses:
            del self.current_responses[agent_name]

        tool_request = None
        task_request = None
        content = assistant_content.strip()

        # Get the agent's settings
        agent_settings = self.agents_data.get(agent_name, {})

        # Check if this is a Specialist agent and if it was called by the Coordinator
        if agent_settings.get('role') == 'Specialist':
            if self.chat_history and self.chat_history[-1]['role'] == 'assistant':
                last_message = self.chat_history[-1]['content']
                if last_message.endswith(f"Next Response By: {agent_name}"):
                    # This is a valid response from a Specialist to the Coordinator
                    content = "[Response to Coordinator] " + content
                else:
                    # Specialist is not supposed to respond unless called by the Coordinator
                    if process_next_agent is not None and index is not None:
                        process_next_agent(index + 1)
                    return
            else:
                if process_next_agent is not None and index is not None:
                    process_next_agent(index + 1)
                return

        # Parse the content as JSON if it's a Coordinator or Specialist response
        parsed = None
        if agent_settings.get('role') in ['Coordinator', 'Specialist']:
            if content.startswith("{") and content.endswith("}"):
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = None

        if parsed is not None:
            if "tool_request" in parsed:
                tool_request = parsed["tool_request"]
                content = parsed.get("content", "").strip()
            if "task_request" in parsed:
                task_request = parsed["task_request"]
                content = parsed.get("content", "").strip()

        timestamp = datetime.now().strftime("%H:%M:%S")
        agent_color = self.agents_data.get(agent_name, {}).get("color", "#000000")

        # If the message is from a Coordinator and contains "Next Response By:", extract the next agent's name.
        next_agent = None
        if agent_settings.get('role') == 'Coordinator' and "Next Response By:" in content:
            parts = content.split("Next Response By:")
            content = parts[0].strip()  # The part before "Next Response By:"
            next_agent = parts[1].strip()

        # Debugging: Print content before modification
        print(f"[Debug] Content before modification: '{content}'")

        if agent_settings.get('role') == 'Coordinator':
            # Ensure the Coordinator's message ends with "Next Response By: [Agent Name]"
            if content and next_agent and not content.endswith(f"Next Response By: {next_agent}"):
                content += f"\nNext Response By: {next_agent}"
                
        # Debugging: Print content after modification
        print(f"[Debug] Content after modification: '{content}'")

        # Display the message from the Coordinator or Assistant
        if agent_settings.get('role') in ['Coordinator', 'Assistant']:
            if content:
                # Check if the message is from a Specialist responding to the Coordinator
                if content.startswith("[Response to Coordinator]"):
                    content = content.replace("[Response to Coordinator]", "").strip() # Remove the prefix
                    self.chat_tab.append_message_html(
                        f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {content}"
                    )
                    self.chat_history.append({"role": "assistant", "content": content, "agent": agent_name})
                else:
                    self.chat_tab.append_message_html(
                        f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {content}"
                    )
                    self.chat_history.append({"role": "assistant", "content": content, "agent": agent_name})
        
        # Display the message from a Specialist if specified by Coordinator
        elif agent_settings.get('role') == 'Specialist' and any(msg['content'].strip().endswith(f"Next Response By: {agent_name}") for msg in self.chat_history):
            self.chat_tab.append_message_html(
                f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {content}"
            )
            self.chat_history.append({"role": "assistant", "content": content, "agent": agent_name})

        # If there's a next agent specified and it's managed by the Coordinator, process it.
        if next_agent:
            managed_agents = agent_settings.get('managed_agents', [])
            if next_agent in managed_agents:
                # Send the user's original message to the next agent.
                # We assume that the user's message is always the last message with role 'user'.
                user_message = next((msg for msg in reversed(self.chat_history) if msg["role"] == "user"), None)
                if user_message:
                    self.send_message_to_agent(next_agent, user_message['content'])
            else:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{next_agent}' is not managed by Coordinator '{agent_name}'.</span>"
                self.chat_tab.append_message_html(error_msg)
        
        # We should always call process_next_agent if there is one to trigger the next agent.
        elif process_next_agent is not None and index is not None:
            process_next_agent(index + 1)

        # Handle tool request if any, only if the agent is allowed to use tools
        if tool_request and agent_settings.get("tool_use", False):
            tool_name = tool_request.get("name", "")
            tool_args = tool_request.get("args", {})
            
            # Check if the requested tool is enabled for the agent
            enabled_tools = agent_settings.get("tools_enabled", [])
            if tool_name not in enabled_tools:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Tool Error] Tool '{tool_name}' is not enabled for agent '{agent_name}'.</span>"
                self.chat_tab.append_message_html(error_msg)
                self.chat_history.append({"role": "assistant", "content": error_msg, "agent": agent_name})
            else:
                tool_result = run_tool(self.tools, tool_name, tool_args, self.debug_enabled)

                # Check for tool errors and handle them
                if tool_result.startswith("[Tool Error]"):
                    error_msg = f"[{timestamp}] <span style='color:red;'>{tool_result}</span>"
                    self.chat_tab.append_message_html(error_msg)
                    # Append error message to chat history
                    self.chat_history.append({"role": "assistant", "content": error_msg, "agent": agent_name})
                else:
                    display_message = f"{agent_name} used {tool_name} with args {tool_args}\nTool Result: {tool_result}"
                    self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{display_message}</span>")
                    self.chat_history.append({"role": "assistant", "content": display_message, "agent": agent_name})

        # Handle task request if any
        if task_request:
            agent_for_task = task_request.get("agent_name", "Default Agent")
            prompt_for_task = task_request.get("prompt", "No prompt provided")
            due_time = task_request.get("due_time", "")
            if due_time:
                add_task(
                    self.tasks,
                    agent_for_task,
                    prompt_for_task,
                    due_time,
                    creator="agent",
                    debug_enabled=self.debug_enabled
                )
                note = f"Agent '{agent_name}' scheduled a new task for '{agent_for_task}' at {due_time}."
                self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{note}</span>")
            else:
                warn_msg = "[Task Error] Missing due_time in request."
                self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:red;'>{warn_msg}</span>")

        if self.debug_enabled and agent_name:
            print(f"[Debug] Worker for agent '{agent_name}' finished.")

        thread.quit()
        thread.wait()

        for i, (worker_item, thread_item) in enumerate(self.active_worker_threads):
            if worker_item == sender_worker:
                del self.active_worker_threads[i]
                break

        sender_worker.deleteLater()
        thread.deleteLater()

        if process_next_agent is not None and index is not None:
            process_next_agent(index + 1)

    def send_message_to_agent(self, agent_name, message):
        """
        Sends a message to a specific agent.
        This is used by the Coordinator to direct messages to managed agents.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Construct a message to indicate which agent should respond next
        formatted_message = f"{message}\nNext Response By: {agent_name}"

        # Add this message to the chat history
        self.chat_history.append({"role": "user", "content": formatted_message})

        # Find the agent settings
        agent_settings = self.agents_data.get(agent_name, {})
        if not agent_settings:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' not found.</span>"
            self.chat_tab.append_message_html(error_msg)
            return

        # If the agent is enabled, start a worker thread to process the message
        if agent_settings.get('enabled', False):
            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            temperature = agent_settings.get("temperature", 0.7)
            max_tokens = agent_settings.get("max_tokens", 512)
            chat_history = self.build_agent_chat_history(agent_name)

            thread = QThread()
            # Pass the agents_data to the AIWorker
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self.worker_finished_sequential(worker, thread, agent_name, None, process_next_agent=self.process_next_agent)

            worker.response_received.connect(self.handle_ai_response_chunk)
            worker.error_occurred.connect(self.handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()
        else:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' is not enabled.</span>"
            self.chat_tab.append_message_html(error_msg)


    # -------------------------------------------------------------------------
    # Agents / Settings Management
    # -------------------------------------------------------------------------
    def populate_agents(self):
        self.agents_data = {}
        if os.path.exists(AGENTS_SAVE_FILE):
            try:
                with open(AGENTS_SAVE_FILE, "r") as f:
                    self.agents_data = json.load(f)
                if self.debug_enabled:
                    print("[Debug] Agents loaded.")
            except Exception as e:
                print(f"[Debug] Failed to load agents: {e}")
        else:
            default_agent_settings = {
                "model": "llama3.2-vision",
                "temperature": 0.7,
                "max_tokens": 512,
                "system_prompt": "",
                "enabled": True,
                "color": "#000000",
                "include_image": False,
                "desktop_history_enabled": False,
                "screenshot_interval": 5,
                "role": "Assistant",  # Default role
                "description": "A general-purpose assistant.", # Default description
                "tool_use": False,
                "tools_enabled": []
            }
            self.agents_data["Default Agent"] = default_agent_settings
            if self.debug_enabled:
                print("[Debug] Default agent added.")

        self.agents_tab.agent_selector.clear()
        for agent_name in self.agents_data.keys():
            self.agents_tab.agent_selector.addItem(agent_name)

        if self.agents_tab.agent_selector.count() > 0:
            self.agents_tab.load_agent_settings(self.agents_tab.agent_selector.currentText())

    def add_agent(self):
        from PyQt5.QtWidgets import QInputDialog
        agent_name, ok = QInputDialog.getText(self, "Add Agent", "Enter agent name:")
        if ok and agent_name.strip():
            agent_name = agent_name.strip()
            if agent_name not in self.agents_data:
                self.agents_data[agent_name] = {
                    "model": "llama3.2-vision",
                    "temperature": 0.7,
                    "max_tokens": 512,
                    "system_prompt": "",
                    "enabled": True,
                    "color": "#000000",
                    "include_image": False,
                    "desktop_history_enabled": False,
                    "screenshot_interval": 5,
                    "role": "Assistant",
                    "description": "A new assistant agent.",
                    "tool_use": False,
                    "tools_enabled": []
                }
                self.agents_tab.agent_selector.addItem(agent_name)
                self.save_agents()
                if self.debug_enabled:
                    print(f"[Debug] Agent '{agent_name}' added.")
            else:
                QMessageBox.warning(self, "Agent Exists", "Agent already exists.")
        self.update_send_button_state()

    def delete_agent(self):
        current_agent = self.agents_tab.agent_selector.currentText()
        if current_agent:
            if current_agent in self.agents_data:
                del self.agents_data[current_agent]
                idx = self.agents_tab.agent_selector.currentIndex()
                self.agents_tab.agent_selector.removeItem(idx)
                self.save_agents()
                if self.debug_enabled:
                    print(f"[Debug] Agent '{current_agent}' removed.")
        self.update_send_button_state()

    def save_agents(self):
        try:
            with open(AGENTS_SAVE_FILE, "w") as f:
                json.dump(self.agents_data, f, indent=4)
            if self.debug_enabled:
                print("[Debug] Agents saved.")
        except Exception as e:
            print(f"[Debug] Failed to save agents: {e}")

    def update_send_button_state(self):
        any_enabled = any(
            a.get("enabled", False)
            for a in self.agents_data.values()
            if not a.get("desktop_history_enabled", False)
            and a.get("role") != 'Specialist'
        )
        self.chat_tab.send_button.setEnabled(any_enabled)

    # -------------------------------------------------------------------------
    # Tools Management
    # -------------------------------------------------------------------------
    def refresh_tools_list(self):
        self.tools = load_tools(self.debug_enabled)
        if hasattr(self.tools_tab, "refresh_tools_list"):
            self.tools_tab.tools = self.tools
            self.tools_tab.refresh_tools_list()

    # -------------------------------------------------------------------------
    # Tasks / Scheduling
    # -------------------------------------------------------------------------
    def check_for_due_tasks(self):
        now = datetime.now()
        to_remove = []
        for t in self.tasks:
            due_str = t.get("due_time", "")
            try:
                if "T" in due_str:
                    due_dt = datetime.fromisoformat(due_str)
                else:
                    due_dt = datetime.strptime(due_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if now >= due_dt:
                agent_name = t.get("agent_name", "")
                prompt = t.get("prompt", "")
                self.schedule_user_message(agent_name, prompt, t["id"])
                to_remove.append(t["id"])

        for task_id in to_remove:
            delete_task(self.tasks, task_id, debug_enabled=self.debug_enabled)
            save_tasks(self.tasks, debug_enabled=self.debug_enabled)

    def schedule_user_message(self, agent_name, prompt, task_id=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        message_html = f'<span style="color:{self.user_color};">[{timestamp}] (Scheduled) {self.user_name}:</span> {prompt}'
        self.chat_tab.append_message_html(message_html)

        user_message = {"role": "user", "content": prompt}
        self.chat_history.append(user_message)

        agent_settings = self.agents_data.get(agent_name, None)
        if not agent_settings:
            msg = f"[Task Error] Agent '{agent_name}' not found for Task '{task_id}'"
            self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:red;'>{msg}</span>")
            return

        if not agent_settings.get("enabled", False):
            msg = f"[Task Error] Agent '{agent_name}' is disabled. Task '{task_id}' skipped."
            self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:red;'>{msg}</span>")
            return

        model_name = agent_settings.get("model", "llama3.2-vision").strip()
        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)
        chat_history = self.build_agent_chat_history(agent_name)

        thread = QThread()
        # Pass the agents_data to the AIWorker
        worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self.worker_finished_sequential(worker, thread, agent_name, None, None)

        worker.response_received.connect(self.handle_ai_response_chunk)
        worker.error_occurred.connect(self.handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()

    # -------------------------------------------------------------------------
    # Chat History Helpers
    # -------------------------------------------------------------------------
    def build_agent_chat_history(self, agent_name, user_message=None, is_screenshot=False):
        system_prompt = ""
        agent_settings = self.agents_data.get(agent_name, {})

        if agent_settings:
            # If the agent is a Coordinator, include managed agents and their descriptions in the system prompt
            if agent_settings.get('role') == 'Coordinator':
                managed_agents_info = []
                for managed_agent_name in agent_settings.get('managed_agents', []):
                    managed_agent_settings = self.agents_data.get(managed_agent_name, {})
                    if managed_agent_settings:
                        managed_agent_desc = managed_agent_settings.get('description', 'No description available')
                        managed_agents_info.append(f"{managed_agent_name}: {managed_agent_desc}")
                
                if managed_agents_info:
                    system_prompt += "You can choose from the following agents:\n" + "\n".join(managed_agents_info) + "\n"

            # Include the agent's specific system prompt
            system_prompt += agent_settings.get("system_prompt", "")

            # Include tool instructions only if tool_use is enabled
            if agent_settings.get("tool_use", False):
                tool_instructions = self.generate_tool_instructions_message(agent_name)
                system_prompt += "\n" + tool_instructions

        # Build the chat history with the constructed system prompt
        chat_history = [{"role": "system", "content": system_prompt}]

        # Filter messages for the chat history
        temp_history = []
        for msg in self.chat_history:
            if msg['role'] == 'user':
                temp_history.append(msg)
            elif msg['role'] == 'assistant':
                if msg.get('agent') == agent_name:
                    temp_history.append(msg)
                # Include messages from specialists if this agent is a coordinator
                elif agent_settings.get('role') == 'Coordinator' and self.agents_data.get(msg.get('agent'), {}).get('role') == 'Specialist':
                    temp_history.append(msg)

        # If the last message indicates a handoff to a Specialist, insert the Specialist's description AFTER the handoff message
        if temp_history:
            last_message = temp_history[-1]
            if last_message['role'] == 'assistant' and "Next Response By:" in last_message['content']:
                next_agent_name = last_message['content'].split("Next Response By:")[1].strip()
                next_agent_settings = self.agents_data.get(next_agent_name, {})
                if next_agent_settings.get('role') == 'Specialist':
                    specialist_description = next_agent_settings.get('description', '')
                    if specialist_description:
                        # Append the specialist description as an assistant message
                        temp_history.append({"role": "assistant", "content": specialist_description, "agent": next_agent_name})

        # Add the user message to the history if provided
        if user_message:
            temp_history.append(user_message)

        chat_history.extend(temp_history)
        return chat_history


    def generate_tool_instructions_message(self, agent_name):
        agent_settings = self.agents_data.get(agent_name, {})
        if agent_settings.get("tool_use", False):
            enabled_tools = agent_settings.get("tools_enabled", [])
            tool_list_str = ""
            for t in self.tools:
                if t['name'] in enabled_tools:
                    tool_list_str += f"- {t['name']}: {t['description']}\n"
            instructions = (
                "You are a knowledgeable assistant. You can answer most questions directly.\n"
                "ONLY use a tool if you cannot answer from your own knowledge. If you can answer directly, do so.\n"
                "If using a tool, respond ONLY in the following exact JSON format and nothing else:\n"
                "{\n"
                ' "role": "assistant",\n'
                ' "content": "<explanation>",\n'
                ' "tool_request": {\n'
                '     "name": "<tool_name>",\n'
                '     "args": { ... }\n'
                ' }\n'
                '}\n'
                "No extra text outside this JSON when calling a tool.\n"
                f"Available tools:\n{tool_list_str}"
            )
            return instructions
        else:
            return ""

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------
    def save_settings(self):
        settings = {
            "debug_enabled": self.debug_enabled,
            "include_image": self.include_image,
            "include_screenshot": self.include_screenshot,
            "image_path": "",
            "user_name": self.user_name,
            "user_color": self.user_color,
            "dark_mode": self.dark_mode
        }
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(settings, f)
            if self.debug_enabled:
                print("[Debug] Settings saved.")
        except Exception as e:
            print(f"[Error failed to save settings: {e}")

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    settings = json.load(f)
                self.debug_enabled = settings.get("debug_enabled", False)
                self.include_image = settings.get("include_image", False)
                self.include_screenshot = settings.get("include_screenshot", False)
                self.user_name = settings.get("user_name", "You")
                self.user_color = settings.get("user_color", "#0000FF")
                self.dark_mode = settings.get("dark_mode", False)
                if self.debug_enabled:
                    print("[Debug] Settings loaded.")
            except Exception as e:
                print(f"[Error] Failed to load settings: {e}")
                
        self.agents_tab.load_global_preferences()

    # -------------------------------------------------------------------------
    # Dark/Light Mode
    # -------------------------------------------------------------------------
    def apply_dark_mode_style(self):
        with open("dark_mode.qss", "r") as f:
            style_sheet = f.read()
        self.setStyleSheet(style_sheet)

    def apply_light_mode_style(self):
        with open("light_mode.qss", "r") as f:
            style_sheet = f.read()
        self.setStyleSheet(style_sheet)

    # -------------------------------------------------------------------------
    # Close Event
    # -------------------------------------------------------------------------
    def closeEvent(self, event):
        for worker, thread in self.active_worker_threads:
            thread.quit()
            thread.wait()
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()
        event.accept()