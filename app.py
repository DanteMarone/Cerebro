# app.py

import os
import json
from datetime import datetime
from PyQt5 import QtCore
from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox
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

class AIChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
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

        # Apply dark mode if relevant
        if self.dark_mode:
            self.apply_dark_mode_style()

        # Check tasks regularly
        self.task_timer = QtCore.QTimer(self)
        self.task_timer.timeout.connect(self.check_for_due_tasks)
        self.task_timer.start(30_000)  # 30 seconds in ms

    # -------------------------------------------------------------------------
    # Chat / UI Utility
    # -------------------------------------------------------------------------
    def send_message(self, user_text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_message_html = f'<span style="color:{self.user_color};">[{timestamp}] {self.user_name}:</span> {user_text}'
        self.chat_tab.append_message_html(user_message_html)

        user_message = {"role": "user", "content": user_text}
        self.chat_history.append(user_message)

        enabled_agents = [
            (agent_name, agent_settings)
            for agent_name, agent_settings in self.agents_data.items()
            if agent_settings.get('enabled', False)
            and not agent_settings.get('desktop_history_enabled', False)
        ]
        if not enabled_agents:
            QMessageBox.warning(self, "No Agents Enabled", "Please enable at least one non-DH agent.")
            return

        def process_next_agent(index):
            if index is None or index >= len(enabled_agents):
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
            chat_history = self.build_agent_chat_history(agent_name)
            thread = QThread()
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name)
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

        parsed = None
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

        if tool_request:
            tool_name = tool_request.get("name", "")
            tool_args = tool_request.get("args", {})
            tool_result = run_tool(self.tools, tool_name, tool_args, self.debug_enabled)
            display_message = f"{agent_name} used {tool_name} with args {tool_args}\nTool Result: {tool_result}"
            self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{display_message}</span>")
            self.chat_history.append({"role": "assistant", "content": display_message, "agent": agent_name})
        else:
            final_content = content.strip()
            if final_content:
                self.chat_tab.append_message_html(
                    f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {final_content}"
                )
                self.chat_history.append({"role": "assistant", "content": final_content, "agent": agent_name})

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
                "screenshot_interval": 5
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
                    "screenshot_interval": 5
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
                json.dump(self.agents_data, f)
            if self.debug_enabled:
                print("[Debug] Agents saved.")
        except Exception as e:
            print(f"[Debug] Failed to save agents: {e}")

    def update_send_button_state(self):
        any_enabled = any(
            a.get("enabled", False)
            for a in self.agents_data.values()
            if not a.get("desktop_history_enabled", False)
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
        worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name)
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
        desktop_history_enabled = self.agents_data.get(agent_name, {}).get("desktop_history_enabled", False)
        system_prompt = self.agents_data.get(agent_name, {}).get("system_prompt", "")
        tool_instructions = self.generate_tool_instructions_message()

        chat_history = [{"role": "system", "content": tool_instructions}]
        if system_prompt:
            chat_history.append({"role": "system", "content": system_prompt})

        dh_agents = [a for a, s in self.agents_data.items() if s.get("desktop_history_enabled", False)]
        filtered_history = []
        for msg in self.chat_history:
            if msg['role'] == 'user':
                filtered_history.append(msg)
            elif msg['role'] == 'assistant':
                if msg.get('agent') == agent_name or msg.get('agent') in dh_agents:
                    filtered_history.append(msg)

        if user_message:
            filtered_history.append(user_message)
        chat_history.extend(filtered_history)
        return chat_history

    def generate_tool_instructions_message(self):
        tool_list_str = ""
        for t in self.tools:
            tool_list_str += f"- {t['name']}: {t['description']}\n"
        instructions = (
            "You are a knowledgeable assistant. You can answer most questions directly.\n"
            "ONLY use a tool if you cannot answer from your own knowledge. If you can answer directly, do so.\n"
            "If using a tool, respond ONLY in the following exact JSON format and nothing else:\n"
            "{\n"
            '  "role": "assistant",\n'
            '  "content": "<explanation>",\n'
            '  "tool_request": {\n'
            '    "name": "<tool_name>",\n'
            '    "args": { ... }\n'
            '  }\n'
            '}\n'
            "No extra text outside this JSON when calling a tool.\n"
            f"Available tools:\n{tool_list_str}"
        )
        return instructions

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
            print(f"[Error] Failed to save settings: {e}")

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

        self.agents_tab.username_input.setText(self.user_name)
        self.agents_tab.user_color_button.setStyleSheet(f"background-color: {self.user_color}")
        self.agents_tab.dark_mode_checkbox.setChecked(self.dark_mode)

    # -------------------------------------------------------------------------
    # Dark/Light Mode
    # -------------------------------------------------------------------------
    def apply_dark_mode_style(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #2E2E2E;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #4C4C4C;
                color: #FFFFFF;
            }
            QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #3C3C3C;
                color: #FFFFFF;
            }
            QCheckBox, QLabel, QGroupBox {
                color: #FFFFFF;
            }
        """)

    def apply_light_mode_style(self):
        self.setStyleSheet("")

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
