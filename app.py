# app.py

import json
import os
import re
import base64
from datetime import datetime

from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QThread
from PyQt5.QtGui import QTextCursor, QColor
from PyQt5.QtWidgets import (
    QMainWindow, QVBoxLayout, QWidget, QTextEdit, QPushButton, QTabWidget,
    QMessageBox, QComboBox, QLabel, QSpinBox, QDoubleSpinBox, QGroupBox, QFormLayout,
    QCheckBox, QHBoxLayout, QFileDialog, QLineEdit, QColorDialog, QDialog,
    QListWidget, QListWidgetItem, QInputDialog
)

from worker import AIWorker
from tools import load_tools, run_tool, add_tool, edit_tool, delete_tool
from tasks import load_tasks, save_tasks, add_task, edit_task, delete_task

AGENTS_SAVE_FILE = "agents.json"
SETTINGS_FILE = "settings.json"

###############################################################################
# Tab: Chat
###############################################################################
class ChatTab(QWidget):
    """
    Encapsulates the chat UI: display, input, send/clear buttons.
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Chat display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.layout.addWidget(self.chat_display)

        # Input area
        self.user_input = QTextEdit()
        self.user_input.setPlaceholderText("Type your message here...")
        self.user_input.setMaximumHeight(100)
        self.user_input.installEventFilter(self)
        self.layout.addWidget(self.user_input)

        # Button row
        btn_layout = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.clear_chat_button = QPushButton("Clear Chat")
        btn_layout.addWidget(self.send_button)
        btn_layout.addWidget(self.clear_chat_button)
        self.layout.addLayout(btn_layout)

        # Wire up signals
        self.send_button.clicked.connect(self.on_send_clicked)
        self.clear_chat_button.clicked.connect(self.on_clear_chat_clicked)
        self.user_input.textChanged.connect(self.adjust_input_height)

    def eventFilter(self, obj, event):
        """
        Capture Enter key in user_input for sending.
        """
        if obj == self.user_input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Return and not event.modifiers() & QtCore.Qt.ShiftModifier:
                self.on_send_clicked()
                return True
        return super().eventFilter(obj, event)

    def adjust_input_height(self):
        doc_height = self.user_input.document().size().height()
        new_height = int(doc_height + 10)
        self.user_input.setFixedHeight(min(new_height, 100))

    def on_send_clicked(self):
        """
        Send message to the AIChatApp logic.
        """
        user_text = self.user_input.toPlainText().strip()
        if not user_text:
            return
        self.user_input.clear()
        self.user_input.setFixedHeight(30)
        self.parent_app.send_message(user_text)

    def on_clear_chat_clicked(self):
        """
        Clear the chat display and the parent app's history.
        """
        self.parent_app.clear_chat()

    def append_message_html(self, html_text):
        """
        Append a new message (in HTML) to the chat display.
        """
        self.chat_display.append(html_text)

###############################################################################
# Tab: Agents
###############################################################################
class AgentsTab(QWidget):
    """
    Allows selecting agents, editing agent-specific settings (model, temperature,
    max tokens, system prompt, color, etc.), and global preferences in a sub-section.
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Agent selection + Add/Delete
        self.agent_selector_layout = QHBoxLayout()
        self.agent_label = QLabel("Select Agent:")
        self.agent_selector_layout.addWidget(self.agent_label)

        self.agent_selector = QComboBox()
        self.agent_selector_layout.addWidget(self.agent_selector)

        self.add_agent_button = QPushButton("Add Agent")
        self.agent_selector_layout.addWidget(self.add_agent_button)

        self.delete_agent_button = QPushButton("Delete Agent")
        self.agent_selector_layout.addWidget(self.delete_agent_button)

        self.layout.addLayout(self.agent_selector_layout)

        # --- Advanced Options Section ---
        self.advanced_options_group = QGroupBox("Agent Settings")
        self.advanced_options_layout = QFormLayout()
        self.advanced_options_group.setLayout(self.advanced_options_layout)
        self.layout.addWidget(self.advanced_options_group)

        self.enabled_checkbox = QCheckBox("Enable Agent")
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
        self.advanced_options_layout.addRow(self.debug_checkbox)

        self.include_image_checkbox = QCheckBox("Include Image (Manual)")
        self.advanced_options_layout.addRow(self.include_image_checkbox)

        self.desktop_history_checkbox = QCheckBox("Enable Desktop History")
        self.advanced_options_layout.addRow(self.desktop_history_checkbox)

        self.screenshot_interval_label = QLabel("Screenshot Interval (seconds):")
        self.screenshot_interval_spinbox = QSpinBox()
        self.screenshot_interval_spinbox.setRange(1, 3600)
        self.screenshot_interval_spinbox.setValue(5)
        self.advanced_options_layout.addRow(self.screenshot_interval_label, self.screenshot_interval_spinbox)

        self.system_prompt_label = QLabel("Custom System Prompt:")
        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setFixedHeight(60)
        self.advanced_options_layout.addRow(self.system_prompt_label, self.system_prompt_input)

        self.color_label = QLabel("Agent Color:")
        self.color_button = QPushButton()
        self.color_button.setStyleSheet("background-color: black")
        self.advanced_options_layout.addRow(self.color_label, self.color_button)

        # --- Global Preferences Section ---
        self.global_preferences_group = QGroupBox("Global Preferences")
        self.global_preferences_layout = QFormLayout()
        self.global_preferences_group.setLayout(self.global_preferences_layout)
        self.layout.addWidget(self.global_preferences_group)

        self.username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        self.global_preferences_layout.addRow(self.username_label, self.username_input)

        self.user_color_label = QLabel("User Color:")
        self.user_color_button = QPushButton()
        self.user_color_button.setStyleSheet(f"background-color: {self.parent_app.user_color}")
        self.global_preferences_layout.addRow(self.user_color_label, self.user_color_button)

        self.dark_mode_checkbox = QCheckBox("Dark Mode")
        self.global_preferences_layout.addRow(self.dark_mode_checkbox)

        # --- Signals ---
        self.agent_selector.currentIndexChanged.connect(self.on_agent_selected)
        self.add_agent_button.clicked.connect(self.parent_app.add_agent)
        self.delete_agent_button.clicked.connect(self.parent_app.delete_agent)

        self.enabled_checkbox.stateChanged.connect(self.save_agent_settings)
        self.debug_checkbox.stateChanged.connect(self.update_debug_enabled)
        self.include_image_checkbox.stateChanged.connect(self.save_agent_settings)
        self.desktop_history_checkbox.stateChanged.connect(self.save_agent_settings)

        self.temperature_spinbox.valueChanged.connect(self.save_agent_settings)
        self.max_tokens_spinbox.valueChanged.connect(self.save_agent_settings)
        self.model_name_input.textChanged.connect(self.save_agent_settings)
        self.system_prompt_input.textChanged.connect(self.save_agent_settings)
        self.screenshot_interval_spinbox.valueChanged.connect(self.save_agent_settings)

        self.color_button.clicked.connect(self.select_agent_color)

        self.username_input.textChanged.connect(self.save_global_preferences)
        self.user_color_button.clicked.connect(self.select_user_color)
        self.dark_mode_checkbox.stateChanged.connect(self.toggle_dark_mode)

    # ------------------ Global Prefs Helpers -----------------------
    def save_global_preferences(self):
        self.parent_app.user_name = self.username_input.text().strip() or "You"
        self.parent_app.save_settings()

    def select_user_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.parent_app.user_color = color.name()
            self.user_color_button.setStyleSheet(f"background-color: {self.parent_app.user_color}")
            self.parent_app.save_settings()

    def toggle_dark_mode(self, state):
        self.parent_app.dark_mode = (state == Qt.Checked)
        self.parent_app.save_settings()
        if self.parent_app.dark_mode:
            self.parent_app.apply_dark_mode_style()
        else:
            self.parent_app.apply_light_mode_style()

    # ------------------ Agent Helpers -----------------------
    def on_agent_selected(self, index):
        agent_name = self.agent_selector.currentText()
        if agent_name in self.parent_app.agents_data:
            self.load_agent_settings(agent_name)

    def load_agent_settings(self, agent_name):
        agent_settings = self.parent_app.agents_data.get(agent_name, {})
        # Block signals so we don't trigger save repeatedly
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
        self.debug_checkbox.setChecked(self.parent_app.debug_enabled)
        self.include_image_checkbox.setChecked(agent_settings.get("include_image", False))
        self.desktop_history_checkbox.setChecked(agent_settings.get("desktop_history_enabled", False))
        self.screenshot_interval_spinbox.setValue(agent_settings.get("screenshot_interval", 5))

        color = agent_settings.get("color", "#000000")
        self.color_button.setStyleSheet(f"background-color: {color}")

        # Unblock signals
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
            self.parent_app.agents_data[agent_name] = {
                "model": self.model_name_input.text().strip(),
                "temperature": self.temperature_spinbox.value(),
                "max_tokens": self.max_tokens_spinbox.value(),
                "system_prompt": self.system_prompt_input.toPlainText(),
                "enabled": self.enabled_checkbox.isChecked(),
                "color": self.parent_app.agents_data.get(agent_name, {}).get("color", "#000000"),
                "include_image": self.include_image_checkbox.isChecked(),
                "desktop_history_enabled": self.desktop_history_checkbox.isChecked(),
                "screenshot_interval": self.screenshot_interval_spinbox.value()
            }
            self.parent_app.save_agents()
            self.parent_app.update_send_button_state()

    def select_agent_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            agent_name = self.agent_selector.currentText()
            if agent_name:
                self.parent_app.agents_data[agent_name]["color"] = color.name()
                self.color_button.setStyleSheet(f"background-color: {color.name()}")
                self.save_agent_settings()

    def update_debug_enabled(self, state):
        # Toggles global debug in the parent app
        self.parent_app.debug_enabled = (state == Qt.Checked)
        self.parent_app.save_settings()

###############################################################################
# Tab: Tools
###############################################################################
class ToolsTab(QWidget):
    """
    Integrated version of Tools management (previously ToolsWindow).
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.tools = self.parent_app.tools
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Tools List
        self.tools_list = QListWidget()
        self.layout.addWidget(self.tools_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Tool")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        # Connect signals
        self.add_button.clicked.connect(self.add_tool_ui)

        self.refresh_tools_list()

    def refresh_tools_list(self):
        self.tools_list.clear()
        for t in self.tools:
            item = QListWidgetItem()
            item.setText(f"{t['name']}: {t['description']}")
            self.tools_list.addItem(item)

            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(f"{t['name']}: {t['description']}")
            edit_btn = QPushButton("Edit")
            del_btn = QPushButton("Delete")

            # We have to capture the tool name carefully in lambdas
            edit_btn.clicked.connect(lambda _, tn=t['name']: self.edit_tool_ui(tn))
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
            err = add_tool(self.tools, name, desc, script, self.parent_app.debug_enabled)
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
            err = edit_tool(self.tools, tool["name"], new_name, desc, script, self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Editing Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()

    def delete_tool_ui(self, tool_name):
        reply = QMessageBox.question(
            self, 'Confirm Delete',
            f"Are you sure you want to delete the tool '{tool_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            err = delete_tool(self.tools, tool_name, self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Deleting Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()

###############################################################################
# Dialog: ToolDialog (Used by ToolsTab)
###############################################################################
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
        return (
            self.name_edit.text().strip(),
            self.description_edit.text().strip(),
            self.script_edit.toPlainText().strip()
        )

###############################################################################
# Tab: Tasks
###############################################################################
class TasksTab(QWidget):
    """
    Integrated version of Tasks management (previously TasksWindow).
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.tasks = self.parent_app.tasks
        self.agents_data = self.parent_app.agents_data

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Tasks list
        self.tasks_list = QListWidget()
        self.layout.addWidget(self.tasks_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Task")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        self.add_button.clicked.connect(self.add_task_ui)

        self.refresh_tasks_list()

    def refresh_tasks_list(self):
        self.tasks_list.clear()
        for t in self.tasks:
            item = QListWidgetItem()
            due_time = t.get("due_time", "")
            agent_name = t.get("agent_name", "")
            prompt = t.get("prompt", "")
            summary = f"[{due_time}] {agent_name} - {prompt[:30]}..."
            item.setText(summary)
            self.tasks_list.addItem(item)

            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(summary)
            edit_btn = QPushButton("Edit")
            del_btn = QPushButton("Delete")

            edit_btn.clicked.connect(lambda _, tid=t['id']: self.edit_task_ui(tid))
            del_btn.clicked.connect(lambda _, tid=t['id']: self.delete_task_ui(tid))

            h_layout.addWidget(label)
            h_layout.addWidget(edit_btn)
            h_layout.addWidget(del_btn)
            container.setLayout(h_layout)

            self.tasks_list.setItemWidget(item, container)

    def add_task_ui(self):
        dialog = TaskDialog(self, self.agents_data)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            agent_name = data["agent_name"]
            prompt = data["prompt"]
            due_time = data["due_time"]
            if not due_time:
                QMessageBox.warning(self, "Error", "Please specify a valid due time.")
                return
            add_task(self.tasks, agent_name, prompt, due_time, creator="user", debug_enabled=self.parent_app.debug_enabled)
            self.refresh_tasks_list()

    def edit_task_ui(self, task_id):
        existing_task = next((t for t in self.tasks if t["id"] == task_id), None)
        if not existing_task:
            QMessageBox.warning(self, "Error", f"No task with ID {task_id} found.")
            return
        dialog = TaskDialog(
            self,
            self.agents_data,
            task_id=task_id,
            agent_name=existing_task.get("agent_name", ""),
            prompt=existing_task.get("prompt", ""),
            due_time=existing_task.get("due_time", "")
        )
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            err = edit_task(
                self.tasks,
                task_id,
                data["agent_name"],
                data["prompt"],
                data["due_time"],
                debug_enabled=self.parent_app.debug_enabled
            )
            if err:
                QMessageBox.warning(self, "Error Editing Task", err)
            else:
                self.refresh_tasks_list()

    def delete_task_ui(self, task_id):
        reply = QMessageBox.question(
            self, 'Confirm Delete',
            "Are you sure you want to delete this task?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            err = delete_task(self.tasks, task_id, debug_enabled=self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Deleting Task", err)
            else:
                self.refresh_tasks_list()

###############################################################################
# Dialog: TaskDialog
###############################################################################
class TaskDialog(QDialog):
    """
    A dialog to create or edit a task.
    """
    def __init__(self, parent, agents_data, task_id=None, agent_name="", prompt="", due_time=""):
        super().__init__(parent)
        self.setWindowTitle("Add/Edit Task")
        self.agents_data = agents_data
        self.task_id = task_id

        layout = QVBoxLayout(self)

        # Agent selection
        self.agent_selector = QComboBox()
        for a_name in self.agents_data.keys():
            self.agent_selector.addItem(a_name)
        if agent_name in self.agents_data:
            self.agent_selector.setCurrentText(agent_name)

        # Prompt
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(prompt)

        # Due time
        self.due_time_edit = QLineEdit()
        self.due_time_edit.setText(due_time)
        self.due_time_label = QLabel("Due Time (YYYY-MM-DD HH:MM:SS or ISO8601):")

        layout.addWidget(QLabel("Agent:"))
        layout.addWidget(self.agent_selector)
        layout.addWidget(QLabel("Prompt:"))
        layout.addWidget(self.prompt_edit)
        layout.addWidget(self.due_time_label)
        layout.addWidget(self.due_time_edit)

        btn_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_button)
        btn_layout.addWidget(self.cancel_button)

        layout.addLayout(btn_layout)

    def get_data(self):
        return {
            "agent_name": self.agent_selector.currentText(),
            "prompt": self.prompt_edit.toPlainText().strip(),
            "due_time": self.due_time_edit.text().strip()
        }

###############################################################################
# Main Application Window
###############################################################################
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
        # Global toggles
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
        # Display in chat
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_message_html = f'<span style="color:{self.user_color};">[{timestamp}] {self.user_name}:</span> {user_text}'
        self.chat_tab.append_message_html(user_message_html)

        user_message = {"role": "user", "content": user_text}
        self.chat_history.append(user_message)

        # Check if at least one non-DH agent is enabled
        enabled_agents = [
            (agent_name, agent_settings)
            for agent_name, agent_settings in self.agents_data.items()
            if agent_settings.get('enabled', False) and not agent_settings.get('desktop_history_enabled', False)
        ]
        if not enabled_agents:
            QMessageBox.warning(self, "No Agents Enabled", "Please enable at least one non-DH agent.")
            return

        # Process each enabled agent in sequence
        def process_next_agent(index):
            if index is None or index >= len(enabled_agents):
                return

            agent_name, agent_settings = enabled_agents[index]
            if self.debug_enabled:
                print(f"[Debug] Processing agent: {agent_name}")

            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            if not model_name:
                QMessageBox.warning(self, "Invalid Model Name", f"Agent '{agent_name}' has no valid model name.")
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
                self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {final_content}")
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

        # Populate agent_selector in AgentsTab
        self.agents_tab.agent_selector.clear()
        for agent_name in self.agents_data.keys():
            self.agents_tab.agent_selector.addItem(agent_name)

        if self.agents_tab.agent_selector.count() > 0:
            self.agents_tab.load_agent_settings(self.agents_tab.agent_selector.currentText())

    def add_agent(self):
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
        # Called after agent changes to see if there's any enabled agent
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
        # Re-load from file, then refresh tab UI
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

        # Filter existing chat
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
            "image_path": "",  # Moved to agent-level config now
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

        # Now update AgentsTab global preferences
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
