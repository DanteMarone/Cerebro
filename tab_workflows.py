from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout,
    QDialog, QFormLayout, QLineEdit, QComboBox, QSpinBox, QTextEdit,
    QListWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt

import workflows


class WorkflowDialog(QDialog):
    def __init__(self, agents, workflow=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workflow")
        form = QFormLayout(self)

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

        self.agent_input = QLineEdit()
        if workflow:
            self.agent_input.setText(",".join(workflow.get("agents", [])))
        form.addRow("Agents", self.agent_input)

        self.turn_spin = QSpinBox()
        self.turn_spin.setMinimum(1)
        self.turn_spin.setMaximum(100)
        if workflow:
            self.turn_spin.setValue(workflow.get("max_turns", 10))
        form.addRow("Max Turns", self.turn_spin)

        self.steps_edit = QTextEdit()
        if workflow and workflow.get("steps"):
            lines = []
            for step in workflow["steps"]:
                lines.append(f"{step['agent']}|{step.get('model','')}|{step.get('system_prompt','')}")
            self.steps_edit.setPlainText("\n".join(lines))
        form.addRow("Steps", self.steps_edit)

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
        self.agent_input.setVisible(agent_managed)
        self.turn_spin.setVisible(agent_managed)
        self.steps_edit.setVisible(not agent_managed)

    def get_data(self):
        data = {
            "name": self.name_input.text().strip(),
            "type": "agent_managed" if self.type_combo.currentIndex() == 0 else "user_managed",
            "coordinator": self.coordinator_combo.currentText(),
            "agents": [a.strip() for a in self.agent_input.text().split(";") if a.strip()],
            "max_turns": self.turn_spin.value(),
            "steps": [],
        }
        if data["type"] == "user_managed":
            steps = []
            for line in self.steps_edit.toPlainText().splitlines():
                parts = [p.strip() for p in line.split("|")]
                if not parts or not parts[0]:
                    continue
                step = {"agent": parts[0]}
                if len(parts) > 1:
                    step["model"] = parts[1]
                if len(parts) > 2:
                    step["system_prompt"] = parts[2]
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
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.del_btn)
        layout.addLayout(btn_layout)

        self.add_btn.clicked.connect(self.add_workflow)
        self.edit_btn.clicked.connect(self.edit_workflow)
        self.del_btn.clicked.connect(self.delete_workflow)

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
            wf_id = workflows.add_workflow(self.workflows, **data)
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
