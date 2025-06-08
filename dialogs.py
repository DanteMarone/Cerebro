# dialogs.py

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QTextEdit,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QComboBox,
    QStyle,
    QColorDialog,
    QCheckBox,
    QDateTimeEdit,
    QDialogButtonBox,
    QMessageBox,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
)
import subprocess
from PyQt5.QtCore import Qt, QDateTime

try:
    from PyQt5.Qsci import QsciScintilla, QsciLexerPython

    class CodeEditor(QsciScintilla):
        """A simple Python code editor with syntax highlighting."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setUtf8(True)
            self.setMarginsBackgroundColor(Qt.lightGray)
            self.setMarginType(0, QsciScintilla.NumberMargin)
            self.setMarginWidth(0, "0000")
            lexer = QsciLexerPython()
            self.setLexer(lexer)

        def text(self):  # compatibility with QTextEdit
            return QsciScintilla.text(self)

        def set_text(self, text):
            self.setText(text)

except Exception:  # QScintilla not installed
    class CodeEditor(QTextEdit):
        """Fallback plain text editor used when QScintilla is unavailable."""

        def text(self):
            return self.toPlainText()

        def set_text(self, text):
            self.setPlainText(text)

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
        self.script_edit = CodeEditor()
        self.script_edit.set_text(script if script is not None else self.SAMPLE_SCRIPT)
        self.script_edit.setToolTip(
            "Enter the Python script for the tool. It must define a `run_tool(args)` function."
        )
        layout.addWidget(self.script_edit)

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.button_box.button(QDialogButtonBox.Ok)
        self.ok_button.setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Connect inputs to validation
        self.prompt_edit.textChanged.connect(self.validate_fields)
        self.due_time_edit.dateTimeChanged.connect(self.validate_fields)
        self.agent_selector.currentIndexChanged.connect(self.validate_fields)

        self.validate_fields()

    def validate_fields(self):
        """Validate settings inputs and update the dialog state."""
        errors = []
        if not self.user_name_edit.text().strip():
            errors.append("User Name is required.")
        if not (1 <= self.interval_spin.value() <= 60):
            errors.append("Screenshot Interval must be 1-60.")
        if not (0 <= self.threshold_spin.value() <= 200):
            errors.append("Summarization Threshold must be 0-200.")
        if not (1 <= self.port_spin.value() <= 65535):
            errors.append("Ollama Port must be 1-65535.")

        self.ok_button.setEnabled(not errors)
        self.error_label.setText("\n".join(errors))
        self.error_label.setVisible(bool(errors))

    def get_data(self):
        return (
            self.name_edit.text().strip(),
            self.description_edit.text().strip(),
            self.script_edit.text().strip()
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
    def __init__(self, parent, agents_data, task_id=None, agent_name="", prompt="", due_time="", repeat_interval=0):
        super().__init__(parent)
        self.setWindowTitle("Add/Edit Task")
        self.agents_data = agents_data
        self.task_id = task_id
        self.repeat_interval = repeat_interval

        layout = QVBoxLayout(self)

# Assignee (required)
        layout.addWidget(QLabel("Assignee*:"))
        self.agent_selector = QComboBox()
        self.agent_selector.addItems(self.agents_data.keys())
        self.agent_selector.setCurrentText(agent_name)
        self.agent_selector.setToolTip("Select the assignee for this task.")
        layout.addWidget(self.agent_selector)

        # Task Description (required)
        layout.addWidget(QLabel("Task Description*:"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(prompt)
        self.prompt_edit.setToolTip("Enter the task description or instructions.")
        layout.addWidget(self.prompt_edit)

        # Due Date (required)
        layout.addWidget(QLabel("Due Date*:"))
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
                    self, "Error", "Invalid due time format. Using current time + 1 minute."
                )
                self.due_time_edit.setDateTime(QDateTime.currentDateTime().addSecs(60))
        else:
            self.due_time_edit.setDateTime(QDateTime.currentDateTime().addSecs(60))

        self.due_time_edit.setToolTip("Select the due date and time for the task.")
        self.due_time_edit.setCalendarPopup(True)  # Enable calendar popup
        layout.addWidget(self.due_time_edit)

        # Repeat Interval
        layout.addWidget(QLabel("Repeat Interval (minutes):"))
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setMinimum(0)
        self.repeat_spin.setMaximum(525600)  # up to a year
        self.repeat_spin.setValue(self.repeat_interval)
        self.repeat_spin.setToolTip("Minutes between repetitions. 0 for none.")
        layout.addWidget(self.repeat_spin)
        

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.button_box.button(QDialogButtonBox.Ok)
        self.ok_button.setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Connect inputs to validation
        self.prompt_edit.textChanged.connect(self.validate_fields)
        self.due_time_edit.dateTimeChanged.connect(self.validate_fields)
        self.agent_selector.currentIndexChanged.connect(self.validate_fields)

        self.validate_fields()

    def get_data(self):
        return {
            "agent_name": self.agent_selector.currentText(),
            "prompt": self.prompt_edit.toPlainText().strip(),
            "due_time": self.due_time_edit.dateTime().toString(Qt.ISODate),
            "repeat_interval": self.repeat_spin.value(),
        }

    def validate_fields(self):
        """Enable or disable the OK button based on required fields."""
        agent_ok = bool(self.agent_selector.currentText().strip())
        prompt_ok = bool(self.prompt_edit.toPlainText().strip())
        due_ok = self.due_time_edit.dateTime().isValid()

        # Clear highlights
        for w in (self.agent_selector, self.prompt_edit, self.due_time_edit):
            w.setStyleSheet("")

        valid = agent_ok and prompt_ok and due_ok
        self.ok_button.setEnabled(valid)
        return valid

    def accept(self):
        if not self.validate_fields():
            if not self.agent_selector.currentText().strip():
                self.agent_selector.setStyleSheet("border: 1px solid red")
                self.agent_selector.setFocus()
            elif not self.prompt_edit.toPlainText().strip():
                self.prompt_edit.setStyleSheet("border: 1px solid red")
                self.prompt_edit.setFocus()
            elif not self.due_time_edit.dateTime().isValid():
                self.due_time_edit.setStyleSheet("border: 1px solid red")
                self.due_time_edit.setFocus()
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

        # Accent Color
        layout.addWidget(QLabel("Accent Color:"))
        self.accent_color_button = QPushButton()
        self.accent_color_button.setStyleSheet(f"background-color: {self.parent.accent_color}")
        self.accent_color_button.setToolTip("Select accent color.")
        self.accent_color_button.clicked.connect(self.select_accent_color)
        layout.addWidget(self.accent_color_button)
        
        # Debug Enabled
        self.debug_enabled_checkbox = QCheckBox("Debug Enabled")
        self.debug_enabled_checkbox.setChecked(self.parent.debug_enabled)
        self.debug_enabled_checkbox.setToolTip("Enable or disable debug mode.")
        layout.addWidget(self.debug_enabled_checkbox)

        # Screenshot Interval
        layout.addWidget(QLabel("Screenshot Interval (s):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(self.parent.screenshot_interval)
        self.interval_spin.setToolTip(
            "Seconds between screenshots when desktop history is enabled."
        )
        layout.addWidget(self.interval_spin)

        # Summarization Threshold
        layout.addWidget(QLabel("Summarization Threshold:"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 200)
        self.threshold_spin.setValue(self.parent.summarization_threshold)
        self.threshold_spin.setToolTip(
            "Number of recent messages to keep before summarizing."
            " Set to 0 to disable summarization."
        )
        layout.addWidget(self.threshold_spin)

        # Ollama Port
        layout.addWidget(QLabel("Ollama Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(getattr(self.parent, "ollama_port", 11434))
        self.port_spin.setToolTip("Port used to connect to the Ollama server.")
        layout.addWidget(self.port_spin)

        # Error summary label
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red")
        layout.addWidget(self.error_label)

        # --- Ollama Updates ---
        update_label = QLabel("Update Ollama and Models:")
        layout.addWidget(update_label)

        update_layout = QHBoxLayout()
        self.update_ollama_button = QPushButton("Update Ollama")
        self.update_ollama_button.clicked.connect(self.update_ollama)
        update_layout.addWidget(self.update_ollama_button)

        self.model_combo = QComboBox()
        models = self.parent.agents_tab.global_agent_preferences.get(
            "available_models", []
        )
        if not models:
            self.parent.agents_tab.load_global_preferences()
            models = self.parent.agents_tab.global_agent_preferences.get(
                "available_models", []
            )
        self.model_combo.addItems(models)
        update_layout.addWidget(self.model_combo)

        self.update_model_button = QPushButton("Update Model")
        self.update_model_button.clicked.connect(self.update_selected_model)
        update_layout.addWidget(self.update_model_button)

        layout.addLayout(update_layout)

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.button_box.button(QDialogButtonBox.Ok)
        self.ok_button.setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Connect inputs to validation
        self.user_name_edit.textChanged.connect(self.validate_fields)
        self.interval_spin.valueChanged.connect(self.validate_fields)
        self.threshold_spin.valueChanged.connect(self.validate_fields)
        self.port_spin.valueChanged.connect(self.validate_fields)

        self.validate_fields()

    def select_user_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.user_color_button.setStyleSheet(f"background-color: {color.name()}")
            self.parent.user_color = color.name()

    def select_accent_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.accent_color_button.setStyleSheet(f"background-color: {color.name()}")
            self.parent.accent_color = color.name()

    def get_data(self):
        return {
            "dark_mode": self.dark_mode_checkbox.isChecked(),
            "user_name": self.user_name_edit.text().strip(),
            "user_color": self.parent.user_color,  # Color is already updated
            "accent_color": self.parent.accent_color,
            "debug_enabled": self.debug_enabled_checkbox.isChecked(),
            "screenshot_interval": self.interval_spin.value(),
            "summarization_threshold": self.threshold_spin.value(),
            "ollama_port": self.port_spin.value(),
        }

    def accept(self):
        self.validate_fields()
        if self.error_label.isVisible():
            return
        super().accept()

    def validate_fields(self):
        """Validate settings inputs and update UI state."""
        errors = []
        if not self.user_name_edit.text().strip():
            errors.append("User Name is required.")
        if not (1 <= self.interval_spin.value() <= 60):
            errors.append("Screenshot Interval must be 1-60.")
        if not (0 <= self.threshold_spin.value() <= 200):
            errors.append("Summarization Threshold must be 0-200.")
        if not (1 <= self.port_spin.value() <= 65535):
            errors.append("Ollama Port must be 1-65535.")

        self.ok_button.setEnabled(not errors)
        self.error_label.setText("\n".join(errors))
        self.error_label.setVisible(bool(errors))

    def update_ollama(self):
        """Run 'ollama update' and show the result."""
        try:
            result = subprocess.run(
                ["ollama", "update"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            if result.returncode == 0:
                output = (
                    result.stdout.strip()
                    or result.stderr.strip()
                    or "Update complete."
                )
                QMessageBox.information(self, "Ollama Update", output)
            else:
                error_msg = result.stderr.strip() or "Ollama update failed."
                QMessageBox.warning(self, "Ollama Update", error_msg)
        except FileNotFoundError:
            QMessageBox.warning(self, "Error", "Ollama executable not found.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to update Ollama: {e}")

    def update_selected_model(self):
        """Run 'ollama pull <model>' for the selected model."""
        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.warning(self, "Error", "No model selected.")
            return
        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            output = result.stdout.strip() or f"Model {model} updated."
            QMessageBox.information(self, "Model Update", output)
            self.parent.agents_tab.load_global_preferences()
        except FileNotFoundError:
            QMessageBox.warning(self, "Error", "Ollama executable not found.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to update model: {e}")


class SearchDialog(QDialog):
    """Dialog for searching conversation history."""

    def __init__(self, parent, conversation_text):
        super().__init__(parent)
        self.setWindowTitle("Search Conversation")
        self.conversation_lines = conversation_text.splitlines()
        self.chat_display = parent.chat_display

        layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type to search...")
        layout.addWidget(self.search_input)

        self.results_list = QListWidget()
        layout.addWidget(self.results_list)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.search_input.textChanged.connect(self.update_results)
        self.results_list.itemClicked.connect(self.highlight_message)

    def update_results(self):
        import re

        query = self.search_input.text().strip()
        self.results_list.clear()
        if not query:
            return

        pattern = re.compile(re.escape(query), re.I)
        for line in self.conversation_lines:
            if pattern.search(line):
                highlighted = pattern.sub(
                    lambda m: f"<span style='background-color:yellow'>{m.group(0)}</span>",
                    line.strip(),
                )
                item = QListWidgetItem()
                label = QLabel(highlighted)
                label.setTextFormat(Qt.RichText)
                self.results_list.addItem(item)
                self.results_list.setItemWidget(item, label)
                item.setData(Qt.UserRole, line.strip())

    def highlight_message(self, item):
        text = item.data(Qt.UserRole)
        if not text:
            return
        doc = self.chat_display.document()
        cursor = doc.find(text)
        if cursor.isNull():
            return
        self.chat_display.setTextCursor(cursor)
        self.chat_display.centerCursor()


class HistorySearchDialog(QDialog):
    """Dialog for searching saved chat history."""

    def __init__(self, parent, history):
        super().__init__(parent)
        self.setWindowTitle("Search Saved History")
        self.history = history

        layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search history...")
        layout.addWidget(self.search_input)

        self.results_list = QListWidget()
        layout.addWidget(self.results_list)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.search_input.textChanged.connect(self.update_results)

    def update_results(self):
        import re

        query = self.search_input.text().strip()
        self.results_list.clear()
        if not query:
            return

        pattern = re.compile(re.escape(query), re.I)
        for msg in self.history:
            content = msg.get("content", "")
            if not pattern.search(content):
                continue
            ts = msg.get("timestamp", "")[:19].replace("T", " ")
            speaker = "You" if msg.get("role") == "user" else msg.get("agent", "assistant")
            line = f"{ts} {speaker}: {content}"
            highlighted = pattern.sub(
                lambda m: f"<span style='background-color:yellow'>{m.group(0)}</span>",
                line,
            )
            item = QListWidgetItem()
            label = QLabel(highlighted)
            label.setTextFormat(Qt.RichText)
            self.results_list.addItem(item)
            self.results_list.setItemWidget(item, label)
            item.setData(Qt.UserRole, line)


def filter_messages(conversation_text, query):
    """Return conversation lines containing the query."""
    if not query:
        return []
    return [
        line
        for line in conversation_text.splitlines()
        if query.lower() in line.lower()
    ]

