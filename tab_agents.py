#tab_agents.py
from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout, QGroupBox,
    QFormLayout, QCheckBox, QDoubleSpinBox, QSpinBox, QLineEdit, QTextEdit,
    QColorDialog, QMessageBox, QInputDialog, QStyle, QListWidget, QAbstractItemView
)

AGENTS_SAVE_FILE = "agents.json"

class AgentsTab(QWidget):
    """
    Allows selecting agents, editing agent-specific settings (model, temperature,
    max tokens, system prompt, color, etc.).
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Agent selection + Add/Delete
        agent_management_layout = QHBoxLayout()
        self.agent_label = QLabel("Select Agent:")
        agent_management_layout.addWidget(self.agent_label)

        self.agent_selector = QComboBox()
        self.agent_selector.setToolTip("Select an agent to modify.")
        agent_management_layout.addWidget(self.agent_selector)

        self.add_agent_button = QPushButton("Add Agent")
        self.add_agent_button.setToolTip("Add a new agent.")
        self.add_agent_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileIcon')))  # Add icon
        agent_management_layout.addWidget(self.add_agent_button)

        self.delete_agent_button = QPushButton("Delete Agent")
        self.delete_agent_button.setToolTip("Delete the selected agent.")
        self.delete_agent_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_TrashIcon')))  # Add icon
        agent_management_layout.addWidget(self.delete_agent_button)

        self.layout.addLayout(agent_management_layout)

        # --- Agent Settings Section ---
        self.agent_settings_group = QGroupBox("Agent Settings")
        self.agent_settings_layout = QFormLayout()
        self.agent_settings_group.setLayout(self.agent_settings_layout)
        self.layout.addWidget(self.agent_settings_group)

        # --- Role ---
        self.role_label = QLabel("Role:")
        self.role_selector = QComboBox()
        self.role_selector.addItems(["Coordinator", "Assistant", "Specialist"])
        self.role_selector.setToolTip("Select the role for this agent.")
        self.agent_settings_layout.addRow(self.role_label, self.role_selector)

        # --- Managed Agents (for Coordinators only) ---
        self.managed_agents_label = QLabel("Managed Agents:")
        self.managed_agents_list = QListWidget()
        self.managed_agents_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.managed_agents_list.setToolTip(
            "Select the agents this Coordinator will manage."
        )
        self.agent_settings_layout.addRow(self.managed_agents_label, self.managed_agents_list)

        # --- Description (for Coordinators only) ---
        self.description_label = QLabel("Description:")
        self.description_input = QTextEdit()
        self.description_input.setFixedHeight(60)
        self.description_input.setToolTip("Enter a description of this agent's capabilities.")
        self.agent_settings_layout.addRow(self.description_label, self.description_input)

        # --- Model Settings Sub-section ---
        self.model_settings_group = QGroupBox("Model Settings")
        self.model_settings_layout = QFormLayout()
        self.model_settings_group.setLayout(self.model_settings_layout)
        self.agent_settings_layout.addRow(self.model_settings_group)

        self.model_name_label = QLabel("Model Name:")
        self.model_name_input = QLineEdit()
        self.model_name_input.setToolTip("Enter the model name for the agent.")
        self.model_settings_layout.addRow(self.model_name_label, self.model_name_input)

        self.temperature_label = QLabel("Temperature:")
        self.temperature_spinbox = QDoubleSpinBox()
        self.temperature_spinbox.setRange(0.0, 1.0)
        self.temperature_spinbox.setSingleStep(0.1)
        self.temperature_spinbox.setValue(0.7)
        self.temperature_spinbox.setToolTip("Set the temperature for the agent (0.0 - 1.0).")
        self.model_settings_layout.addRow(self.temperature_label, self.temperature_spinbox)

        self.max_tokens_label = QLabel("Max Tokens:")
        self.max_tokens_spinbox = QSpinBox()
        self.max_tokens_spinbox.setRange(1, 4096)
        self.max_tokens_spinbox.setValue(512)
        self.max_tokens_spinbox.setToolTip("Set the maximum number of tokens for the agent.")
        self.model_settings_layout.addRow(self.max_tokens_label, self.max_tokens_spinbox)

        # --- Prompt Settings Sub-section ---
        self.prompt_settings_group = QGroupBox("Prompt Settings")
        self.prompt_settings_layout = QFormLayout()
        self.prompt_settings_group.setLayout(self.prompt_settings_layout)
        self.agent_settings_layout.addRow(self.prompt_settings_group)

        self.system_prompt_label = QLabel("Custom System Prompt:")
        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setFixedHeight(60)
        self.system_prompt_input.setToolTip("Enter a custom system prompt for the agent.")
        self.prompt_settings_layout.addRow(self.system_prompt_label, self.system_prompt_input)

        # --- Other Settings ---
        self.enabled_checkbox = QCheckBox("Enable Agent")
        self.enabled_checkbox.setToolTip("Enable or disable this agent.")
        self.agent_settings_layout.addRow(self.enabled_checkbox)

        self.color_label = QLabel("Agent Color:")
        self.color_button = QPushButton()
        self.color_button.setToolTip("Select a color for the agent.")
        self.color_button.setStyleSheet("background-color: black")
        self.agent_settings_layout.addRow(self.color_label, self.color_button)

        # --- Tool Use Settings Sub-section ---
        self.tool_settings_group = QGroupBox("Tool Settings")
        self.tool_settings_layout = QFormLayout()
        self.tool_settings_group.setLayout(self.tool_settings_layout)
        self.agent_settings_layout.addRow(self.tool_settings_group)

        self.tool_use_checkbox = QCheckBox("Enable Tool Use")
        self.tool_use_checkbox.setToolTip("Allow this agent to use tools.")
        self.tool_settings_layout.addRow(self.tool_use_checkbox)

        self.tools_label = QLabel("Enabled Tools:")
        self.tools_list = QListWidget()
        self.tools_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.tools_list.setToolTip("Select the tools this agent can use.")
        
        # Set items to checkable
        for i in range(self.tools_list.count()):
            item = self.tools_list.item(i)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)  # Default unchecked
        
        self.tool_settings_layout.addRow(self.tools_label, self.tools_list)

        # --- Desktop History Settings Sub-section ---
        self.desktop_history_group = QGroupBox("Desktop History Settings")
        self.desktop_history_layout = QFormLayout()
        self.desktop_history_group.setLayout(self.desktop_history_layout)
        self.agent_settings_layout.addRow(self.desktop_history_group)

        self.desktop_history_checkbox = QCheckBox("Enable Desktop History")
        self.desktop_history_checkbox.setToolTip("Enable desktop history for this agent.")
        self.desktop_history_layout.addRow(self.desktop_history_checkbox)

        self.screenshot_interval_label = QLabel("Screenshot Interval (seconds):")
        self.screenshot_interval_spinbox = QSpinBox()
        self.screenshot_interval_spinbox.setRange(1, 3600)
        self.screenshot_interval_spinbox.setValue(5)
        self.screenshot_interval_spinbox.setToolTip("Set the screenshot interval for desktop history.")
        self.desktop_history_layout.addRow(self.screenshot_interval_label, self.screenshot_interval_spinbox)

        # --- Signals ---
        self.agent_selector.currentIndexChanged.connect(self.on_agent_selected)
        self.add_agent_button.clicked.connect(self.parent_app.add_agent)
        self.delete_agent_button.clicked.connect(self.parent_app.delete_agent)
        self.role_selector.currentIndexChanged.connect(self.update_ui_for_role)

        self.enabled_checkbox.stateChanged.connect(self.save_agent_settings)
        self.desktop_history_checkbox.stateChanged.connect(self.save_agent_settings)

        self.temperature_spinbox.valueChanged.connect(self.save_agent_settings)
        self.max_tokens_spinbox.valueChanged.connect(self.save_agent_settings)
        self.model_name_input.textChanged.connect(self.save_agent_settings)
        self.system_prompt_input.textChanged.connect(self.save_agent_settings)
        self.screenshot_interval_spinbox.valueChanged.connect(self.save_agent_settings)
        self.tool_use_checkbox.stateChanged.connect(self.update_ui_for_role)
        self.tool_use_checkbox.stateChanged.connect(self.save_agent_settings)

        self.color_button.clicked.connect(self.select_agent_color)
        
        self.tools_list.itemChanged.connect(self.save_agent_settings)

        # Hide elements initially
        self.managed_agents_label.hide()
        self.managed_agents_list.hide()
        self.description_label.hide()
        self.description_input.hide()
        self.tools_label.hide()
        self.tools_list.hide()

    # ------------------ Agent Helpers -----------------------
    def on_agent_selected(self, index):
        agent_name = self.agent_selector.currentText()
        if agent_name in self.parent_app.agents_data:
            self.load_agent_settings(agent_name)

    def load_agent_settings(self, agent_name):
        agent_settings = self.parent_app.agents_data.get(agent_name, {})
        
        self.role_selector.blockSignals(True)
        self.managed_agents_list.blockSignals(True)
        self.description_input.blockSignals(True)
        self.temperature_spinbox.blockSignals(True)
        self.max_tokens_spinbox.blockSignals(True)
        self.system_prompt_input.blockSignals(True)
        self.model_name_input.blockSignals(True)
        self.enabled_checkbox.blockSignals(True)
        self.desktop_history_checkbox.blockSignals(True)
        self.screenshot_interval_spinbox.blockSignals(True)
        self.color_button.blockSignals(True)
        self.tool_use_checkbox.blockSignals(True)
        self.tools_list.blockSignals(True)

        # Load settings
        self.role_selector.setCurrentText(agent_settings.get("role", "Assistant"))
        self.description_input.setText(agent_settings.get("description", ""))
        self.temperature_spinbox.setValue(agent_settings.get("temperature", 0.7))
        self.max_tokens_spinbox.setValue(agent_settings.get("max_tokens", 512))
        self.system_prompt_input.setText(agent_settings.get("system_prompt", ""))
        self.model_name_input.setText(agent_settings.get("model", "llama3.2-vision"))
        self.enabled_checkbox.setChecked(agent_settings.get("enabled", False))
        self.desktop_history_checkbox.setChecked(agent_settings.get("desktop_history_enabled", False))
        self.screenshot_interval_spinbox.setValue(agent_settings.get("screenshot_interval", 5))
        self.tool_use_checkbox.setChecked(agent_settings.get("tool_use", False))

        color = agent_settings.get("color", "#000000")
        self.color_button.setStyleSheet(f"background-color: {color}")

        # Update managed agents list
        self.managed_agents_list.clear()
        all_agents = [
            a for a in self.parent_app.agents_data.keys() if a != agent_name
        ]
        self.managed_agents_list.addItems(all_agents)
        for i in range(self.managed_agents_list.count()):
            item = self.managed_agents_list.item(i)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)

        # Check managed agents
        managed_agents = agent_settings.get("managed_agents", [])
        for i in range(self.managed_agents_list.count()):
            item = self.managed_agents_list.item(i)
            if item.text() in managed_agents:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
        
        # Update tools list
        self.tools_list.clear()
        all_tools = [tool['name'] for tool in self.parent_app.tools]
        self.tools_list.addItems(all_tools)
        
        # Check enabled tools
        enabled_tools = agent_settings.get("tools_enabled", [])
        for i in range(self.tools_list.count()):
            item = self.tools_list.item(i)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if item.text() in enabled_tools:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)

        self.update_ui_for_role()
        
        self.role_selector.blockSignals(False)
        self.managed_agents_list.blockSignals(False)
        self.description_input.blockSignals(False)
        self.temperature_spinbox.blockSignals(False)
        self.max_tokens_spinbox.blockSignals(False)
        self.system_prompt_input.blockSignals(False)
        self.model_name_input.blockSignals(False)
        self.enabled_checkbox.blockSignals(False)
        self.desktop_history_checkbox.blockSignals(False)
        self.screenshot_interval_spinbox.blockSignals(False)
        self.color_button.blockSignals(False)
        self.tool_use_checkbox.blockSignals(False)
        self.tools_list.blockSignals(False)

    def update_ui_for_role(self):
        current_role = self.role_selector.currentText()
        is_coordinator = current_role == "Coordinator"

        self.managed_agents_label.setVisible(is_coordinator)
        self.managed_agents_list.setVisible(is_coordinator)
        self.description_label.setVisible(is_coordinator)
        self.description_input.setVisible(is_coordinator)

        # Only show for non-coordinator roles
        self.desktop_history_group.setVisible(current_role != "Coordinator")

        # Only show tool settings if tool use is enabled
        self.tools_label.setVisible(self.tool_use_checkbox.isChecked())
        self.tools_list.setVisible(self.tool_use_checkbox.isChecked())

        self.save_agent_settings()  # Save settings whenever the role changes


    def save_agent_settings(self):
        agent_name = self.agent_selector.currentText()
        if agent_name:
            # Collect managed agents
            managed_agents = [
                self.managed_agents_list.item(i).text()
                for i in range(self.managed_agents_list.count())
                if self.managed_agents_list.item(i).checkState() == Qt.Checked
            ]

            # Collect enabled tools
            enabled_tools = [
                self.tools_list.item(i).text()
                for i in range(self.tools_list.count())
                if self.tools_list.item(i).checkState() == Qt.Checked
            ]

            self.parent_app.agents_data[agent_name] = {
                "model": self.model_name_input.text().strip(),
                "temperature": self.temperature_spinbox.value(),
                "max_tokens": self.max_tokens_spinbox.value(),
                "system_prompt": self.system_prompt_input.toPlainText(),
                "enabled": self.enabled_checkbox.isChecked(),
                "color": self.parent_app.agents_data.get(agent_name, {}).get("color", "#000000"),
                "desktop_history_enabled": self.desktop_history_checkbox.isChecked(),
                "screenshot_interval": self.screenshot_interval_spinbox.value(),
                "role": self.role_selector.currentText(),
                "description": self.description_input.toPlainText(),
                "managed_agents": managed_agents,
                "tool_use": self.tool_use_checkbox.isChecked(),
                "tools_enabled": enabled_tools
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
                
    def load_global_preferences(self):
        self.parent_app.user_name = self.parent_app.user_name
        self.parent_app.user_color = self.parent_app.user_color
        self.parent_app.dark_mode = self.parent_app.dark_mode