# dialogs.py

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QTextEdit, QLabel, QPushButton, QHBoxLayout
)

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

        from PyQt5.QtWidgets import QComboBox
        self.agent_selector = QComboBox()
        for a_name in self.agents_data.keys():
            self.agent_selector.addItem(a_name)
        if agent_name in self.agents_data:
            self.agent_selector.setCurrentText(agent_name)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(prompt)

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
