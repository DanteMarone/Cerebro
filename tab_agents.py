#tab_agents.py
import os
import json
import copy
import requests
import tts
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton,
    QHBoxLayout, QComboBox, QFrame, QLineEdit, QTextEdit, QCheckBox,
    QColorDialog, QFormLayout, QGroupBox, QDoubleSpinBox, QSpinBox,
    QListWidget, QListWidgetItem, QMessageBox, QStackedWidget, QTabWidget, QToolButton
)
from PyQt5.QtCore import Qt

class AgentsTab(QWidget):
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.current_agent = None
        self.unsaved_changes = False
        self.original_settings = {}

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

        intro_label = QLabel("Manage automated workers that perform tasks.")
        intro_label.setWordWrap(True)
        list_layout.addWidget(intro_label)

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
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.add_agent_btn)

        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("Open Agents help")
        help_btn.clicked.connect(self.open_agents_help)
        btn_row.addWidget(help_btn)

        btn_row.addStretch()
        list_layout.addLayout(btn_row)

        self.stacked.addWidget(self.list_page)

        # ------------------------------------------------------------------
        # Agent edit page
        # ------------------------------------------------------------------
        self.edit_page = QWidget()
        edit_layout = QVBoxLayout(self.edit_page)

        nav_layout = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.show_agent_list)
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.on_save_agent_clicked)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.on_delete_agent_clicked)

        help_btn_edit = QToolButton()
        help_btn_edit.setText("?")
        help_btn_edit.setToolTip("Open Agents help")
        help_btn_edit.clicked.connect(self.open_agents_help)

        nav_layout.addStretch()
        nav_layout.addWidget(help_btn_edit)
        nav_layout.addWidget(self.cancel_button)
        nav_layout.addWidget(self.save_button)
        nav_layout.addWidget(self.delete_button)

        # Add a separator below navigation
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        edit_layout.addWidget(separator)

        # Settings tabs with progressive disclosure
        self.settings_tabs = QTabWidget()

        # -------------------
        # General tab
        # -------------------
        self.general_tab = QWidget()
        self.general_form = QFormLayout(self.general_tab)

        # Agent name
        self.name_label = QLabel("Agent Name:")
        self.name_input = QLineEdit()
        self.name_input.setToolTip("Unique name for this agent.")
        self.general_form.addRow(self.name_label, self.name_input)

        self.model_label = QLabel("Model:")
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("Select the model to use for this agent.")
        self.general_form.addRow(self.model_label, self.model_combo)

        self.enabled_checkbox = QCheckBox("Enable Agent")
        self.enabled_checkbox.setToolTip("Enable or disable this agent.")
        self.general_form.addRow("", self.enabled_checkbox)

        self.role_label = QLabel("Agent Role:")
        self.role_combo = QComboBox()
        self.role_combo.addItems(["Assistant", "Coordinator", "Specialist"])
        self.role_combo.setToolTip("Select the role for this agent.")
        self.general_form.addRow(self.role_label, self.role_combo)

        self.description_label = QLabel("Description:")
        self.description_input = QLineEdit()
        self.description_input.setToolTip("Brief description of this agent's capabilities.")
        self.general_form.addRow(self.description_label, self.description_input)

        self.color_label = QLabel("Agent Color:")
        self.color_button = QPushButton()
        self.color_button.setToolTip("Select a color for this agent's messages.")
        self.color_button.setFixedWidth(80)
        self.color_button.clicked.connect(self.on_color_button_clicked)
        self.general_form.addRow(self.color_label, self.color_button)

        # -------------------
        # Triggers tab
        # -------------------
        self.triggers_tab = QWidget()
        self.triggers_form = QFormLayout(self.triggers_tab)

        self.managed_agents_label = QLabel("Managed Agents:")
        self.managed_agents_list = QListWidget()
        self.managed_agents_list.setToolTip("Select agents that this Coordinator can manage.")
        self.managed_agents_list.setSelectionMode(QListWidget.MultiSelection)
        self.triggers_form.addRow(self.managed_agents_label, self.managed_agents_list)

        self.tool_use_checkbox = QCheckBox("Enable Tool Use")
        self.tool_use_checkbox.setToolTip("Allow this agent to use tools.")
        self.triggers_form.addRow("", self.tool_use_checkbox)

        self.tools_label = QLabel("Enabled Tools:")
        self.tools_list = QListWidget()
        self.tools_list.setToolTip("Select tools that this agent can use.")
        self.tools_list.setSelectionMode(QListWidget.MultiSelection)
        self.triggers_form.addRow(self.tools_label, self.tools_list)

        self.automations_label = QLabel("Enabled Automations:")
        self.automations_list = QListWidget()
        self.automations_list.setToolTip("Select automations that this agent can use.")
        self.automations_list.setSelectionMode(QListWidget.MultiSelection)
        self.triggers_form.addRow(self.automations_label, self.automations_list)

        # -------------------
        # Advanced tab
        # -------------------
        self.advanced_tab = QWidget()
        self.advanced_form = QFormLayout(self.advanced_tab)

        self.prompt_settings_group = QGroupBox("Prompt Settings")
        self.prompt_settings_layout = QFormLayout()
        self.prompt_settings_group.setLayout(self.prompt_settings_layout)

        self.temperature_label = QLabel("Temperature:")
        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setMinimum(0.0)
        self.temperature_input.setMaximum(1.0)
        self.temperature_input.setSingleStep(0.1)
        self.temperature_input.setToolTip("Controls randomness. Lower values produce more predictable outputs.")
        self.prompt_settings_layout.addRow(self.temperature_label, self.temperature_input)

        self.max_tokens_label = QLabel("Max Tokens:")
        self.max_tokens_input = QSpinBox()
        self.max_tokens_input.setMinimum(1)
        self.max_tokens_input.setMaximum(100000)
        self.max_tokens_input.setToolTip("Maximum number of tokens in the response.")
        self.prompt_settings_layout.addRow(self.max_tokens_label, self.max_tokens_input)

        self.system_prompt_label = QLabel("Custom System Prompt:")
        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setMinimumHeight(150)
        self.system_prompt_input.setObjectName("systemPromptInput")
        self.system_prompt_input.setToolTip("Enter a custom system prompt for the agent.")
        self.prompt_settings_layout.addRow(self.system_prompt_label, self.system_prompt_input)

        self.advanced_form.addRow(self.prompt_settings_group)

        self.thinking_checkbox = QCheckBox("Enable Thinking")
        self.thinking_checkbox.setToolTip("Allow the agent to think in steps before answering.")
        self.advanced_form.addRow("", self.thinking_checkbox)

        self.thinking_steps_label = QLabel("Thinking Steps:")
        self.thinking_steps_input = QSpinBox()
        self.thinking_steps_input.setMinimum(1)
        self.thinking_steps_input.setMaximum(10)
        self.thinking_steps_input.setToolTip("Number of thinking iterations before responding.")
        self.advanced_form.addRow(self.thinking_steps_label, self.thinking_steps_input)

        self.tts_checkbox = QCheckBox("Text-to-Speech Enabled")
        self.tts_checkbox.setToolTip("Speak this agent's replies aloud.")
        self.advanced_form.addRow("", self.tts_checkbox)

        self.voice_combo = QComboBox()
        self.voice_combo.addItem("Default")
        for name in tts.get_available_voice_names():
            self.voice_combo.addItem(name)
        self.voice_combo.setToolTip("Select the voice used for Text-to-Speech.")
        self.advanced_form.addRow("Voice", self.voice_combo)

        # Add tabs to widget
        self.settings_tabs.addTab(self.general_tab, "General")
        self.settings_tabs.addTab(self.triggers_tab, "Triggers")
        self.settings_tabs.addTab(self.advanced_tab, "Advanced")

        edit_layout.addWidget(self.settings_tabs)


        # Navigation buttons at the bottom
        edit_layout.addLayout(nav_layout)

        self.stacked.addWidget(self.edit_page)
        
        # Track unsaved changes without immediately writing to disk
        self.model_combo.currentIndexChanged.connect(self.mark_unsaved)
        self.temperature_input.valueChanged.connect(self.mark_unsaved)
        self.max_tokens_input.valueChanged.connect(self.mark_unsaved)
        self.system_prompt_input.textChanged.connect(self.mark_unsaved)
        self.enabled_checkbox.stateChanged.connect(self.mark_unsaved)
        self.description_input.textChanged.connect(self.mark_unsaved)
        self.role_combo.currentIndexChanged.connect(self.mark_unsaved)
        self.tool_use_checkbox.stateChanged.connect(self.mark_unsaved)
        self.managed_agents_list.itemSelectionChanged.connect(self.mark_unsaved)
        self.tools_list.itemSelectionChanged.connect(self.mark_unsaved)
        self.automations_list.itemSelectionChanged.connect(self.mark_unsaved)
        self.thinking_checkbox.stateChanged.connect(self.mark_unsaved)
        self.thinking_steps_input.valueChanged.connect(self.mark_unsaved)
        self.tts_checkbox.stateChanged.connect(self.mark_unsaved)
        self.voice_combo.currentIndexChanged.connect(self.mark_unsaved)
        self.name_input.textChanged.connect(self.mark_unsaved)
        
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
        self.name_input.blockSignals(True)
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
        self.thinking_checkbox.blockSignals(True)
        self.thinking_steps_input.blockSignals(True)
        self.tts_checkbox.blockSignals(True)
        self.voice_combo.blockSignals(True)
        
        # Set form values
        self.name_input.setText(agent_name)
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

        self.thinking_checkbox.setChecked(agent_settings.get("thinking_enabled", False))
        self.thinking_steps_input.setValue(agent_settings.get("thinking_steps", 3))
        self.tts_checkbox.setChecked(agent_settings.get("tts_enabled", False))
        voice_name = agent_settings.get("tts_voice", "")
        if voice_name:
            idx = self.voice_combo.findText(voice_name)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
            else:
                self.voice_combo.addItem(voice_name)
                self.voice_combo.setCurrentIndex(self.voice_combo.count() - 1)
        else:
            self.voice_combo.setCurrentIndex(0)
        
        # Update tools list
        self.tools_list.clear()
        for tool in self.parent_app.tools:
            tool_name = tool.get("name", "")
            if tool_name:
                item = QListWidgetItem(tool_name) # Corrected Line - Direct QListWidgetItem call
                self.tools_list.addItem(item)
                if tool_name in agent_settings.get("tools_enabled", []):
                    item.setSelected(True)

        # Update automations list
        self.automations_list.clear()
        for auto in getattr(self.parent_app, "automations", []):
            name = auto.get("name", "")
            if name:
                item = QListWidgetItem(name)
                self.automations_list.addItem(item)
                if name in agent_settings.get("automations_enabled", []):
                    item.setSelected(True)
        
        # Unblock signals
        self.name_input.blockSignals(False)
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
        self.automations_list.blockSignals(False)
        self.thinking_checkbox.blockSignals(False)
        self.thinking_steps_input.blockSignals(False)
        self.tts_checkbox.blockSignals(False)
        self.voice_combo.blockSignals(False)
        
        # Update visibility based on current settings
        self.update_managed_agents_visibility()
        self.update_tools_visibility()
        self.unsaved_changes = False
    
    def update_managed_agents_visibility(self):
        is_coordinator = self.role_combo.currentText() == "Coordinator"
        self.managed_agents_label.setVisible(is_coordinator)
        self.managed_agents_list.setVisible(is_coordinator)
    
    def update_tools_visibility(self):
        tool_use_enabled = self.tool_use_checkbox.isChecked()
        self.tools_label.setVisible(tool_use_enabled)
        self.tools_list.setVisible(tool_use_enabled)
        self.automations_label.setVisible(tool_use_enabled)
        self.automations_list.setVisible(tool_use_enabled)
    
    def on_color_button_clicked(self):
        agent_name = self.current_agent
        if not agent_name:
            return
            
        current_color = self.parent_app.agents_data.get(agent_name, {}).get("color", "#000000")
        color = QColorDialog.getColor(Qt.black, self, "Select Agent Color")
        
        if color.isValid():
            color_hex = color.name()
            self.update_color_button(color_hex)

            # Update color but defer saving until Save is clicked
            if agent_name in self.parent_app.agents_data:
                self.parent_app.agents_data[agent_name]["color"] = color_hex
                self.mark_unsaved()
    
    def update_color_button(self, color_hex):
        """Update the color button with the selected color."""
        self.color_button.setStyleSheet(f"background-color: {color_hex}; color: white;")
        self.color_button.setText(color_hex)

    def mark_unsaved(self, *_):
        """Flag that there are unsaved changes."""
        self.unsaved_changes = True

    def save_agent_settings(self):
        """Save agent settings from the form."""
        agent_name = self.current_agent
        if not agent_name or agent_name not in self.parent_app.agents_data:
            return

        new_name = self.name_input.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Agent name cannot be empty.")
            return

        if new_name != agent_name and new_name in self.parent_app.agents_data:
            QMessageBox.warning(self, "Name Exists", "An agent with this name already exists.")
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
            "thinking_enabled": self.thinking_checkbox.isChecked(),
            "thinking_steps": self.thinking_steps_input.value(),
            "tts_enabled": self.tts_checkbox.isChecked(),
            "tts_voice": self.voice_combo.currentText() if self.voice_combo.currentIndex() > 0 else "",
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

        enabled_autos = []
        for i in range(self.automations_list.count()):
            item = self.automations_list.item(i)
            if item.isSelected():
                enabled_autos.append(item.text())
        updated_settings["automations_enabled"] = enabled_autos
        
        # Preserve other settings that might exist
        for key, value in self.parent_app.agents_data[agent_name].items():
            if key not in updated_settings:
                updated_settings[key] = value

        # Rename if needed and update settings
        if new_name != agent_name:
            del self.parent_app.agents_data[agent_name]
            self.parent_app.agents_data[new_name] = updated_settings
            self.current_agent = new_name
        else:
            self.parent_app.agents_data[agent_name] = updated_settings
        self.parent_app.save_agents()
        self.parent_app.update_send_button_state()
        self.refresh_agent_table()
        self.unsaved_changes = False

    def on_save_agent_clicked(self):
        """Handle Save button press."""
        self.save_agent_settings()
    
    def on_delete_agent_clicked(self):
        """Prompt before deleting the current agent."""
        agent_name = self.current_agent
        if not agent_name:
            return

        task_count = sum(
            1 for t in self.parent_app.tasks if t.get("agent_name") == agent_name
        )
        message = (
            f"Are you sure you want to delete Agent '{agent_name}'? "
            "This will stop its current operations and remove its configuration."
        )
        if task_count:
            message += (
                f"\n\nAgent '{agent_name}' is currently assigned to {task_count} "
                f"task{'s' if task_count != 1 else ''}. Deleting this agent may affect these tasks."
            )
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.parent_app.delete_agent(agent_name)
            self.show_agent_list()

    def show_agent_list(self):
        """Display the list of agents."""
        if self.unsaved_changes and self.current_agent:
            self.parent_app.agents_data[self.current_agent] = copy.deepcopy(self.original_settings)
            self.unsaved_changes = False
        self.refresh_agent_table()
        self.current_agent = None
        self.stacked.setCurrentWidget(self.list_page)

    def edit_agent(self, agent_name):
        """Open the edit page for the specified agent."""
        self.current_agent = agent_name
        self.original_settings = copy.deepcopy(self.parent_app.agents_data.get(agent_name, {}))
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
                with open("agents.json", "r", encoding="utf-8") as f:
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

    def open_agents_help(self):
        """Open the documentation tab to the Agents Help section."""
        app = self.parent_app
        app.change_tab(9, app.nav_buttons.get("docs"))
        if "Agents Help" in app.docs_tab.doc_map:
            app.docs_tab.selector.setCurrentText("Agents Help")
