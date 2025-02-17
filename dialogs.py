# dialogs.py

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QTextEdit, QLabel, QPushButton, QHBoxLayout,
    QComboBox, QStyle, QColorDialog, QCheckBox, QDateTimeEdit, QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt, QDateTime

class ToolDialog(QDialog):
    # Updated Sample Script
    SAMPLE_SCRIPT = """\"\"\"
This is a sample tool script.

This tool must define a function called `run_tool(args)` 
that accepts a dictionary of arguments and returns a string.

For example:

def run_tool(args):
    # Access arguments like this:
    arg1 = args.get('argument1', 'default_value')
    
    # Perform some operation and return a result
    result = f"Hello from the sample tool! You passed: {arg1}"
    return result
\"\"\"

def run_tool(args):
    return "Hello from the sample tool!"
"""

    def __init__(self, title="Add Tool", name="", description="", script=None):
        super().__init__()
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        # Name
        layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(name)
        self.name_edit.setToolTip("Enter a name for the tool.")
        layout.addWidget(self.name_edit)

        # Description
        layout.addWidget(QLabel("Description:"))
        self.description_edit = QLineEdit(description)
        self.description_edit.setToolTip("Enter a brief description of the tool.")
        layout.addWidget(self.description_edit)

        # Script (using a code editor with syntax highlighting)
        layout.addWidget(QLabel("Script (must define `run_tool(args)`):"))
        self.script_edit = QTextEdit()  # Consider using a proper code editor widget (see notes)
        self.script_edit.setPlainText(script if script is not None else self.SAMPLE_SCRIPT)
        self.script_edit.setToolTip(
            "Enter the Python script for the tool. It must define a `run_tool(args)` function."
        )
        layout.addWidget(self.script_edit)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_data(self):
        return (
            self.name_edit.text().strip(),
            self.description_edit.text().strip(),
            self.script_edit.toPlainText().strip()
        )

    def accept(self):
        name, description, script = self.get_data()
        if not name:
            QMessageBox.warning(self, "Error", "Tool name cannot be empty.")
            return
        if not description:
            QMessageBox.warning(self, "Error", "Tool description cannot be empty.")
            return
        if not script or "def run_tool(args):" not in script:
            QMessageBox.warning(self, "Error", "Tool script must define a `run_tool(args)` function.")
            return
        super().accept()

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

        # Agent
        layout.addWidget(QLabel("Agent:"))
        self.agent_selector = QComboBox()
        self.agent_selector.addItems(self.agents_data.keys())
        self.agent_selector.setCurrentText(agent_name)
        self.agent_selector.setToolTip("Select the agent for this task.")
        layout.addWidget(self.agent_selector)

        # Prompt
        layout.addWidget(QLabel("Prompt:"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(prompt)
        self.prompt_edit.setToolTip("Enter the prompt for the task.")
        layout.addWidget(self.prompt_edit)

        # Due Time
        layout.addWidget(QLabel("Due Time:"))
        self.due_time_edit = QDateTimeEdit()
        if due_time:
            try:
                # Attempt to parse the due_time string
                if "T" in due_time:
                    # ISO 8601 format
                    dt = QDateTime.fromString(due_time, Qt.ISODate)
                else:
                    # "YYYY-MM-DD HH:MM:SS" format
                    dt = QDateTime.fromString(due_time, "yyyy-MM-dd HH:mm:ss")

                if dt.isValid():
                    self.due_time_edit.setDateTime(dt)
                else:
                    raise ValueError("Invalid date time format")

            except ValueError:
                print(f"Error parsing due time: {due_time}")
                # Handle invalid date time format
                QMessageBox.warning(
                    self, "Error", "Invalid due time format. Using current time."
                )
                self.due_time_edit.setDateTime(QDateTime.currentDateTime())
        else: 
            self.due_time_edit.setDateTime(QDateTime.currentDateTime())

        self.due_time_edit.setToolTip("Select the due time for the task.")
        self.due_time_edit.setCalendarPopup(True)  # Enable calendar popup
        layout.addWidget(self.due_time_edit)
        

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_data(self):
        return {
            "agent_name": self.agent_selector.currentText(),
            "prompt": self.prompt_edit.toPlainText().strip(),
            "due_time": self.due_time_edit.dateTime().toString(Qt.ISODate)
        }

    def accept(self):
        data = self.get_data()
        if not data["prompt"]:
            QMessageBox.warning(self, "Error", "Prompt cannot be empty.")
            return
        if not data["due_time"]:
            QMessageBox.warning(self, "Error", "Due time cannot be empty.")
            return
        super().accept()

class SettingsDialog(QDialog):
    """
    A dialog to configure global application settings.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Settings")

        layout = QVBoxLayout(self)

        # Dark Mode
        self.dark_mode_checkbox = QCheckBox("Dark Mode")
        self.dark_mode_checkbox.setChecked(self.parent.dark_mode)
        self.dark_mode_checkbox.setToolTip("Enable or disable dark mode.")
        layout.addWidget(self.dark_mode_checkbox)

        # User Name
        layout.addWidget(QLabel("User Name:"))
        self.user_name_edit = QLineEdit(self.parent.user_name)
        self.user_name_edit.setToolTip("Enter your user name.")
        layout.addWidget(self.user_name_edit)

        # User Color
        layout.addWidget(QLabel("User Color:"))
        self.user_color_button = QPushButton()
        self.user_color_button.setStyleSheet(f"background-color: {self.parent.user_color}")
        self.user_color_button.setToolTip("Select your user color.")
        self.user_color_button.clicked.connect(self.select_user_color)
        layout.addWidget(self.user_color_button)
        
        # Debug Enabled
        self.debug_enabled_checkbox = QCheckBox("Debug Enabled")
        self.debug_enabled_checkbox.setChecked(self.parent.debug_enabled)
        self.debug_enabled_checkbox.setToolTip("Enable or disable debug mode.")
        layout.addWidget(self.debug_enabled_checkbox)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def select_user_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.user_color_button.setStyleSheet(f"background-color: {color.name()}")
            self.parent.user_color = color.name()

    def get_data(self):
        return {
            "dark_mode": self.dark_mode_checkbox.isChecked(),
            "user_name": self.user_name_edit.text().strip(),
            "user_color": self.parent.user_color,  # Color is already updated
            "debug_enabled": self.debug_enabled_checkbox.isChecked()
        }