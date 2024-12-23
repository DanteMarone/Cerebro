import json
import os
import re
import base64
from datetime import datetime
from PyQt5 import QtCore
from PyQt5.QtWidgets import (
    QMainWindow, QVBoxLayout, QTextEdit, QPushButton, QWidget, QComboBox,
    QLabel, QSpinBox, QDoubleSpinBox, QGroupBox, QFormLayout, QCheckBox, QHBoxLayout,
    QMessageBox, QInputDialog, QFileDialog, QLineEdit, QColorDialog, QDialog, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QThread
from PyQt5.QtGui import QTextCursor, QColor

from worker import AIWorker
from tools import load_tools, run_tool, add_tool, edit_tool, delete_tool

AGENTS_SAVE_FILE = "agents.json"
SETTINGS_FILE = "settings.json"

class ToolDialog(QDialog):
    SAMPLE_SCRIPT = """def run_tool(args):
    # This function will be called with a dictionary 'args'
    # It must return a string as the result.
    return "Hello from the sample tool!"
"""

    def __init__(self, title="Add Tool", name="", description="", script=None):
        super().__init__()
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        self.name_edit = QLineEdit(name)
        self.description_edit = QLineEdit(description)
        self.script_edit = QTextEdit(script if script is not None else self.SAMPLE_SCRIPT)

        layout.addWidget(QLabel("Name:"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Description:"))
        layout.addWidget(self.description_edit)
        layout.addWidget(QLabel("Script (must define run_tool(args)):\n"))
        layout.addWidget(self.script_edit)

        btn_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_button)
        btn_layout.addWidget(self.cancel_button)

        layout.addLayout(btn_layout)

    def get_data(self):
        return (self.name_edit.text().strip(), self.description_edit.text().strip(), self.script_edit.toPlainText().strip())

class ToolsWindow(QDialog):
    def __init__(self, parent, tools, debug_enabled=False):
        super().__init__(parent)
        self.setWindowTitle("Manage Tools")
        self.debug_enabled = debug_enabled
        self.parent_app = parent
        self.tools = tools
        self.layout = QVBoxLayout(self)

        # Tools list
        self.tools_list = QListWidget()
        self.refresh_tools_list()
        self.layout.addWidget(self.tools_list)

        # Buttons below list
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Tool")
        self.add_button.clicked.connect(self.add_tool_ui)
        btn_layout.addWidget(self.add_button)

        self.layout.addLayout(btn_layout)

    def refresh_tools_list(self):
        self.tools_list.clear()
        for t in self.tools:
            item = QListWidgetItem()
            item.setText(f"{t['name']}: {t['description']}")
            self.tools_list.addItem(item)

            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0,0,0,0)

            label = QLabel(f"{t['name']}: {t['description']}")
            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda _, tn=t['name']: self.edit_tool_ui(tn))
            del_btn = QPushButton("Delete")
            del_btn.clicked.connect(lambda _, tn=t['name']: self.delete_tool_ui(tn))

            h_layout.addWidget(label)
            h_layout.addWidget(edit_btn)
            h_layout.addWidget(del_btn)
            container.setLayout(h_layout)

            self.tools_list.setItemWidget(item, container)

    def add_tool_ui(self):
        dialog = ToolDialog(title="Add Tool")
        if dialog.exec_() == QDialog.Accepted:
            name, desc, script = dialog.get_data()
            err = add_tool(self.tools, name, desc, script, self.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Adding Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()

    def edit_tool_ui(self, tool_name):
        tool = next((t for t in self.tools if t['name'] == tool_name), None)
        if not tool:
            QMessageBox.warning(self, "Error", f"No tool named '{tool_name}' found.")
            return
        dialog = ToolDialog(title="Edit Tool", name=tool["name"], description=tool["description"], script=tool["script"])
        if dialog.exec_() == QDialog.Accepted:
            new_name, desc, script = dialog.get_data()
            err = edit_tool(self.tools, tool["name"], new_name, desc, script, self.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Editing Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()

    def delete_tool_ui(self, tool_name):
        reply = QMessageBox.question(self, 'Confirm Delete', f"Are you sure you want to delete the tool '{tool_name}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            err = delete_tool(self.tools, tool_name, self.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Deleting Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()

class AIChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        if os.environ.get("DEBUG_MODE", "") == "1":
            self.debug_enabled = True
        else:
            self.debug_enabled = False
        print("[Debug] Initializing AIChatApp...")
        self.setWindowTitle("Cerebro 1.0")
        self.setGeometry(100, 100, 600, 700)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        # Variables
        self.chat_history = []
        self.current_responses = {}
        self.agents_data = {}
        # Debug can be toggled via UI
        # Include image and screenshot not used globally except for per-agent
        self.include_image = False
        self.include_screenshot = False
        self.current_agent_color = "#000000"
        self.user_name = "You"
        self.user_color = "#0000FF"
        self.dark_mode = False
        self.active_worker_threads = []
        self.tools = load_tools(self.debug_enabled)

        # UI Setup
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.layout.addWidget(self.chat_display)

        self.tools_button = QPushButton("Manage Tools")
        self.tools_button.clicked.connect(self.open_tools_window)
        self.layout.addWidget(self.tools_button)

        self.user_input = QTextEdit()
        self.user_input.setPlaceholderText("Type your message here...")
        self.user_input.setMaximumHeight(100)
        self.user_input.textChanged.connect(self.adjust_input_height)
        self.user_input.installEventFilter(self)
        self.layout.addWidget(self.user_input)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        self.layout.addWidget(self.send_button)

        self.clear_chat_button = QPushButton("Clear Chat")
        self.clear_chat_button.clicked.connect(self.clear_chat)
        self.layout.addWidget(self.clear_chat_button)

        self.advanced_button = QPushButton("Advanced")
        self.advanced_button.setCheckable(True)
        self.advanced_button.clicked.connect(self.toggle_advanced_options)
        self.layout.addWidget(self.advanced_button)

        self.global_prefs_button = QPushButton("Global Preferences")
        self.global_prefs_button.setCheckable(True)
        self.global_prefs_button.clicked.connect(self.toggle_global_preferences)
        self.layout.addWidget(self.global_prefs_button)

        # Advanced Options
        self.advanced_options_group = QGroupBox("Advanced Options")
        self.advanced_options_layout = QFormLayout()

        self.enabled_checkbox = QCheckBox("Enable Agent")
        self.enabled_checkbox.stateChanged.connect(self.save_agent_settings)
        self.advanced_options_layout.addRow(self.enabled_checkbox)

        self.temperature_label = QLabel("Temperature:")
        self.temperature_spinbox = QDoubleSpinBox()
        self.temperature_spinbox.setRange(0.0, 1.0)
        self.temperature_spinbox.setSingleStep(0.1)
        self.temperature_spinbox.setValue(0.7)
        self.advanced_options_layout.addRow(self.temperature_label, self.temperature_spinbox)

        self.max_tokens_label = QLabel("Max Tokens:")
        self.max_tokens_spinbox = QSpinBox()
        self.max_tokens_spinbox.setRange(1, 4096)
        self.max_tokens_spinbox.setValue(512)
        self.advanced_options_layout.addRow(self.max_tokens_label, self.max_tokens_spinbox)

        self.model_name_label = QLabel("Model Name:")
        self.model_name_input = QLineEdit()
        self.advanced_options_layout.addRow(self.model_name_label, self.model_name_input)

        self.debug_checkbox = QCheckBox("Enable Debug")
        self.debug_checkbox.stateChanged.connect(self.update_debug_enabled)
        self.advanced_options_layout.addRow(self.debug_checkbox)

        self.include_image_checkbox = QCheckBox("Include Image (Manual)")
        self.include_image_checkbox.stateChanged.connect(self.save_agent_settings)
        self.advanced_options_layout.addRow(self.include_image_checkbox)

        self.desktop_history_checkbox = QCheckBox("Enable Desktop History")
        self.desktop_history_checkbox.stateChanged.connect(self.save_agent_settings)
        self.advanced_options_layout.addRow(self.desktop_history_checkbox)

        self.screenshot_interval_label = QLabel("Screenshot Interval (seconds):")
        self.screenshot_interval_spinbox = QSpinBox()
        self.screenshot_interval_spinbox.setRange(1, 3600)
        self.screenshot_interval_spinbox.setValue(5)
        self.screenshot_interval_spinbox.valueChanged.connect(self.save_agent_settings)
        self.advanced_options_layout.addRow(self.screenshot_interval_label, self.screenshot_interval_spinbox)

        self.image_input_layout = QHBoxLayout()
        self.image_path_input = QLineEdit()
        self.image_path_input.setPlaceholderText("Enter image file path...")
        self.image_path_input.textChanged.connect(self.save_settings)
        self.browse_image_button = QPushButton("Browse")
        self.browse_image_button.clicked.connect(self.browse_image_file)
        self.image_input_layout.addWidget(self.image_path_input)
        self.image_input_layout.addWidget(self.browse_image_button)
        self.advanced_options_layout.addRow(QLabel("Image File:"), self.image_input_layout)

        self.system_prompt_label = QLabel("Custom System Prompt:")
        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setFixedHeight(60)
        self.system_prompt_input.textChanged.connect(self.save_agent_settings)
        self.advanced_options_layout.addRow(self.system_prompt_label, self.system_prompt_input)

        self.color_label = QLabel("Agent Color:")
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.select_agent_color)
        self.color_button.setStyleSheet("background-color: black")
        self.advanced_options_layout.addRow(self.color_label, self.color_button)

        self.advanced_options_group.setLayout(self.advanced_options_layout)
        self.advanced_options_group.setVisible(False)
        self.layout.addWidget(self.advanced_options_group)

        # Global Preferences Group
        self.global_preferences_group = QGroupBox("Global Preferences")
        self.global_preferences_layout = QFormLayout()

        self.username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        self.username_input.textChanged.connect(self.save_global_preferences)
        self.global_preferences_layout.addRow(self.username_label, self.username_input)

        self.user_color_label = QLabel("User Color:")
        self.user_color_button = QPushButton()
        self.user_color_button.setStyleSheet(f"background-color: {self.user_color}")
        self.user_color_button.clicked.connect(self.select_user_color)
        self.global_preferences_layout.addRow(self.user_color_label, self.user_color_button)

        self.dark_mode_checkbox = QCheckBox("Dark Mode")
        self.dark_mode_checkbox.stateChanged.connect(self.toggle_dark_mode)
        self.global_preferences_layout.addRow(self.dark_mode_checkbox)

        self.global_preferences_group.setLayout(self.global_preferences_layout)
        self.global_preferences_group.setVisible(False)
        self.layout.addWidget(self.global_preferences_group)

        # Agent Selection
        self.agent_label = QLabel("Select Agent:")
        self.layout.addWidget(self.agent_label)

        self.agent_selector_layout = QHBoxLayout()
        self.agent_selector = QComboBox()
        self.agent_selector_layout.addWidget(self.agent_selector)

        self.add_agent_button = QPushButton("Add Agent")
        self.add_agent_button.clicked.connect(self.add_agent)
        self.agent_selector_layout.addWidget(self.add_agent_button)

        self.delete_agent_button = QPushButton("Delete Agent")
        self.delete_agent_button.clicked.connect(self.delete_agent)
        self.agent_selector_layout.addWidget(self.delete_agent_button)

        self.layout.addLayout(self.agent_selector_layout)

        self.temperature_spinbox.valueChanged.connect(self.save_agent_settings)
        self.max_tokens_spinbox.valueChanged.connect(self.save_agent_settings)
        self.model_name_input.textChanged.connect(self.save_agent_settings)

        # Load settings and agents
        self.load_settings()
        self.populate_agents()
        self.update_send_button_state()

        if self.dark_mode:
            self.apply_dark_mode_style()

    def open_tools_window(self):
        tw = ToolsWindow(self, self.tools, self.debug_enabled)
        tw.exec_()

    def refresh_tools_list(self):
        self.tools = load_tools(self.debug_enabled)

    def toggle_dark_mode(self, state):
        self.dark_mode = (state == Qt.Checked)
        self.save_global_preferences()
        if self.dark_mode:
            self.apply_dark_mode_style()
        else:
            self.apply_light_mode_style()

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

    def toggle_global_preferences(self):
        self.global_preferences_group.setVisible(self.global_prefs_button.isChecked())

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

    def build_agent_chat_history(self, agent_name, user_message=None, is_screenshot=False):
        desktop_history_enabled = self.agents_data.get(agent_name, {}).get("desktop_history_enabled", False)
        system_prompt = self.agents_data.get(agent_name, {}).get("system_prompt", "")

        tool_instructions = self.generate_tool_instructions_message()
        chat_history = [{"role": "system", "content": tool_instructions}]

        if system_prompt:
            chat_history.append({"role": "system", "content": system_prompt})

        # If desktop historian is enabled and is_screenshot would be handled here if implemented.
        # For now, just proceed with normal chat history filtering.
        dh_agents = [a for a, s in self.agents_data.items() if s.get("desktop_history_enabled", False)]
        filtered_history = []
        for msg in self.chat_history:
            if msg['role'] == 'user':
                filtered_history.append(msg)
            elif msg['role'] == 'assistant':
                # Include messages from this agent or from DH agents
                if msg.get('agent') == agent_name or msg.get('agent') in dh_agents:
                    filtered_history.append(msg)
        if user_message:
            filtered_history.append(user_message)
        chat_history.extend(filtered_history)

        return chat_history

    def adjust_input_height(self):
        doc_height = self.user_input.document().size().height()
        new_height = int(doc_height + 10)
        self.user_input.setFixedHeight(min(new_height, 100))

    def eventFilter(self, obj, event):
        if obj == self.user_input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Return and not event.modifiers() & QtCore.Qt.ShiftModifier:
                self.send_message()
                return True
        return super(AIChatApp, self).eventFilter(obj, event)

    def toggle_advanced_options(self):
        self.advanced_options_group.setVisible(self.advanced_button.isChecked())

    def send_message(self):
        user_text = self.user_input.toPlainText().strip()
        if not user_text:
            return

        if self.debug_enabled:
            print(f"[Debug] User input: {user_text}")
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_message_html = f'<span style="color:{self.user_color};">[{timestamp}] {self.user_name}:</span> {user_text}'
        self.chat_display.append(user_message_html)
        self.user_input.clear()
        self.user_input.setFixedHeight(30)

        user_message = {"role": "user", "content": user_text}

        current_agent = self.agent_selector.currentText()
        # If agent has include_image, we attempt to add image
        if current_agent in self.agents_data and self.agents_data[current_agent].get("include_image", False):
            image_path = self.image_path_input.text().strip()
            if image_path:
                try:
                    with open(image_path, "rb") as image_file:
                        image_bytes = image_file.read()
                        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                        user_message["images"] = [image_base64]
                        if self.debug_enabled:
                            print(f"[Debug] Image '{image_path}' encoded.")
                except Exception as e:
                    error_msg = f"[Error] Failed to read image file: {e}"
                    if self.debug_enabled:
                        print(error_msg)
                    QMessageBox.critical(self, "Image Error", error_msg)
                    return
            else:
                QMessageBox.warning(self, "Image Not Specified", "Please specify an image file.")
                return

        self.chat_history.append(user_message)
        enabled_agents = [(agent_name, agent_settings)
                          for agent_name, agent_settings in self.agents_data.items()
                          if agent_settings.get('enabled', False) and not agent_settings.get('desktop_history_enabled', False)]

        if not enabled_agents:
            QMessageBox.warning(self, "No Agents Enabled", "Please enable at least one non-DH agent.")
            return

        def process_next_agent(index):
            if index is None or index >= len(enabled_agents):
                return

            agent_name, agent_settings = enabled_agents[index]
            if self.debug_enabled:
                print(f"[Debug] Processing agent: {agent_name}")

            # Validate model name
            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            if not model_name:
                QMessageBox.warning(self, "Invalid Model Name", f"Agent '{agent_name}' has no valid model name. Please set one.")
                process_next_agent(index+1)
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
        self.chat_display.clear()
        self.chat_history = []

    def add_agent(self):
        agent_name, ok = QInputDialog.getText(self, "Add Agent", "Enter agent name:")
        if ok and agent_name.strip():
            agent_name = agent_name.strip()
            if agent_name not in self.agents_data:
                self.agent_selector.addItem(agent_name)
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
                self.save_agents()
                if self.debug_enabled:
                    print(f"[Debug] Agent '{agent_name}' added.")
            else:
                QMessageBox.warning(self, "Agent Exists", "Agent already exists.")
        self.update_send_button_state()

    def delete_agent(self):
        current_agent = self.agent_selector.currentText()
        if current_agent:
            if current_agent in self.agents_data:
                del self.agents_data[current_agent]
            self.agent_selector.removeItem(self.agent_selector.currentIndex())
            self.save_agents()
            if self.debug_enabled:
                print(f"[Debug] Agent '{current_agent}' removed.")
        self.update_send_button_state()

    def populate_agents(self):
        self.agents_data = {}
        if os.path.exists(AGENTS_SAVE_FILE):
            try:
                with open(AGENTS_SAVE_FILE, "r") as f:
                    self.agents_data = json.load(f)
                    for a in self.agents_data.keys():
                        self.agent_selector.addItem(a)
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
            self.agent_selector.addItem("Default Agent")
            if self.debug_enabled:
                print("[Debug] Default agent added.")
        self.agent_selector.currentIndexChanged.connect(self.load_agent_settings)
        if self.agent_selector.count() > 0:
            self.load_agent_settings(self.agent_selector.currentIndex())

    def load_agent_settings(self, index):
        agent_name = self.agent_selector.currentText()
        if agent_name in self.agents_data:
            agent_settings = self.agents_data[agent_name]
            self.temperature_spinbox.blockSignals(True)
            self.max_tokens_spinbox.blockSignals(True)
            self.system_prompt_input.blockSignals(True)
            self.model_name_input.blockSignals(True)
            self.enabled_checkbox.blockSignals(True)
            self.debug_checkbox.blockSignals(True)
            self.include_image_checkbox.blockSignals(True)
            self.desktop_history_checkbox.blockSignals(True)
            self.screenshot_interval_spinbox.blockSignals(True)

            self.temperature_spinbox.setValue(agent_settings.get("temperature", 0.7))
            self.max_tokens_spinbox.setValue(agent_settings.get("max_tokens", 512))
            self.system_prompt_input.setText(agent_settings.get("system_prompt", ""))
            self.model_name_input.setText(agent_settings.get("model", "llama3.2-vision"))
            self.enabled_checkbox.setChecked(agent_settings.get("enabled", False))
            self.include_image_checkbox.setChecked(agent_settings.get("include_image", False))
            self.desktop_history_checkbox.setChecked(agent_settings.get("desktop_history_enabled", False))
            self.screenshot_interval_spinbox.setValue(agent_settings.get("screenshot_interval", 5))

            color = agent_settings.get("color", "#000000")
            self.color_button.setStyleSheet(f"background-color: {color}")
            self.current_agent_color = color

            self.temperature_spinbox.blockSignals(False)
            self.max_tokens_spinbox.blockSignals(False)
            self.system_prompt_input.blockSignals(False)
            self.model_name_input.blockSignals(False)
            self.enabled_checkbox.blockSignals(False)
            self.debug_checkbox.blockSignals(False)
            self.include_image_checkbox.blockSignals(False)
            self.desktop_history_checkbox.blockSignals(False)
            self.screenshot_interval_spinbox.blockSignals(False)

    def save_agent_settings(self):
        agent_name = self.agent_selector.currentText()
        if agent_name:
            self.agents_data[agent_name] = {
                "model": self.model_name_input.text().strip(),
                "temperature": self.temperature_spinbox.value(),
                "max_tokens": self.max_tokens_spinbox.value(),
                "system_prompt": self.system_prompt_input.toPlainText(),
                "enabled": self.enabled_checkbox.isChecked(),
                "color": self.current_agent_color,
                "include_image": self.include_image_checkbox.isChecked(),
                "desktop_history_enabled": self.desktop_history_checkbox.isChecked(),
                "screenshot_interval": self.screenshot_interval_spinbox.value()
            }
            self.save_agents()
            if self.debug_enabled:
                print(f"[Debug] Saved settings for agent '{agent_name}'.")
        self.update_send_button_state()

    def update_send_button_state(self):
        # Disable send if no enabled agents
        any_enabled = any(a.get("enabled", False) for a in self.agents_data.values() if not a.get("desktop_history_enabled", False))
        self.send_button.setEnabled(any_enabled)

    def save_agents(self):
        try:
            with open(AGENTS_SAVE_FILE, "w") as f:
                json.dump(self.agents_data, f)
            if self.debug_enabled:
                print("[Debug] Agents saved.")
        except Exception as e:
            print(f"[Debug] Failed to save agents: {e}")

    def save_settings(self):
        settings = {
            "debug_enabled": self.debug_enabled,
            "include_image": self.include_image,
            "include_screenshot": self.include_screenshot,
            "image_path": self.image_path_input.text().strip(),
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

    def save_global_preferences(self):
        self.user_name = self.username_input.text().strip() if self.username_input.text().strip() else "You"
        self.save_settings()

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    settings = json.load(f)
                    self.debug_enabled = settings.get("debug_enabled", False)
                    self.include_image = settings.get("include_image", False)
                    self.include_screenshot = settings.get("include_screenshot", False)
                    image_path = settings.get("image_path", "")
                    self.image_path_input.setText(image_path)
                    self.user_name = settings.get("user_name", "You")
                    self.user_color = settings.get("user_color", "#0000FF")
                    self.dark_mode = settings.get("dark_mode", False)

                self.username_input.setText(self.user_name)
                self.user_color_button.setStyleSheet(f"background-color: {self.user_color}")
                self.dark_mode_checkbox.setChecked(self.dark_mode)
                if self.dark_mode:
                    self.apply_dark_mode_style()

                if self.debug_enabled:
                    print("[Debug] Settings loaded.")
            except Exception as e:
                print(f"[Error] Failed to load settings: {e}")

    def select_agent_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.color_button.setStyleSheet(f"background-color: {color.name()}")
            self.current_agent_color = color.name()
            self.save_agent_settings()

    def select_user_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.user_color = color.name()
            self.user_color_button.setStyleSheet(f"background-color: {self.user_color}")
            self.save_global_preferences()

    def handle_ai_response_chunk(self, chunk, agent_name):
        # Accumulate response
        if agent_name not in self.current_responses:
            self.current_responses[agent_name] = ''
        self.current_responses[agent_name] += chunk

    def handle_worker_error(self, error_message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_display.append(f"[{timestamp}] {error_message}")

    def worker_finished_sequential(self, sender_worker, thread, agent_name, index, process_next_agent):
        assistant_content = self.current_responses.get(agent_name, "")
        if agent_name in self.current_responses:
            del self.current_responses[agent_name]

        tool_request = None
        content = assistant_content.strip()

        # Try parsing full content as JSON once
        parsed = None
        if content.startswith("{") and content.endswith("}"):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None

        if parsed and "tool_request" in parsed:
            tool_request = parsed["tool_request"]
            content = parsed.get("content", "").strip()

        timestamp = datetime.now().strftime("%H:%M:%S")
        agent_color = self.agents_data.get(agent_name, {}).get("color", "#000000")

        if tool_request:
            tool_name = tool_request.get("name", "")
            tool_args = tool_request.get("args", {})
            tool_result = run_tool(self.tools, tool_name, tool_args, self.debug_enabled)

            display_message = f"{agent_name} used {tool_name} with args {tool_args}\nTool Result: {tool_result}"
            self.chat_display.append(f"\n[{timestamp}] <span style='color:{agent_color};'>{display_message}</span>")
            self.chat_history.append({"role": "assistant", "content": display_message, "agent": agent_name})
        else:
            final_content = content.strip()
            if final_content:
                self.chat_display.append(f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {final_content}")
                self.chat_history.append({"role": "assistant", "content": final_content, "agent": agent_name})

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

    def browse_image_file(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Image File", "",
                                                   "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)",
                                                   options=options)
        if file_name:
            if self.debug_enabled:
                print(f"[Debug] Selected image: {file_name}")
            self.image_path_input.setText(file_name)
            self.save_settings()

    def update_debug_enabled(self, state):
        self.debug_enabled = (state == Qt.Checked)
        if self.debug_enabled:
            print("[Debug] Debug mode enabled.")
        else:
            print("[Debug] Debug mode disabled.")
        self.save_settings()

    def closeEvent(self, event):
        for worker, thread in self.active_worker_threads:
            thread.quit()
            thread.wait()
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()

        event.accept()
