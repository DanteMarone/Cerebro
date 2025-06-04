#tab_agents.py
import os
import json
import requests
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton,
    QHBoxLayout, QComboBox, QFrame, QLineEdit, QTextEdit, QCheckBox,
    QColorDialog, QFormLayout, QGroupBox, QDoubleSpinBox, QSpinBox,
    QListWidget, QListWidgetItem, QMessageBox, QStackedWidget
)
from PyQt5.QtCore import Qt

class AgentsTab(QWidget):
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.current_agent = None

        self.global_agent_preferences = {}

        self.init_ui()
        self.load_global_preferences()
        self.show_agent_list()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        self.stacked = QStackedWidget()
        main_layout.addWidget(self.stacked)

        # ------------------------------------------------------------------
        # Agent list page
        # ------------------------------------------------------------------
        self.list_page = QWidget()
        list_layout = QVBoxLayout(self.list_page)

        self.agent_table = QTableWidget(0, 5)
        self.agent_table.setHorizontalHeaderLabels([
            "Name",
            "Description",
            "Role",
            "Model",
            "",
        ])
        list_layout.addWidget(self.agent_table)

        self.add_agent_btn = QPushButton("Add New Agent")
        self.add_agent_btn.clicked.connect(self.parent_app.add_agent)
        list_layout.addWidget(self.add_agent_btn, alignment=Qt.AlignLeft)

        self.stacked.addWidget(self.list_page)

        # ------------------------------------------------------------------
        # Agent edit page
        # ------------------------------------------------------------------
        self.edit_page = QWidget()
        edit_layout = QVBoxLayout(self.edit_page)

        nav_layout = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.show_agent_list)
        self.delete_button = QPushButton("Delete Agent")
        self.delete_button.clicked.connect(self.on_delete_agent_clicked)
        nav_layout.addWidget(self.back_button)
        nav_layout.addStretch()
        nav_layout.addWidget(self.delete_button)
        edit_layout.addLayout(nav_layout)

        # Add a separator below navigation
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        edit_layout.addWidget(separator)

        # Agent settings form
        self.agent_settings_layout = QFormLayout()
        
        # --- Basic Settings ---
        self.model_label = QLabel("Model:")
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("Select the model to use for this agent.")
        self.agent_settings_layout.addRow(self.model_label, self.model_combo)
        
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
        
        # Tools enabled
        self.tools_label = QLabel("Enabled Tools:")
        self.tools_list = QListWidget()
        self.tools_list.setToolTip("Select tools that this agent can use.")
        self.tools_list.setSelectionMode(QListWidget.MultiSelection)
        self.agent_settings_layout.addRow(self.tools_label, self.tools_list)
        
        edit_layout.addLayout(self.agent_settings_layout)

        self.stacked.addWidget(self.edit_page)
        
        # Connect change events
        self.model_combo.currentIndexChanged.connect(self.save_agent_settings)
        self.temperature_input.valueChanged.connect(self.save_agent_settings)
        self.max_tokens_input.valueChanged.connect(self.save_agent_settings)
        self.system_prompt_input.textChanged.connect(self.save_agent_settings)
        self.enabled_checkbox.stateChanged.connect(self.save_agent_settings)
        self.description_input.textChanged.connect(self.save_agent_settings)
        self.role_combo.currentIndexChanged.connect(self.save_agent_settings)
        self.tool_use_checkbox.stateChanged.connect(self.save_agent_settings)
        self.managed_agents_list.itemSelectionChanged.connect(self.save_agent_settings)
        self.tools_list.itemSelectionChanged.connect(self.save_agent_settings)
        
        # Initially hide the managed agents list
        self.managed_agents_label.setVisible(False)
        self.managed_agents_list.setVisible(False)
        
        # Connect role change to show/hide managed agents
        self.role_combo.currentIndexChanged.connect(self.update_managed_agents_visibility)
        
        # Connect tool use checkbox to tools list visibility
        self.tool_use_checkbox.stateChanged.connect(self.update_tools_visibility)

    def load_agent_settings(self, agent_name):
        """Load agent settings into the form."""
        if not agent_name:
            return
            
        agent_settings = self.parent_app.agents_data.get(agent_name, {})
        if not agent_settings:
            return
            
        # Block signals during loading
        self.model_combo.blockSignals(True)
        self.temperature_input.blockSignals(True)
        self.max_tokens_input.blockSignals(True)
        self.system_prompt_input.blockSignals(True)
        self.enabled_checkbox.blockSignals(True)
        self.description_input.blockSignals(True)
        self.role_combo.blockSignals(True)
        self.managed_agents_list.blockSignals(True)
        self.tool_use_checkbox.blockSignals(True)
        self.tools_list.blockSignals(True)
        
        # Set form values
        self.update_model_dropdown()
        model_value = agent_settings.get("model", "")
        index = self.model_combo.findText(model_value)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        elif model_value:
            self.model_combo.addItem(model_value)
            self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
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
        self.model_combo.blockSignals(False)
        self.temperature_input.blockSignals(False)
        self.max_tokens_input.blockSignals(False)
        self.system_prompt_input.blockSignals(False)
        self.enabled_checkbox.blockSignals(False)
        self.description_input.blockSignals(False)
        self.role_combo.blockSignals(False)
        self.managed_agents_list.blockSignals(False)
        self.tool_use_checkbox.blockSignals(False)
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
        agent_name = self.current_agent
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
        agent_name = self.current_agent
        if not agent_name or agent_name not in self.parent_app.agents_data:
            return
            
        # Build settings dictionary
        updated_settings = {
            "model": self.model_combo.currentText(),
            "temperature": self.temperature_input.value(),
            "max_tokens": self.max_tokens_input.value(),
            "system_prompt": self.system_prompt_input.toPlainText(),
            "enabled": self.enabled_checkbox.isChecked(),
            "description": self.description_input.text(),
            "role": self.role_combo.currentText(),
            "tool_use": self.tool_use_checkbox.isChecked(),
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
        agent_name = self.current_agent
        if not agent_name:
            return
            
        # Confirm deletion
        if QMessageBox.question(self, "Confirm Deletion", 
                               f"Are you sure you want to delete the agent '{agent_name}'?",
                               QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.parent_app.delete_agent(agent_name)
            self.show_agent_list()

    def show_agent_list(self):
        """Display the list of agents."""
        self.refresh_agent_table()
        self.stacked.setCurrentWidget(self.list_page)

    def edit_agent(self, agent_name):
        """Open the edit page for the specified agent."""
        self.current_agent = agent_name
        self.load_agent_settings(agent_name)
        self.stacked.setCurrentWidget(self.edit_page)

    def refresh_agent_table(self):
        """Populate the agent table with current data."""
        self.agent_table.setRowCount(0)
        for row, (name, settings) in enumerate(self.parent_app.agents_data.items()):
            self.agent_table.insertRow(row)
            self.agent_table.setItem(row, 0, QTableWidgetItem(name))
            self.agent_table.setItem(row, 1, QTableWidgetItem(settings.get("description", "")))
            self.agent_table.setItem(row, 2, QTableWidgetItem(settings.get("role", "")))
            self.agent_table.setItem(row, 3, QTableWidgetItem(settings.get("model", "")))
            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda _ , n=name: self.edit_agent(n))
            self.agent_table.setCellWidget(row, 4, edit_btn)
    
    def load_global_preferences(self):
        """Load global preferences like model list."""
        models = self.fetch_available_models()
        if not models and os.path.exists("agents.json"):
            try:
                with open("agents.json", "r") as f:
                    agents_data = json.load(f)

                models = {
                    settings.get("model", "")
                    for settings in agents_data.values()
                    if settings.get("model", "")
                }
            except Exception as e:
                if self.parent_app.debug_enabled:
                    print(f"[Debug] Error loading agent preferences: {str(e)}")

        self.global_agent_preferences["available_models"] = list(models)
        self.update_model_dropdown()

    def fetch_available_models(self):
        """Fetch installed Ollama models via the tags API."""
        url = "http://localhost:11434/api/tags"
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            return [m.get("name") for m in data.get("models", []) if m.get("name")]
        except Exception as e:
            if self.parent_app.debug_enabled:
                print(f"[Debug] Failed to fetch models: {e}")
            return []

    def update_model_dropdown(self):
        """Populate the model combo box with available models."""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        models = self.global_agent_preferences.get("available_models", [])
        self.model_combo.addItems(models)
        self.model_combo.blockSignals(False)
