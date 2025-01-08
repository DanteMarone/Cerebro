#tab_agents.py
from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout, QGroupBox,
    QFormLayout, QCheckBox, QDoubleSpinBox, QSpinBox, QLineEdit, QTextEdit,
    QColorDialog, QMessageBox, QInputDialog, QStyle  # Import QStyle here
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

        self.enabled_checkbox.stateChanged.connect(self.save_agent_settings)
        self.desktop_history_checkbox.stateChanged.connect(self.save_agent_settings)

        self.temperature_spinbox.valueChanged.connect(self.save_agent_settings)
        self.max_tokens_spinbox.valueChanged.connect(self.save_agent_settings)
        self.model_name_input.textChanged.connect(self.save_agent_settings)
        self.system_prompt_input.textChanged.connect(self.save_agent_settings)
        self.screenshot_interval_spinbox.valueChanged.connect(self.save_agent_settings)

        self.color_button.clicked.connect(self.select_agent_color)

    # ------------------ Agent Helpers -----------------------
    def on_agent_selected(self, index):
        agent_name = self.agent_selector.currentText()
        if agent_name in self.parent_app.agents_data:
            self.load_agent_settings(agent_name)

    def load_agent_settings(self, agent_name):
        agent_settings = self.parent_app.agents_data.get(agent_name, {})
        self.temperature_spinbox.blockSignals(True)
        self.max_tokens_spinbox.blockSignals(True)
        self.system_prompt_input.blockSignals(True)
        self.model_name_input.blockSignals(True)
        self.enabled_checkbox.blockSignals(True)
        self.desktop_history_checkbox.blockSignals(True)
        self.screenshot_interval_spinbox.blockSignals(True)

        self.temperature_spinbox.setValue(agent_settings.get("temperature", 0.7))
        self.max_tokens_spinbox.setValue(agent_settings.get("max_tokens", 512))
        self.system_prompt_input.setText(agent_settings.get("system_prompt", ""))
        self.model_name_input.setText(agent_settings.get("model", "llama3.2-vision"))
        self.enabled_checkbox.setChecked(agent_settings.get("enabled", False))
        self.desktop_history_checkbox.setChecked(agent_settings.get("desktop_history_enabled", False))
        self.screenshot_interval_spinbox.setValue(agent_settings.get("screenshot_interval", 5))

        color = agent_settings.get("color", "#000000")
        self.color_button.setStyleSheet(f"background-color: {color}")

        self.temperature_spinbox.blockSignals(False)
        self.max_tokens_spinbox.blockSignals(False)
        self.system_prompt_input.blockSignals(False)
        self.model_name_input.blockSignals(False)
        self.enabled_checkbox.blockSignals(False)
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
                
    def load_global_preferences(self):
        self.parent_app.user_name = self.parent_app.user_name
        self.parent_app.user_color = self.parent_app.user_color
        self.parent_app.dark_mode = self.parent_app.dark_mode