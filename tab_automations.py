from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout,
    QListWidgetItem, QLabel, QMessageBox, QInputDialog, QLineEdit, QStyle,
    QTabWidget, QGroupBox, QSplitter, QFormLayout, QSpinBox, QDoubleSpinBox,
    QComboBox, QTextEdit, QAbstractItemView, QApplication, QDialog, QDialogButtonBox
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QSize
import os # For checking screenshot path

from automation_sequences import (
    create_step, # Import create_step
    record_automation,
    add_automation,
    delete_automation,
    run_automation,
    STEP_TYPE_MOUSE_CLICK,
    STEP_TYPE_KEYBOARD_INPUT,
    STEP_TYPE_WAIT,
    STEP_TYPE_ASK_AGENT,
    STEP_TYPE_LOOP_START,
    STEP_TYPE_LOOP_END,
    STEP_TYPE_IF_CONDITION,
    STEP_TYPE_ELSE,
    STEP_TYPE_END_IF,
    load_step_automations,
    save_step_automations,
    run_step_automation,
)


class AskAgentDialog(QDialog):
    def __init__(self, prompt: str, screenshot_path: str = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agent Action Required")

        layout = QVBoxLayout(self)

        prompt_label = QLabel(prompt)
        prompt_label.setWordWrap(True)
        layout.addWidget(prompt_label)

        if screenshot_path and os.path.exists(screenshot_path):
            try:
                pixmap = QPixmap(screenshot_path)
                if not pixmap.isNull():
                    img_label = QLabel()
                    # Scale pixmap to fit while maintaining aspect ratio, e.g., max width 400
                    max_width = 400
                    if pixmap.width() > max_width:
                        pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)
                    img_label.setPixmap(pixmap)
                    layout.addWidget(img_label)
                else:
                    layout.addWidget(QLabel(f"Could not load screenshot: {screenshot_path}"))
            except Exception as e:
                layout.addWidget(QLabel(f"Error loading screenshot ({screenshot_path}): {e}"))
        elif screenshot_path:
            layout.addWidget(QLabel(f"Screenshot not found: {screenshot_path}"))
        else:
            layout.addWidget(QLabel("No screenshot provided."))

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        self.setMinimumWidth(400) # Ensure dialog is not too small


class AutomationsTab(QWidget):
    """Manage recorded and step-based automation sequences."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.automations = self.parent_app.automations # For recorded automations
        # self.step_automations = [] # Will be loaded separately

        # Main layout for the AutomationsTab
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        # Create the QTabWidget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Create the "Recorded Automations" tab
        self.recorded_automations_tab = QWidget()
        self.tab_widget.addTab(self.recorded_automations_tab, "Recorded Automations")
        self._setup_recorded_automations_ui()

        # Create the "Step-based Automations" tab
        self.step_automations_tab = QWidget()
        self.tab_widget.addTab(self.step_automations_tab, "Step-based Automations")
        self._setup_step_based_automations_ui()

        self.refresh_automations_list() # Initial refresh for recorded automations

    def _setup_recorded_automations_ui(self):
        """Sets up the UI for the Recorded Automations sub-tab."""
        layout = QVBoxLayout(self.recorded_automations_tab) # Use the tab's layout

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self.list_widget)

        self.no_label = QLabel("No recorded automations available.")
        self.no_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.no_label)
        self.no_label.hide()

        btn_layout = QHBoxLayout()
        self.record_btn = QPushButton("Record New Automation")
        self.record_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogYesButton'))) # Consider a more fitting icon like SP_MediaRecord
        btn_layout.addWidget(self.record_btn)

        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_TrashIcon')))
        self.delete_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_btn)

        self.run_btn = QPushButton("Run Selected")
        self.run_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_MediaPlay')))
        self.run_btn.setEnabled(False)
        btn_layout.addWidget(self.run_btn)

        layout.addLayout(btn_layout)

        self.record_btn.clicked.connect(self.record_automation_ui)
        self.delete_btn.clicked.connect(self.delete_automation_ui)
        self.run_btn.clicked.connect(self.run_automation_ui)
        self.list_widget.itemSelectionChanged.connect(self.update_recorded_buttons)

    def _setup_step_based_automations_ui(self):
        """Sets up the UI for the Step-based Automations sub-tab."""
        # Use QSplitter for resizable panels
        splitter = QSplitter(Qt.Horizontal)
        # step_tab_layout was removed, splitter will be added to main_step_layout_container later

        # Left Panel: Available Steps
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel_group = QGroupBox("Available Steps")
        left_panel_group.setLayout(left_layout)

        self.available_steps_list = QListWidget()
        # Populate with step types
        self.step_types = [ # Ensure this list is comprehensive
            STEP_TYPE_MOUSE_CLICK,
            STEP_TYPE_KEYBOARD_INPUT,
            STEP_TYPE_WAIT,
            STEP_TYPE_ASK_AGENT,
            STEP_TYPE_LOOP_START,
            STEP_TYPE_LOOP_END,
            STEP_TYPE_IF_CONDITION,
            STEP_TYPE_ELSE,
            STEP_TYPE_END_IF
        ]
        for step_type_name in self.step_types:
            self.available_steps_list.addItem(QListWidgetItem(step_type_name))
        left_layout.addWidget(self.available_steps_list)

        self.add_step_btn = QPushButton("Add Step to Sequence")
        self.add_step_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_ArrowRight')))
        left_layout.addWidget(self.add_step_btn)
        splitter.addWidget(left_panel_group) # Add group to splitter

        # Center Panel: Automation Sequence
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_panel_group = QGroupBox("Automation Sequence")
        center_panel_group.setLayout(center_layout)

        self.step_sequence_list = QListWidget()
        # Enable Drag and Drop
        self.step_sequence_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.step_sequence_list.setSelectionMode(QAbstractItemView.SingleSelection) # Ensure single selection
        self.step_sequence_list.setDefaultDropAction(Qt.MoveAction)
        self.step_sequence_list.viewport().setAcceptDrops(True)
        center_layout.addWidget(self.step_sequence_list)

        self.remove_step_btn = QPushButton("Remove Selected Step")
        self.remove_step_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
        self.remove_step_btn.setEnabled(False)
        center_layout.addWidget(self.remove_step_btn)

        splitter.addWidget(center_panel_group)

        # Right Panel: Step Parameters
        # right_panel = QWidget() # QGroupBox is already a QWidget
        self.step_parameter_editor_area = QGroupBox("Step Parameters")
        self.param_form_layout = QFormLayout() # Initialize without parent

        self.placeholder_param_label = QLabel("Select a step from the sequence to edit its parameters.", parent=self.step_parameter_editor_area)
        self.placeholder_param_label.setAlignment(Qt.AlignCenter)
        self.placeholder_param_label.setWordWrap(True)
        # Add placeholder to the layout, it will be hidden/shown as needed
        self.param_form_layout.addRow(self.placeholder_param_label)

        self.apply_param_changes_btn = QPushButton("Apply Parameter Changes")
        self.apply_param_changes_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.apply_param_changes_btn.setVisible(False) # Initially hidden
        # Add this button to a separate layout or directly to the groupbox's main layout if QFormLayout is tricky
        param_editor_v_layout = QVBoxLayout() # Main layout for the group box
        param_editor_v_layout.addLayout(self.param_form_layout)
        param_editor_v_layout.addWidget(self.apply_param_changes_btn)
        self.step_parameter_editor_area.setLayout(param_editor_v_layout)

        splitter.addWidget(self.step_parameter_editor_area)

        # Adjust initial sizes of splitter panes
        splitter.setSizes([150, 300, 250]) # Adjust as needed

        # Bottom Buttons for Step Automations
        step_bottom_btn_layout = QHBoxLayout()
        main_step_layout_container = QVBoxLayout() # This will be the main layout for step_automations_tab
        main_step_layout_container.addWidget(splitter) # Add splitter here
        main_step_layout_container.addLayout(step_bottom_btn_layout)
        self.step_automations_tab.setLayout(main_step_layout_container)


        self.save_step_auto_btn = QPushButton("Save Step Automation")
        self.save_step_auto_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogSaveButton')))
        self.save_step_auto_btn.setEnabled(False) # Disabled for now
        step_bottom_btn_layout.addWidget(self.save_step_auto_btn)

        self.load_step_auto_btn = QPushButton("Load Step Automation")
        # Icon for load: SP_DialogOpenButton or SP_DriveHDIcon
        self.load_step_auto_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogOpenButton')))
        # self.load_step_auto_btn.setEnabled(False) # Or True if it can always be active
        step_bottom_btn_layout.addWidget(self.load_step_auto_btn)

        self.run_step_auto_btn = QPushButton("Run Step Automation")
        self.run_step_auto_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_MediaPlay')))
        self.run_step_auto_btn.setEnabled(False) # Disabled for now
        step_bottom_btn_layout.addWidget(self.run_step_auto_btn)

        # Connections for step-based UI
        self.add_step_btn.clicked.connect(self.add_step_to_sequence)
        self.remove_step_btn.clicked.connect(self.remove_selected_step)
        self.step_sequence_list.itemSelectionChanged.connect(self.on_step_selection_changed)
        self.apply_param_changes_btn.clicked.connect(self.apply_step_parameter_changes)
        self.save_step_auto_btn.clicked.connect(self._save_step_automation)
        self.load_step_auto_btn.clicked.connect(self._load_step_automation)
        self.run_step_auto_btn.clicked.connect(self._run_step_automation_ui)

        self._clear_parameter_editor()
        self._update_step_based_buttons_enabled_state() # Initial state

    def _run_step_automation_ui(self):
        if self.step_sequence_list.count() == 0:
            QMessageBox.warning(self, "Empty Sequence", "There are no steps in the current automation sequence to run.")
            return

        steps_data = []
        for i in range(self.step_sequence_list.count()):
            item = self.step_sequence_list.item(i)
            step_data = item.data(Qt.UserRole)
            if step_data:
                steps_data.append(step_data)
            else:
                QMessageBox.critical(self, "Error", f"Internal error: Step item '{item.text()}' has no data. Aborting run.")
                return

        delay, ok = QInputDialog.getDouble(self, "Set Step Delay", "Delay between steps (seconds):", 0.1, 0, 60, 1)
        if not ok:
            return # User cancelled

        # Optionally, add a small delay before starting to allow user to switch focus
        # time.sleep(1) # Consider if this is needed or should be a specific "Wait" step by user

        self.parent_app.main_window.showMinimized() # Minimize main window before running
        QApplication.processEvents() # Ensure minimization is processed
        # A small delay to ensure window is minimized, though pyautogui usually handles focus well.
        # This might need adjustment based on system performance.
        # For very fast systems, time.sleep(0.5) or even less might be enough.
        # For slower systems, or if focus issues persist, a slightly longer delay could be tried.
        # However, the best practice is for pyautogui to manage focus, which it usually does.
        # If focus issues are frequent, it might indicate a deeper issue with the environment
        # or how pyautogui interacts with it.
        # A common pattern is to give a few seconds for the user to prepare,
        # often as part of the instructions or a countdown.
        # Here, we're just minimizing and immediately running.
        # A very short sleep to allow window manager to react.
        time.sleep(0.2)

        execution_context = None # Initialize to run from the start

        while True:
            # Ensure window is minimized before running a segment, unless an AskAgent is expected
            # This check is a bit tricky because we don't know if the *next* step is AskAgent
            # For simplicity, we minimize, and if AskAgent is returned, we re-show.
            if not (execution_context and execution_context.get('status') == 'paused_ask_agent'):
                 if not self.parent_app.main_window.isMinimized():
                    self.parent_app.main_window.showMinimized()
                    QApplication.processEvents()
                    time.sleep(0.2) # Allow time to minimize

            execution_context = run_step_automation(
                steps_data,
                step_delay=delay,
                execution_context=execution_context
            )

            status = execution_context.get('status')

            if status == 'paused_ask_agent':
                self.parent_app.main_window.showNormal()
                self.parent_app.main_window.activateWindow()
                QApplication.processEvents()

                prompt = execution_context.get("ask_agent_prompt", "Agent action required.")
                screenshot_path = execution_context.get("ask_agent_screenshot_path")

                dialog = AskAgentDialog(prompt, screenshot_path, self)
                dialog_result = dialog.exec_()

                if dialog_result == QDialog.Accepted:
                    execution_context['current_step_index'] = execution_context.get('next_step_index_after_ask', 0)
                    # Loop continues
                else:
                    QMessageBox.warning(self, "Automation Paused", "Automation paused by user.")
                    break # Stop the loop

            elif status == 'completed':
                QMessageBox.information(self, "Automation Finished", "Step automation executed successfully.")
                break

            elif status == 'error':
                error_msg = execution_context.get('error_message', 'Unknown error occurred.')
                QMessageBox.warning(self, "Automation Error", error_msg)
                break

            else: # Unknown status or loop without explicit break condition
                QMessageBox.critical(self, "Runtime Error", f"Unhandled automation status: {status}")
                break

        # Final restoration if window was minimized
        if self.parent_app.main_window.isMinimized():
            self.parent_app.main_window.showNormal()
            self.parent_app.main_window.activateWindow()

    def _update_step_based_buttons_enabled_state(self):
        has_steps = self.step_sequence_list.count() > 0
        self.save_step_auto_btn.setEnabled(has_steps)
        self.run_step_auto_btn.setEnabled(has_steps)
        # load_step_auto_btn is always enabled, or could check if file exists / has content

    def update_recorded_buttons(self):
        has_sel = bool(self.list_widget.selectedItems())
        self.delete_btn.setEnabled(has_sel)
        self.run_btn.setEnabled(has_sel)

    def refresh_automations_list(self):
        # This now only refreshes the recorded automations list
        if not hasattr(self, 'list_widget'): # Check if UI setup has happened
            return
        self.list_widget.clear()
        if not self.automations:
            self.no_label.show()
            self.list_widget.hide() # Hide list widget when no label is shown
            return
        self.no_label.hide()
        self.list_widget.show() # Show list widget
        for auto in self.automations:
            item = QListWidgetItem(auto.get("name", ""))
            self.list_widget.addItem(item)

    def _generate_step_display_text(self, step_data: dict) -> str:
        """Generates a user-friendly display string for a step."""
        step_type = step_data.get("type")
        params = step_data.get("params", {})

        if step_type == STEP_TYPE_MOUSE_CLICK:
            return f"{step_type} (x:{params.get('x',0)}, y:{params.get('y',0)}, button:{params.get('button','left')})"
        elif step_type == STEP_TYPE_KEYBOARD_INPUT:
            return f"{step_type} (keys:'{params.get('keys','')}')"
        elif step_type == STEP_TYPE_WAIT:
            return f"{step_type} (duration:{params.get('duration',1.0)}s)"
        elif step_type == STEP_TYPE_ASK_AGENT:
            prompt = params.get('prompt','')
            return f"{step_type} (prompt:'{prompt[:20]}{'...' if len(prompt) > 20 else ''}')"
        elif step_type == STEP_TYPE_LOOP_START:
            if "count" in params:
                return f"{step_type} (count:{params.get('count',1)})"
            elif "condition" in params:
                return f"{step_type} (condition:'{params.get('condition','').strip()}')" # Added strip
            return f"{step_type} (count:1)" # Default
        elif step_type == STEP_TYPE_IF_CONDITION:
            return f"{STEP_TYPE_IF_CONDITION} (condition:'{params.get('condition','true').strip()}')" # Default to true, added strip
        elif step_type == STEP_TYPE_ELSE:
            return STEP_TYPE_ELSE
        elif step_type == STEP_TYPE_END_IF:
            return STEP_TYPE_END_IF
        elif step_type == STEP_TYPE_LOOP_END: # Explicitly handle LoopEnd if not covered by generic
            return STEP_TYPE_LOOP_END
        # Fallback for any other types that might be simple
        elif step_type in [STEP_TYPE_LOOP_END, STEP_TYPE_ELSE, STEP_TYPE_END_IF]: # Redundant but safe
            return step_type
        return f"Unknown Step: {step_type}"

    def add_step_to_sequence(self):
        selected_items = self.available_steps_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Step Type Selected", "Please select a step type from the 'Available Steps' list.")
            return

        step_type_name = selected_items[0].text()

        # Create step with default parameters
        default_params = {}
        if step_type_name == STEP_TYPE_MOUSE_CLICK:
            default_params = {"x": 0, "y": 0, "button": "left"}
        elif step_type_name == STEP_TYPE_KEYBOARD_INPUT:
            default_params = {"keys": ""}
        elif step_type_name == STEP_TYPE_WAIT:
            default_params = {"duration": 1.0}
        elif step_type_name == STEP_TYPE_ASK_AGENT:
            default_params = {"prompt": "", "screenshot_path": None}
        elif step_type_name == STEP_TYPE_LOOP_START:
            default_params = {"count": 1}
        elif step_type_name == STEP_TYPE_IF_CONDITION:
            default_params = {"condition": "true"} # Default If condition to "true"
        # For Else, EndIf, LoopEnd, params dict remains empty {}

        new_step_data = create_step(step_type_name, default_params)

        display_text = self._generate_step_display_text(new_step_data)
        list_item = QListWidgetItem(display_text)
        list_item.setData(Qt.UserRole, new_step_data) # Store the dictionary
        self.step_sequence_list.addItem(list_item)
        self._update_step_based_buttons_enabled_state()

    def remove_selected_step(self):
        selected_items = self.step_sequence_list.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.step_sequence_list.takeItem(self.step_sequence_list.row(item))
        # After removing, clear parameter editor and update button states
        self.on_step_selection_changed()
        self._update_step_based_buttons_enabled_state()

    def _clear_parameter_editor(self):
        """Clears the parameter editor and shows the placeholder."""
        # Remove all widgets from the form layout except the placeholder
        while self.param_form_layout.rowCount() > 0:
            self.param_form_layout.removeRow(0)

        # Add the placeholder back if it's not already there (it might be if it was the only thing)
        # A bit of a hacky way to ensure it's the only thing
        if self.param_form_layout.rowCount() == 0 :
             self.param_form_layout.addRow(self.placeholder_param_label)

        self.placeholder_param_label.setVisible(True)
        self.apply_param_changes_btn.setVisible(False)
        # Clear any dynamically added widgets stored in a list if you have one
        self.current_param_widgets = {} # Reset current param widgets

    def on_step_selection_changed(self):
        selected_items = self.step_sequence_list.selectedItems()
        if not selected_items:
            self._clear_parameter_editor()
            self.remove_step_btn.setEnabled(False)
            # self._update_step_based_buttons_enabled_state() # Already called by remove_selected_step if selection becomes empty
            return

        self.remove_step_btn.setEnabled(True)
        # self._update_step_based_buttons_enabled_state() # Not strictly needed here as buttons depend on count, not selection for save/run
        item = selected_items[0]
        step_data = item.data(Qt.UserRole)
        if not step_data:
            self._clear_parameter_editor()
            return

        self._populate_parameter_editor(step_data)

    def _populate_parameter_editor(self, step_data: dict):
        self._clear_parameter_editor() # Clear previous content
        self.placeholder_param_label.setVisible(False) # Hide placeholder
        self.apply_param_changes_btn.setVisible(True)

        step_type = step_data.get("type")
        params = step_data.get("params", {})
        self.current_param_widgets = {} # To store references to input widgets

        if step_type == STEP_TYPE_MOUSE_CLICK:
            self.current_param_widgets["x"] = QSpinBox()
            self.current_param_widgets["x"].setRange(0, 10000)
            self.current_param_widgets["x"].setValue(params.get("x", 0))
            self.param_form_layout.addRow("X:", self.current_param_widgets["x"])

            self.current_param_widgets["y"] = QSpinBox()
            self.current_param_widgets["y"].setRange(0, 10000)
            self.current_param_widgets["y"].setValue(params.get("y", 0))
            self.param_form_layout.addRow("Y:", self.current_param_widgets["y"])

            self.current_param_widgets["button"] = QComboBox()
            self.current_param_widgets["button"].addItems(["left", "right", "middle"])
            self.current_param_widgets["button"].setCurrentText(params.get("button", "left"))
            self.param_form_layout.addRow("Button:", self.current_param_widgets["button"])

        elif step_type == STEP_TYPE_KEYBOARD_INPUT:
            self.current_param_widgets["keys"] = QLineEdit(params.get("keys", ""))
            self.param_form_layout.addRow("Keys:", self.current_param_widgets["keys"])

        elif step_type == STEP_TYPE_WAIT:
            self.current_param_widgets["duration"] = QDoubleSpinBox()
            self.current_param_widgets["duration"].setRange(0.1, 3600.0)
            self.current_param_widgets["duration"].setSingleStep(0.1)
            self.current_param_widgets["duration"].setValue(params.get("duration", 1.0))
            self.param_form_layout.addRow("Duration (s):", self.current_param_widgets["duration"])

        elif step_type == STEP_TYPE_ASK_AGENT:
            self.current_param_widgets["prompt"] = QTextEdit(params.get("prompt", ""))
            self.current_param_widgets["prompt"].setFixedHeight(100) # Example height
            self.param_form_layout.addRow("Prompt:", self.current_param_widgets["prompt"])
            # screenshot_path browse button can be added here later
            # For now, store it if it exists, but don't make it editable directly
            if "screenshot_path" in params:
                 self.current_param_widgets["screenshot_path"] = params.get("screenshot_path")


        elif step_type == STEP_TYPE_LOOP_START:
            # For now, only 'count'. 'condition' would need different UI (e.g. QLineEdit)
            if "count" in params or ("condition" not in params): # Prioritize count if both somehow exist
                self.current_param_widgets["count"] = QSpinBox()
                self.current_param_widgets["count"].setRange(1, 1000)
                self.current_param_widgets["count"].setValue(params.get("count", 1))
                self.param_form_layout.addRow("Count:", self.current_param_widgets["count"])
            # elif "condition" in params: # For later
            #     self.current_param_widgets["condition"] = QLineEdit(params.get("condition", "")) # Kept for LoopStart if condition-based loops are added
            #     self.param_form_layout.addRow("Condition:", self.current_param_widgets["condition"])


        elif step_type == STEP_TYPE_IF_CONDITION:
            self.current_param_widgets["condition"] = QLineEdit(params.get("condition", "true")) # Default to "true"
            self.param_form_layout.addRow("Condition (true/false):", self.current_param_widgets["condition"])

        elif step_type in [STEP_TYPE_LOOP_END, STEP_TYPE_ELSE, STEP_TYPE_END_IF]:
            self.param_form_layout.addRow(QLabel(f"{step_type} (No parameters)"))
            self.apply_param_changes_btn.setVisible(False)

        else:
            self.param_form_layout.addRow(QLabel(f"Unknown step type: {step_type}"))
            self.apply_param_changes_btn.setVisible(False)

    def apply_step_parameter_changes(self):
        selected_items = self.step_sequence_list.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        step_data = item.data(Qt.UserRole)
        if not step_data:
            return

        step_type = step_data["type"]
        new_params = {}

        try:
            if step_type == STEP_TYPE_MOUSE_CLICK:
                new_params["x"] = self.current_param_widgets["x"].value()
                new_params["y"] = self.current_param_widgets["y"].value()
                new_params["button"] = self.current_param_widgets["button"].currentText()
            elif step_type == STEP_TYPE_KEYBOARD_INPUT:
                new_params["keys"] = self.current_param_widgets["keys"].text()
            elif step_type == STEP_TYPE_WAIT:
                new_params["duration"] = self.current_param_widgets["duration"].value()
            elif step_type == STEP_TYPE_ASK_AGENT:
                new_params["prompt"] = self.current_param_widgets["prompt"].toPlainText()
                # Preserve screenshot_path if it was there and not editable
                if "screenshot_path" in self.current_param_widgets and \
                   self.current_param_widgets["screenshot_path"] is not None:
                    new_params["screenshot_path"] = self.current_param_widgets["screenshot_path"]
                elif "screenshot_path" in step_data["params"]: # carry over if exists
                     new_params["screenshot_path"] = step_data["params"]["screenshot_path"]
                else:
                    new_params["screenshot_path"] = None

            elif step_type == STEP_TYPE_LOOP_START:
                if "count" in self.current_param_widgets: # Check if count widget exists
                    new_params["count"] = self.current_param_widgets["count"].value()
                # elif "condition" in self.current_param_widgets: # For later
                #     new_params["condition"] = self.current_param_widgets["condition"].text() # Kept for LoopStart if condition-based loops are added

            elif step_type == STEP_TYPE_IF_CONDITION:
                condition_val = self.current_param_widgets["condition"].text().lower().strip()
                if condition_val not in ["true", "false"]:
                    QMessageBox.warning(self, "Invalid Condition", "Condition for If step must be 'true' or 'false'.")
                    return # Don't apply changes
                new_params["condition"] = condition_val
            # No params for LoopEnd, Else, EndIf to read, so new_params remains {} for them, which is fine.

            step_data["params"] = new_params # Update params, even if it's empty for some types
            item.setData(Qt.UserRole, step_data) # Update data in item
            item.setText(self._generate_step_display_text(step_data)) # Update display text
            QMessageBox.information(self, "Changes Applied", "Step parameters updated successfully.")
        except KeyError as e:
            QMessageBox.warning(self, "Error", f"Could not find parameter widget for: {e}. Changes not applied.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"An error occurred while applying changes: {e}")

    def _save_step_automation(self):
        if self.step_sequence_list.count() == 0:
            QMessageBox.warning(self, "Empty Automation", "Cannot save an empty automation sequence.")
            return

        automation_name, ok = QInputDialog.getText(self, "Save Step Automation", "Enter automation name:")
        if not ok or not automation_name.strip():
            return # User cancelled or entered empty name

        automation_name = automation_name.strip()

        steps_data = []
        for i in range(self.step_sequence_list.count()):
            item = self.step_sequence_list.item(i)
            step_data = item.data(Qt.UserRole)
            if step_data:
                steps_data.append(step_data)
            else: # Should not happen if items are always added with data
                QMessageBox.critical(self, "Error", f"Internal error: Step item '{item.text()}' has no data. Aborting save.")
                return


        current_automation = {"name": automation_name, "steps": steps_data}

        try:
            existing_automations = load_step_automations(debug_enabled=self.parent_app.debug_enabled)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load existing step automations: {e}")
            return

        found_existing = False
        for i, auto in enumerate(existing_automations):
            if auto.get("name") == automation_name:
                reply = QMessageBox.question(self, "Overwrite Confirmation",
                                             f"An automation named '{automation_name}' already exists. Overwrite it?",
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.Yes:
                    existing_automations[i] = current_automation
                else:
                    return # User chose not to overwrite
                found_existing = True
                break

        if not found_existing:
            existing_automations.append(current_automation)

        try:
            save_step_automations(existing_automations, debug_enabled=self.parent_app.debug_enabled)
            QMessageBox.information(self, "Save Successful", f"Automation '{automation_name}' saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save step automation: {e}")

        self._update_step_based_buttons_enabled_state()


    def _load_step_automation(self):
        try:
            all_automations = load_step_automations(debug_enabled=self.parent_app.debug_enabled)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load step automations: {e}")
            return

        if not all_automations:
            QMessageBox.information(self, "No Automations", "No step-based automations found to load.")
            return

        automation_names = [auto.get("name", "Unnamed") for auto in all_automations]
        chosen_name, ok = QInputDialog.getItem(self, "Load Step Automation",
                                               "Select an automation to load:", automation_names, 0, False)

        if not ok or not chosen_name:
            return # User cancelled

        selected_automation_data = None
        for auto in all_automations:
            if auto.get("name") == chosen_name:
                selected_automation_data = auto
                break

        if not selected_automation_data or "steps" not in selected_automation_data:
            QMessageBox.warning(self, "Load Error", f"Could not find or parse data for automation '{chosen_name}'.")
            return

        # Clear current sequence
        self.step_sequence_list.clear()
        self._clear_parameter_editor() # Also clear parameter editor

        # Populate with loaded steps
        for step_data in selected_automation_data["steps"]:
            display_text = self._generate_step_display_text(step_data)
            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.UserRole, step_data)
            self.step_sequence_list.addItem(list_item)

        QMessageBox.information(self, "Load Successful", f"Automation '{chosen_name}' loaded.")
        self._update_step_based_buttons_enabled_state()


    def record_automation_ui(self):
        name, ok = QInputDialog.getText(self, "Record Automation", "Name:")
        if not ok or not name.strip():
            return
        duration_str, ok = QInputDialog.getText(
            self, "Record Automation", "Duration (seconds):", QLineEdit.Normal, "5"
        )
        if not ok:
            return
        try:
            duration = float(duration_str)
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Duration must be a number.")
            return
        events = record_automation(duration)
        if not events:
            QMessageBox.warning(self, "Error", "Recording failed or pynput not installed.")
            return
        add_automation(self.parent_app.automations, name, events, self.parent_app.debug_enabled)
        self.automations = self.parent_app.automations # This line seems duplicated, already in __init__ and add_automation
        self.refresh_automations_list()

    def delete_automation_ui(self): # This is for recorded automations
        items = self.list_widget.selectedItems()
        if not items:
            return
        name = items[0].text()
        if QMessageBox.question(self, "Confirm Delete", f"Delete recorded automation '{name}'?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        delete_automation(self.parent_app.automations, name, self.parent_app.debug_enabled)
        # self.automations = self.parent_app.automations # This line seems duplicated
        self.refresh_automations_list()

    def run_automation_ui(self): # This is for recorded automations
        items = self.list_widget.selectedItems()
        if not items:
            return
        name = items[0].text()
        # Use QInputDialog.getDouble for consistency with step automation delay
        delay, ok = QInputDialog.getDouble(
            self, "Run Recorded Automation", "Delay between actions (seconds):",
            0.5, 0, 60, 1
        )
        if not ok:
            return

        # Minimize window before running recorded automation as well
        self.parent_app.main_window.showMinimized()
        QApplication.processEvents()
        import time # Ensure time is imported
        time.sleep(0.2)


        result = run_automation(self.parent_app.automations, name, delay)

        self.parent_app.main_window.showNormal()
        self.parent_app.main_window.activateWindow()

        if "Error" in result: # Simple check for error in result string
            QMessageBox.warning(self, "Automation Error", result)
        else:
            QMessageBox.information(self, "Automation Result", result)
