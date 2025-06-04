#tab_agents.py
from datetime import datetime
import os
import json
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton,
    QHBoxLayout, QComboBox, QFrame, QLineEdit, QTextEdit, QCheckBox,
    QColorDialog, QFormLayout, QGroupBox, QDoubleSpinBox, QSpinBox,
    QListWidget, QListWidgetItem, QMessageBox # Make sure QListWidgetItem is here
)
from PyQt5.QtCore import Qt

class AgentsTab(QWidget):
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        
        self.init_ui()
        self.global_agent_preferences = {}
        self.load_global_preferences()

    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Agent selector
        selector_layout = QHBoxLayout()
        self.agent_selector = QComboBox()
        self.agent_selector.setToolTip("Select an agent to configure.")
        self.agent_selector.currentIndexChanged.connect(self.on_agent_selected)
        selector_layout.addWidget(QLabel("Current Agent:"))
        selector_layout.addWidget(self.agent_selector, 1)
        
        # Add/Delete buttons
        add_agent_btn = QPushButton("Add New Agent")
        add_agent_btn.setToolTip("Create a new agent.")
        add_agent_btn.clicked.connect(self.parent_app.add_agent)
        
        delete_agent_btn = QPushButton("Delete Agent")
        delete_agent_btn.setToolTip("Delete the selected agent.")
        delete_agent_btn.clicked.connect(self.on_delete_agent_clicked)
        
        button_layout = QHBoxLayout()
        button_layout.addWidget(add_agent_btn)
        button_layout.addWidget(delete_agent_btn)
        
        layout.addLayout(selector_layout)
        layout.addLayout(button_layout)
        
        # Add a separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)
        
        # Agent settings form
        self.agent_settings_layout = QFormLayout()
        
        # --- Basic Settings ---
        self.model_label = QLabel("Model:")
        self.model_input = QLineEdit()
        self.model_input.setToolTip("Enter the model name to use for this agent.")
        self.agent_settings_layout.addRow(self.model_label, self.model_input)
        
        # --- Prompt Settings Group ---
        self.prompt_settings_group = QGroupBox("Prompt Settings")
        self.prompt_settings_layout = QFormLayout()
        self.prompt_settings_group.setLayout(self.prompt_settings_layout)
        
        # Temperature setting
        self.temperature_label = QLabel("Temperature:")
        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setMinimum(0.0)
        self.temperature_input.setMaximum(1.0)
        self.temperature_input.setSingleStep(0.1)
        self.temperature_input.setToolTip("Controls randomness. Lower values produce more predictable outputs.")
        self.prompt_settings_layout.addRow(self.temperature_label, self.temperature_input)
        
        # Max tokens setting
        self.max_tokens_label = QLabel("Max Tokens:")
        self.max_tokens_input = QSpinBox()
        self.max_tokens_input.setMinimum(1)
        self.max_tokens_input.setMaximum(8192)
        self.max_tokens_input.setToolTip("Maximum number of tokens in the response.")
        self.prompt_settings_layout.addRow(self.max_tokens_label, self.max_tokens_input)
        
        self.agent_settings_layout.addRow(self.prompt_settings_group)

        self.system_prompt_label = QLabel("Custom System Prompt:")
        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setMinimumHeight(150)
        self.system_prompt_input.setObjectName("systemPromptInput")
        self.system_prompt_input.setToolTip("Enter a custom system prompt for the agent.")
        self.prompt_settings_layout.addRow(self.system_prompt_label, self.system_prompt_input)

        # --- Other Settings ---
        self.enabled_checkbox = QCheckBox("Enable Agent")
        self.enabled_checkbox.setToolTip("Enable or disable this agent.")
        self.agent_settings_layout.addRow("", self.enabled_checkbox)
        
        # Agent role
        self.role_label = QLabel("Agent Role:")
        self.role_combo = QComboBox()
        self.role_combo.addItems(["Assistant", "Coordinator", "Specialist"])
        self.role_combo.setToolTip("Select the role for this agent.")
        self.agent_settings_layout.addRow(self.role_label, self.role_combo)
        
        # Agent description
        self.description_label = QLabel("Description:")
        self.description_input = QLineEdit()
        self.description_input.setToolTip("Brief description of this agent's capabilities.")
        self.agent_settings_layout.addRow(self.description_label, self.description_input)
        
        # Color picker
        self.color_label = QLabel("Agent Color:")
        self.color_button = QPushButton()
        self.color_button.setToolTip("Select a color for this agent's messages.")
        self.color_button.setFixedWidth(80)
        self.color_button.clicked.connect(self.on_color_button_clicked)
        self.agent_settings_layout.addRow(self.color_label, self.color_button)
        
        # Managed agents (for Coordinator role)
        self.managed_agents_label = QLabel("Managed Agents:")
        self.managed_agents_list = QListWidget()
        self.managed_agents_list.setToolTip("Select agents that this Coordinator can manage.")
        self.managed_agents_list.setSelectionMode(QListWidget.MultiSelection)
        self.agent_settings_layout.addRow(self.managed_agents_label, self.managed_agents_list)
        
        # Tool use
        self.tool_use_checkbox = QCheckBox("Enable Tool Use")
        self.tool_use_checkbox.setToolTip("Allow this agent to use tools.")
        self.agent_settings_layout.addRow("", self.tool_use_checkbox)

        # Task scheduling permission
        self.schedule_tasks_checkbox = QCheckBox("Allow Task Scheduling")
        self.schedule_tasks_checkbox.setToolTip("Permit this agent to schedule tasks.")
        self.agent_settings_layout.addRow("", self.schedule_tasks_checkbox)

        # Screenshot permission
        self.screenshot_checkbox = QCheckBox("Access Screenshots")
        self.screenshot_checkbox.setToolTip("Allow this agent to receive desktop screenshots.")
        self.agent_settings_layout.addRow("", self.screenshot_checkbox)
        
        # Tools enabled
        self.tools_label = QLabel("Enabled Tools:")
        self.tools_list = QListWidget()
        self.tools_list.setToolTip("Select tools that this agent can use.")
        self.tools_list.setSelectionMode(QListWidget.MultiSelection)
        self.agent_settings_layout.addRow(self.tools_label, self.tools_list)
        
        layout.addLayout(self.agent_settings_layout)
        
        # Connect change events
        self.model_input.textChanged.connect(self.save_agent_settings)
        self.temperature_input.valueChanged.connect(self.save_agent_settings)
        self.max_tokens_input.valueChanged.connect(self.save_agent_settings)
        self.system_prompt_input.textChanged.connect(self.save_agent_settings)
        self.enabled_checkbox.stateChanged.connect(self.save_agent_settings)
        self.description_input.textChanged.connect(self.save_agent_settings)
        self.role_combo.currentIndexChanged.connect(self.save_agent_settings)
        self.tool_use_checkbox.stateChanged.connect(self.save_agent_settings)
        self.schedule_tasks_checkbox.stateChanged.connect(self.save_agent_settings)
        self.screenshot_checkbox.stateChanged.connect(self.save_agent_settings)
        self.managed_agents_list.itemSelectionChanged.connect(self.save_agent_settings)
        self.tools_list.itemSelectionChanged.connect(self.save_agent_settings)
        
        # Initially hide the managed agents list
        self.managed_agents_label.setVisible(False)
        self.managed_agents_list.setVisible(False)
        
        # Connect role change to show/hide managed agents
        self.role_combo.currentIndexChanged.connect(self.update_managed_agents_visibility)
        
        # Connect tool use checkbox to tools list visibility
        self.tool_use_checkbox.stateChanged.connect(self.update_tools_visibility)

    def on_agent_selected(self, index):
        if index < 0:
            return
        
        agent_name = self.agent_selector.currentText()
        self.load_agent_settings(agent_name)
    
    def load_agent_settings(self, agent_name):
        """Load agent settings into the form."""
        if not agent_name:
            return
            
        agent_settings = self.parent_app.agents_data.get(agent_name, {})
        if not agent_settings:
            return
            
        # Block signals during loading
        self.model_input.blockSignals(True)
        self.temperature_input.blockSignals(True)
        self.max_tokens_input.blockSignals(True)
        self.system_prompt_input.blockSignals(True)
        self.enabled_checkbox.blockSignals(True)
        self.description_input.blockSignals(True)
        self.role_combo.blockSignals(True)
        self.managed_agents_list.blockSignals(True)
        self.tool_use_checkbox.blockSignals(True)
        self.schedule_tasks_checkbox.blockSignals(True)
        self.screenshot_checkbox.blockSignals(True)
        self.tools_list.blockSignals(True)
        
        # Set form values
        self.model_input.setText(agent_settings.get("model", ""))
        self.temperature_input.setValue(agent_settings.get("temperature", 0.7))
        self.max_tokens_input.setValue(agent_settings.get("max_tokens", 512))
        self.system_prompt_input.setText(agent_settings.get("system_prompt", ""))
        self.enabled_checkbox.setChecked(agent_settings.get("enabled", True))
        self.description_input.setText(agent_settings.get("description", ""))
        
        # Set agent color
        agent_color = agent_settings.get("color", "#000000")
        self.update_color_button(agent_color)
        
        # Set agent role
        role = agent_settings.get("role", "Assistant")
        role_index = self.role_combo.findText(role)
        if role_index >= 0:
            self.role_combo.setCurrentIndex(role_index)
        
        # Update managed agents list
        self.managed_agents_list.clear()
        for agent in self.parent_app.agents_data.keys():
            if agent != agent_name:  # Don't allow managing self
                item = QListWidgetItem(agent)
                self.managed_agents_list.addItem(item)
                if agent in agent_settings.get("managed_agents", []):
                    item.setSelected(True)
        
        # Update tool use settings
        self.tool_use_checkbox.setChecked(agent_settings.get("tool_use", False))
        perms = agent_settings.get("permissions", {})
        self.schedule_tasks_checkbox.setChecked(perms.get("schedule_tasks", True))
        self.screenshot_checkbox.setChecked(perms.get("access_screenshots", False))
        
        # Update tools list
        self.tools_list.clear()
        for tool in self.parent_app.tools:
            tool_name = tool.get("name", "")
            if tool_name:
                item = QListWidgetItem(tool_name) # Corrected Line - Direct QListWidgetItem call
                self.tools_list.addItem(item)
                if tool_name in agent_settings.get("tools_enabled", []):
                    item.setSelected(True)
        
        # Unblock signals
        self.model_input.blockSignals(False)
        self.temperature_input.blockSignals(False)
        self.max_tokens_input.blockSignals(False)
        self.system_prompt_input.blockSignals(False)
        self.enabled_checkbox.blockSignals(False)
        self.description_input.blockSignals(False)
        self.role_combo.blockSignals(False)
        self.managed_agents_list.blockSignals(False)
        self.tool_use_checkbox.blockSignals(False)
        self.schedule_tasks_checkbox.blockSignals(False)
        self.screenshot_checkbox.blockSignals(False)
        self.tools_list.blockSignals(False)
        
        # Update visibility based on current settings
        self.update_managed_agents_visibility()
        self.update_tools_visibility()
    
    def update_managed_agents_visibility(self):
        is_coordinator = self.role_combo.currentText() == "Coordinator"
        self.managed_agents_label.setVisible(is_coordinator)
        self.managed_agents_list.setVisible(is_coordinator)
    
    def update_tools_visibility(self):
        tool_use_enabled = self.tool_use_checkbox.isChecked()
        self.tools_label.setVisible(tool_use_enabled)
        self.tools_list.setVisible(tool_use_enabled)
    
    def on_color_button_clicked(self):
        agent_name = self.agent_selector.currentText()
        if not agent_name:
            return
            
        current_color = self.parent_app.agents_data.get(agent_name, {}).get("color", "#000000")
        color = QColorDialog.getColor(Qt.black, self, "Select Agent Color")
        
        if color.isValid():
            color_hex = color.name()
            self.update_color_button(color_hex)
            
            # Save color to agent settings
            if agent_name in self.parent_app.agents_data:
                self.parent_app.agents_data[agent_name]["color"] = color_hex
                self.parent_app.save_agents()
    
    def update_color_button(self, color_hex):
        """Update the color button with the selected color."""
        self.color_button.setStyleSheet(f"background-color: {color_hex}; color: white;")
        self.color_button.setText(color_hex)
    
    def save_agent_settings(self):
        """Save agent settings from the form."""
        agent_name = self.agent_selector.currentText()
        if not agent_name or agent_name not in self.parent_app.agents_data:
            return
            
        # Build settings dictionary
        updated_settings = {
            "model": self.model_input.text(),
            "temperature": self.temperature_input.value(),
            "max_tokens": self.max_tokens_input.value(),
            "system_prompt": self.system_prompt_input.toPlainText(),
            "enabled": self.enabled_checkbox.isChecked(),
            "description": self.description_input.text(),
            "role": self.role_combo.currentText(),
            "tool_use": self.tool_use_checkbox.isChecked(),
            "permissions": {
                "schedule_tasks": self.schedule_tasks_checkbox.isChecked(),
                "use_tools": self.tool_use_checkbox.isChecked(),
                "access_screenshots": self.screenshot_checkbox.isChecked(),
            },
        }
        
        # Get color from button
        color = self.parent_app.agents_data[agent_name].get("color", "#000000")
        updated_settings["color"] = color
        
        # Get managed agents
        if self.role_combo.currentText() == "Coordinator":
            managed_agents = []
            for i in range(self.managed_agents_list.count()):
                item = self.managed_agents_list.item(i)
                if item.isSelected():
                    managed_agents.append(item.text())
            updated_settings["managed_agents"] = managed_agents
        else:
            # Ensure managed_agents exists for non-coordinators
            updated_settings["managed_agents"] = []
        
        # Get enabled tools
        enabled_tools = []
        for i in range(self.tools_list.count()):
            item = self.tools_list.item(i)
            if item.isSelected():
                enabled_tools.append(item.text())
        updated_settings["tools_enabled"] = enabled_tools
        
        # Preserve other settings that might exist
        for key, value in self.parent_app.agents_data[agent_name].items():
            if key not in updated_settings:
                updated_settings[key] = value
        
        # Update settings
        self.parent_app.agents_data[agent_name] = updated_settings
        self.parent_app.save_agents()
        self.parent_app.update_send_button_state()
    
    def on_delete_agent_clicked(self):
        agent_name = self.agent_selector.currentText()
        if not agent_name:
            return
            
        # Confirm deletion
        if QMessageBox.question(self, "Confirm Deletion", 
                               f"Are you sure you want to delete the agent '{agent_name}'?",
                               QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.parent_app.delete_agent()
    
    def load_global_preferences(self):
        """Load global preferences like model list."""
        # Use the hardcoded filename directly 
        if os.path.exists("agents.json"):
            try:
                with open("agents.json", 'r') as f:
                    agents_data = json.load(f)
                
                # Extract unique models from agents
                models = set()
                for agent_settings in agents_data.values():
                    model = agent_settings.get("model", "")
                    if model:
                        models.add(model)
                
                self.global_agent_preferences["available_models"] = list(models)
            except Exception as e:
                if self.parent_app.debug_enabled:
                    print(f"[Debug] Error loading agent preferences: {str(e)}")