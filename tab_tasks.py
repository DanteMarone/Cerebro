# tab_tasks.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QHBoxLayout, QPushButton, QListWidgetItem,
    QLabel, QMessageBox, QDialog, QStyle, QAbstractItemView
)
from PyQt5.QtCore import Qt  # Import Qt from PyQt5.QtCore
from dialogs import TaskDialog
from tasks import add_task, edit_task, delete_task, set_task_status

class TasksTab(QWidget):
    """
    Manages the display and interaction with scheduled tasks.
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
        self.tasks_list.setSelectionMode(QAbstractItemView.SingleSelection) # Enforce single selection
        self.tasks_list.itemSelectionChanged.connect(self.on_item_selection_changed)
        self.layout.addWidget(self.tasks_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Task")
        self.add_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileIcon')))
        self.add_button.setToolTip("Add a new task.")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        # Edit and Delete Buttons (initially hidden)
        self.edit_button = QPushButton("Edit")
        self.edit_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileDialogDetailedView')))
        self.edit_button.setToolTip("Edit the selected task.")
        self.edit_button.hide()
        btn_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_TrashIcon')))
        self.delete_button.setToolTip("Delete the selected task.")
        self.delete_button.hide()
        btn_layout.addWidget(self.delete_button)

        self.status_button = QPushButton("Toggle Status")
        self.status_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_BrowserReload')))
        self.status_button.setToolTip("Toggle between pending and completed.")
        self.status_button.hide()
        btn_layout.addWidget(self.status_button)

        # Connect signals
        self.add_button.clicked.connect(self.add_task_ui)
        self.edit_button.clicked.connect(self.edit_task_ui)
        self.delete_button.clicked.connect(self.delete_task_ui)
        self.status_button.clicked.connect(self.toggle_status_ui)

        self.refresh_tasks_list()

    def on_item_selection_changed(self):
        """
        Show or hide the Edit/Delete buttons based on whether an item is selected.
        """
        selected_items = self.tasks_list.selectedItems()
        if selected_items:
            self.edit_button.show()
            self.delete_button.show()
            self.status_button.show()
        else:
            self.edit_button.hide()
            self.delete_button.hide()
            self.status_button.hide()

    def refresh_tasks_list(self):
        """
        Refresh the tasks list in the UI.
        """
        self.tasks_list.clear()
        if not self.tasks:  # Check if the list is empty
            label = QLabel("No tasks available.")
            label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(label)
        else:
            for t in self.tasks:
                item = QListWidgetItem()
                due_time = t.get("due_time", "")
                agent_name = t.get("agent_name", "")
                prompt = t.get("prompt", "")
                status = t.get("status", "pending")
                summary = f"[{due_time}] {agent_name} ({status}) - {prompt[:30]}..."
                item.setText(summary)
                item.setData(Qt.UserRole, t['id'])  # Store the task ID in the item's data
                self.tasks_list.addItem(item)

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

    def edit_task_ui(self):
        """
        Display a dialog to edit an existing task.
        """
        selected_items = self.tasks_list.selectedItems()
        if not selected_items:
            return
        
        # Get the task ID from the selected item's data
        task_id = selected_items[0].data(Qt.UserRole)
        
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

    def delete_task_ui(self):
        """
        Delete a task after user confirmation.
        """
        selected_items = self.tasks_list.selectedItems()
        if not selected_items:
            return

        # Get the task ID from the selected item's data
        task_id = selected_items[0].data(Qt.UserRole)

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

    def toggle_status_ui(self):
        """Toggle the status of the selected task between pending and completed."""
        selected_items = self.tasks_list.selectedItems()
        if not selected_items:
            return

        task_id = selected_items[0].data(Qt.UserRole)
        task = next((t for t in self.tasks if t["id"] == task_id), None)
        if not task:
            QMessageBox.warning(self, "Error", f"No task with ID {task_id} found.")
            return

        new_status = "completed" if task.get("status") != "completed" else "pending"
        err = set_task_status(self.tasks, task_id, new_status, debug_enabled=self.parent_app.debug_enabled)
        if err:
            QMessageBox.warning(self, "Error Updating Status", err)
        else:
            if new_status == "completed":
                from metrics import record_task_completion
                record_task_completion(self.parent_app.metrics, task.get("agent_name", "unknown"), self.parent_app.debug_enabled)
                self.parent_app.refresh_metrics_display()
            self.refresh_tasks_list()
