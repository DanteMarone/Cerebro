# tab_tasks.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QHBoxLayout, QPushButton, QListWidgetItem,
    QLabel, QMessageBox, QDialog, QStyle, QAbstractItemView, QCalendarWidget,
    QInputDialog
)
from PyQt5.QtCore import Qt, QDate, QDateTime, QMimeData, QRect
from PyQt5.QtGui import QDrag, QTextCharFormat, QBrush, QColor
from dialogs import TaskDialog
from tasks import (
    add_task,
    edit_task,
    delete_task,
    set_task_status,
    update_task_due_time,
)


class TaskListWidget(QListWidget):
    """List widget that starts drags with the task ID."""

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item:
            return
        mime = QMimeData()
        mime.setText(item.data(Qt.UserRole))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)


class DroppableCalendarWidget(QCalendarWidget):
    """Calendar widget that accepts drops and shows task markers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.task_dates = set()

    def paintCell(self, painter, rect, date):
        """Customize painting to highlight today and mark task dates."""
        if date == QDate.currentDate():
            painter.save()
            painter.fillRect(rect, QColor("#ffffb3"))
            painter.restore()

        super().paintCell(painter, rect, date)

        if date in self.task_dates:
            painter.save()
            radius = 3
            dot_rect = QRect(
                rect.right() - radius * 2 - 2,
                rect.top() + 2,
                radius * 2,
                radius * 2,
            )
            painter.setBrush(QColor("red"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(dot_rect)
            painter.restore()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        task_id = event.mimeData().text()
        date = self.selectedDate()
        parent = self.parent()
        if hasattr(parent, "reschedule_task"):
            parent.reschedule_task(task_id, date)
        event.acceptProposedAction()

class TasksTab(QWidget):
    """
    Manages the display and interaction with scheduled tasks.
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.tasks = self.parent_app.tasks

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Tasks list
        self.tasks_list = TaskListWidget()
        self.tasks_list.setSelectionMode(QAbstractItemView.SingleSelection)  # Enforce single selection
        self.tasks_list.setDragEnabled(True)
        self.tasks_list.itemSelectionChanged.connect(self.on_item_selection_changed)
        self.tasks_list.itemDoubleClicked.connect(self.toggle_status_ui)
        self.layout.addWidget(self.tasks_list)

        # Calendar view
        self.calendar = DroppableCalendarWidget(self)
        self.calendar.activated.connect(self.on_date_activated)
        self.layout.addWidget(self.calendar)

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
        self.highlight_task_dates()

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
                repeat = t.get("repeat_interval", 0)
                repeat_str = f" every {repeat}m" if repeat else ""
                summary = f"[{due_time}] {agent_name}{repeat_str} ({status}) - {prompt[:30]}..."
                item.setText(summary)
                item.setData(Qt.UserRole, t['id'])  # Store the task ID in the item's data
                self.tasks_list.addItem(item)
        self.highlight_task_dates()

    def highlight_task_dates(self):
        """Update calendar decorations for task dates."""
        fmt_default = QTextCharFormat()
        self.calendar.setDateTextFormat(QDate(), fmt_default)  # clear formatting

        self.calendar.task_dates = set()
        for task in self.tasks:
            due = task.get("due_time")
            if not due:
                continue
            dt = QDateTime.fromString(due, Qt.ISODate)
            if not dt.isValid():
                dt = QDateTime.fromString(due, "yyyy-MM-dd HH:mm:ss")
            if dt.isValid():
                self.calendar.task_dates.add(dt.date())

        self.calendar.updateCells()

    def add_task_ui(self):
        """
        Display a dialog to add a new task.
        """
        dialog = TaskDialog(self, self.parent_app.agents_data)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            agent_name = data["agent_name"]
            prompt = data["prompt"]
            due_time = data["due_time"]
            repeat_interval = data.get("repeat_interval", 0)
            if not due_time:
                QMessageBox.warning(self, "Error", "Please specify a valid due time.")
                return
            add_task(
                self.tasks,
                agent_name,
                prompt,
                due_time,
                creator="user",
                repeat_interval=repeat_interval,
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
            self.parent_app.agents_data,
            task_id=task_id,
            agent_name=existing_task.get("agent_name", ""),
            prompt=existing_task.get("prompt", ""),
            due_time=existing_task.get("due_time", ""),
            repeat_interval=existing_task.get("repeat_interval", 0),
        )
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            err = edit_task(
                self.tasks,
                task_id,
                data["agent_name"],
                data["prompt"],
                data["due_time"],
                data.get("repeat_interval", 0),
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

    def on_date_activated(self, qdate):
        """Ask to mark tasks on the activated date as completed."""
        tasks_on_date = [t for t in self.tasks if self._task_date(t) == qdate]
        if not tasks_on_date:
            return
        reply = QMessageBox.question(
            self,
            "Mark Complete",
            f"Mark {len(tasks_on_date)} task(s) on {qdate.toString()} as completed?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for t in tasks_on_date:
                set_task_status(
                    self.tasks,
                    t["id"],
                    "completed",
                    debug_enabled=self.parent_app.debug_enabled,
                )
            self.refresh_tasks_list()

    def reschedule_task(self, task_id, qdate):
        """Reschedule the given task to the selected date."""
        task = next((t for t in self.tasks if t["id"] == task_id), None)
        if not task:
            return
        due = task.get("due_time", "")
        dt = QDateTime.fromString(due, Qt.ISODate)
        if not dt.isValid():
            dt = QDateTime.fromString(due, "yyyy-MM-dd HH:mm:ss")
        if not dt.isValid():
            dt = QDateTime(qdate, QDateTime.currentDateTime().time())
        else:
            dt.setDate(qdate)
        new_due = dt.toString(Qt.ISODate)
        update_task_due_time(
            self.tasks,
            task_id,
            new_due,
            debug_enabled=self.parent_app.debug_enabled,
        )
        self.refresh_tasks_list()

    @staticmethod
    def _task_date(task):
        due = task.get("due_time")
        if not due:
            return QDate()
        dt = QDateTime.fromString(due, Qt.ISODate)
        if not dt.isValid():
            dt = QDateTime.fromString(due, "yyyy-MM-dd HH:mm:ss")
        return dt.date() if dt.isValid() else QDate()
