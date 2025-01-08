# tab_tasks.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QHBoxLayout, QPushButton, QListWidgetItem,
    QLabel, QMessageBox, QDialog
)
from dialogs import TaskDialog
from tasks import add_task, edit_task, delete_task

class TasksTab(QWidget):
    """
    Integrated version of Tasks management (previously TasksWindow).
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.tasks = self.parent_app.tasks
        self.agents_data = self.parent_app.agents_data

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Tasks list
        self.tasks_list = QListWidget()
        self.layout.addWidget(self.tasks_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Task")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        self.add_button.clicked.connect(self.add_task_ui)

        self.refresh_tasks_list()

    def refresh_tasks_list(self):
        """
        Refresh the tasks list in the UI.
        """
        self.tasks_list.clear()
        for t in self.tasks:
            item = QListWidgetItem()
            due_time = t.get("due_time", "")
            agent_name = t.get("agent_name", "")
            prompt = t.get("prompt", "")
            summary = f"[{due_time}] {agent_name} - {prompt[:30]}..."
            item.setText(summary)
            self.tasks_list.addItem(item)

            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(summary)
            edit_btn = QPushButton("Edit")
            del_btn = QPushButton("Delete")

            edit_btn.clicked.connect(lambda _, tid=t['id']: self.edit_task_ui(tid))
            del_btn.clicked.connect(lambda _, tid=t['id']: self.delete_task_ui(tid))

            h_layout.addWidget(label)
            h_layout.addWidget(edit_btn)
            h_layout.addWidget(del_btn)
            container.setLayout(h_layout)

            self.tasks_list.setItemWidget(item, container)

    def add_task_ui(self):
        """
        Display a dialog to add a new task.
        """
        dialog = TaskDialog(self, self.agents_data)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            agent_name = data["agent_name"]
            prompt = data["prompt"]
            due_time = data["due_time"]
            if not due_time:
                QMessageBox.warning(self, "Error", "Please specify a valid due time.")
                return
            add_task(
                self.tasks,
                agent_name,
                prompt,
                due_time,
                creator="user",
                debug_enabled=self.parent_app.debug_enabled
            )
            self.refresh_tasks_list()

    def edit_task_ui(self, task_id):
        """
        Display a dialog to edit an existing task.
        """
        existing_task = next((t for t in self.tasks if t["id"] == task_id), None)
        if not existing_task:
            QMessageBox.warning(self, "Error", f"No task with ID {task_id} found.")
            return
        dialog = TaskDialog(
            self,
            self.agents_data,
            task_id=task_id,
            agent_name=existing_task.get("agent_name", ""),
            prompt=existing_task.get("prompt", ""),
            due_time=existing_task.get("due_time", "")
        )
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            err = edit_task(
                self.tasks,
                task_id,
                data["agent_name"],
                data["prompt"],
                data["due_time"],
                debug_enabled=self.parent_app.debug_enabled
            )
            if err:
                QMessageBox.warning(self, "Error Editing Task", err)
            else:
                self.refresh_tasks_list()

    def delete_task_ui(self, task_id):
        """
        Delete a task after user confirmation.
        """
        reply = QMessageBox.question(
            self,
            'Confirm Delete',
            "Are you sure you want to delete this task?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            err = delete_task(self.tasks, task_id, debug_enabled=self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Deleting Task", err)
            else:
                self.refresh_tasks_list()
