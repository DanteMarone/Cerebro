from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QPushButton,
    QHBoxLayout,
    QDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QListWidgetItem,
    QMessageBox,
    QLabel,
    QTextEdit,
)
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

import workflows


class StepWidget(QWidget):
    """Widget for configuring a single workflow step."""

    def __init__(self, agents, step=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        self.agent_combo = QComboBox()
        self.agent_combo.addItems(sorted(agents))
        self.prompt_edit = QLineEdit()
        if step:
            self.agent_combo.setCurrentText(step.get("agent", ""))
            self.prompt_edit.setText(step.get("prompt", step.get("system_prompt", "")))
        layout.addWidget(QLabel("Agent"))
        layout.addWidget(self.agent_combo)
        layout.addWidget(QLabel("Prompt"))
        layout.addWidget(self.prompt_edit)


class PromptDialog(QDialog):
    """Prompt dialog for starting a workflow."""

    def __init__(self, workflow_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Run {workflow_name}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Initial Prompt"))
        self.prompt_edit = QLineEdit()
        layout.addWidget(self.prompt_edit)
        start_btn = QPushButton("Start Workflow")
        start_btn.clicked.connect(self.accept)
        layout.addWidget(start_btn)

    def get_prompt(self):
        return self.prompt_edit.text().strip()


class WorkflowRunnerDialog(QDialog):
    """Simple window to show workflow execution logs."""

    def __init__(self, workflow_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Workflow Runner - {workflow_name}")
        layout = QVBoxLayout(self)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def append_line(self, text):
        self.log_display.append(text)


class WorkflowDialog(QDialog):
    """Dialog for creating or editing workflows."""

    def __init__(self, agents, workflow=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workflow")
        form = QFormLayout(self)

        self.agents = agents
        self.step_widgets = []

        self.name_input = QLineEdit(workflow.get("name", "") if workflow else "")
        form.addRow("Name", self.name_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Agent Managed", "User Managed"])
        if workflow:
            idx = 0 if workflow.get("type") == "agent_managed" else 1
            self.type_combo.setCurrentIndex(idx)
        form.addRow("Type", self.type_combo)

        self.coordinator_combo = QComboBox()
        self.coordinator_combo.addItems(sorted(agents))
        if workflow:
            self.coordinator_combo.setCurrentText(workflow.get("coordinator", ""))
        form.addRow("Coordinator", self.coordinator_combo)

        self.agent_list = QListWidget()
        for name in sorted(agents):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.agent_list.addItem(item)
        if workflow:
            for i in range(self.agent_list.count()):
                item = self.agent_list.item(i)
                if item.text() in workflow.get("agents", []):
                    item.setCheckState(Qt.Checked)
        form.addRow("Agents", self.agent_list)

        self.turn_spin = QSpinBox()
        self.turn_spin.setMinimum(1)
        self.turn_spin.setMaximum(100)
        if workflow:
            self.turn_spin.setValue(workflow.get("max_turns", 10))
        form.addRow("Max Turns", self.turn_spin)

        self.steps_spin = QSpinBox()
        self.steps_spin.setMinimum(1)
        self.steps_spin.setMaximum(20)
        self.steps_spin.valueChanged.connect(self.sync_step_widgets)
        form.addRow("Steps", self.steps_spin)

        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        form.addRow(self.steps_container)

        if workflow and workflow.get("steps"):
            self.steps_spin.setValue(len(workflow["steps"]))
            for step in workflow["steps"]:
                self.add_step_widget(step)
        else:
            self.add_step_widget()

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        form.addRow(btn_layout)

        self.type_combo.currentIndexChanged.connect(self.update_visibility)
        self.update_visibility()

    def update_visibility(self):
        agent_managed = self.type_combo.currentIndex() == 0
        self.coordinator_combo.setVisible(agent_managed)
        self.agent_list.setVisible(agent_managed)
        self.turn_spin.setVisible(agent_managed)
        self.steps_spin.setVisible(not agent_managed)
        self.steps_container.setVisible(not agent_managed)
        for widget in self.step_widgets:
            widget.setVisible(not agent_managed)

    def add_step_widget(self, step=None):
        widget = StepWidget(self.agents, step=step)
        self.steps_layout.addWidget(widget)
        self.step_widgets.append(widget)

    def sync_step_widgets(self):
        count = self.steps_spin.value()
        while len(self.step_widgets) < count:
            self.add_step_widget()
        while len(self.step_widgets) > count:
            widget = self.step_widgets.pop()
            self.steps_layout.removeWidget(widget)
            widget.deleteLater()

    def get_data(self):
        data = {
            "name": self.name_input.text().strip(),
            "type": "agent_managed" if self.type_combo.currentIndex() == 0 else "user_managed",
            "coordinator": self.coordinator_combo.currentText(),
            "agents": [
                self.agent_list.item(i).text()
                for i in range(self.agent_list.count())
                if self.agent_list.item(i).checkState() == Qt.Checked
            ],
            "max_turns": self.turn_spin.value(),
            "steps": [],
        }
        if data["type"] == "user_managed":
            steps = []
            for widget in self.step_widgets:
                step = {
                    "agent": widget.agent_combo.currentText(),
                    "prompt": widget.prompt_edit.text().strip(),
                }
                steps.append(step)
            data["steps"] = steps
        return data


class WorkflowsTab(QWidget):
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.workflows = parent_app.workflows
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Workflow")
        self.edit_btn = QPushButton("Edit")
        self.del_btn = QPushButton("Delete")
        self.run_btn = QPushButton("Run")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.del_btn)
        btn_layout.addWidget(self.run_btn)
        layout.addLayout(btn_layout)

        self.add_btn.clicked.connect(self.add_workflow)
        self.edit_btn.clicked.connect(self.edit_workflow)
        self.del_btn.clicked.connect(self.delete_workflow)
        self.run_btn.clicked.connect(self.run_workflow)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        for wf in self.workflows:
            item = QListWidgetItem(f"{wf['name']} ({wf['type']})")
            item.setData(Qt.UserRole, wf['id'])
            self.list_widget.addItem(item)

    def add_workflow(self):
        dlg = WorkflowDialog(self.parent_app.agents_data.keys(), parent=self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            if not data["name"]:
                QMessageBox.warning(self, "Invalid", "Name is required")
                return
            wf_type = data.pop("type")
            wf_id = workflows.add_workflow(self.workflows, wf_type=wf_type, **data)
            self.parent_app.workflows = self.workflows
            self.refresh_list()

    def edit_workflow(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        wf_id = item.data(Qt.UserRole)
        wf = next((w for w in self.workflows if w['id'] == wf_id), None)
        if not wf:
            return
        dlg = WorkflowDialog(self.parent_app.agents_data.keys(), workflow=wf, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            workflows.edit_workflow(self.workflows, wf_id, **data)
            self.parent_app.workflows = self.workflows
            self.refresh_list()

    def delete_workflow(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        wf_id = item.data(Qt.UserRole)
        if QMessageBox.question(self, "Confirm", "Delete workflow?") == QMessageBox.Yes:
            workflows.delete_workflow(self.workflows, wf_id)
            self.parent_app.workflows = self.workflows
            self.refresh_list()

    def run_workflow(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        wf_id = item.data(Qt.UserRole)
        wf = next((w for w in self.workflows if w['id'] == wf_id), None)
        if not wf:
            return
        prompt_dlg = PromptDialog(wf['name'], self)
        if prompt_dlg.exec_() != QDialog.Accepted:
            return
        start_prompt = prompt_dlg.get_prompt()
        runner = WorkflowRunnerDialog(wf['name'], self)
        runner.show()
        log, result = workflows.execute_workflow(wf, start_prompt, self.parent_app.agents_data)
        for line in log:
            runner.append_line(line)
            QApplication.processEvents()
        QMessageBox.information(self, "Workflow Result", result)
