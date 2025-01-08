# tab_agents.py

import json
from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout, QGroupBox,
    QFormLayout, QCheckBox, QDoubleSpinBox, QSpinBox, QLineEdit, QTextEdit,
    QColorDialog, QMessageBox, QInputDialog
)

AGENTS_SAVE_FILE = "agents.json"

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
        self.parent_app.debug_enabled = (state == Qt.Checked)
        self.parent_app.save_settings()
