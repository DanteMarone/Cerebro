# tab_tasks.py

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QHBoxLayout,
    QPushButton,
    QListWidgetItem,
    QLabel,
    QProgressBar,
    QMessageBox,
    QDialog,
    QMenu,
    QStyle,
    QAbstractItemView,
    QCalendarWidget,
    QInputDialog,
    QComboBox,
    QDateTimeEdit,
    QCheckBox,
    QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QDate, QDateTime, QMimeData, QRect
from datetime import timedelta
from PyQt5.QtGui import QDrag, QTextCharFormat, QBrush, QColor
from dialogs import TaskDialog
from tasks import (
    add_task,
    edit_task,
    delete_task,
    duplicate_task,
    set_task_status,
    update_task_agent,
    update_task_due_time,
    compute_task_progress,
    save_tasks,
    compute_task_times,
)

# Mapping of task status to display color and icon.
STATUS_STYLES = {
    "pending": {"color": "#3daee9", "icon": QStyle.SP_FileDialogNewFolder},
    "in_progress": {"color": "#ff9800", "icon": QStyle.SP_MediaPlay},
    "completed": {"color": "#4caf50", "icon": QStyle.SP_DialogApplyButton},
    "failed": {"color": "#f44336", "icon": QStyle.SP_MessageBoxWarning},
    "on_hold": {"color": "#9e9e9e", "icon": QStyle.SP_MediaPause},
}


class TaskListWidget(QListWidget):
    """List widget that supports reordering and external drags."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item:
            return
        mime = QMimeData()
        mime.setText(item.data(Qt.UserRole))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)

    def dropEvent(self, event):
        super().dropEvent(event)
        parent = self.parent()
        if hasattr(parent, "update_task_order"):
            parent.update_task_order()


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


class BulkEditDialog(QDialog):
    """Dialog to edit multiple tasks at once."""

    def __init__(self, parent, agents):
        super().__init__(parent)
        self.setWindowTitle("Bulk Edit Tasks")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Agent:"))
        self.agent_combo = QComboBox()
        self.agent_combo.addItem("(No Change)")
        self.agent_combo.addItems(agents)
        layout.addWidget(self.agent_combo)

        self.due_check = QCheckBox("Change Due Time")
        layout.addWidget(self.due_check)
        self.due_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setEnabled(False)
        layout.addWidget(self.due_edit)
        self.due_check.stateChanged.connect(
            lambda: self.due_edit.setEnabled(self.due_check.isChecked())
        )

        self.status_check = QCheckBox("Change Status")
        layout.addWidget(self.status_check)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["pending", "completed"])
        self.status_combo.setEnabled(False)
        layout.addWidget(self.status_combo)
        self.status_check.stateChanged.connect(
            lambda: self.status_combo.setEnabled(self.status_check.isChecked())
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        data = {}
        agent = self.agent_combo.currentText()
        if agent and agent != "(No Change)":
            data["agent_name"] = agent
        if self.due_check.isChecked():
            data["due_time"] = self.due_edit.dateTime().toString(Qt.ISODate)
        if self.status_check.isChecked():
            data["status"] = self.status_combo.currentText()
        return data

class TasksTab(QWidget):
    """
    Manages the display and interaction with scheduled tasks.
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.tasks = self.parent_app.tasks
        self.last_deleted_task = None

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Filter controls
        filter_layout = QHBoxLayout()
        self.agent_filter = QComboBox()
        self.agent_filter.setToolTip("Filter tasks by assignee")
        self.agent_filter.addItem("All Assignees")
        for name in getattr(self.parent_app, "agents_data", {}).keys():
            self.agent_filter.addItem(name)
        self.agent_filter.currentIndexChanged.connect(self.refresh_tasks_list)
        filter_layout.addWidget(self.agent_filter)

        self.status_filter = QComboBox()
        self.status_filter = QComboBox()
        self.status_filter.setToolTip("Filter tasks by status")
        self.status_filter.addItems([
            "All Statuses",
            "pending",
            "in_progress",
            "completed",
            "failed",
            "on_hold",
        ])
        self.status_filter.currentIndexChanged.connect(self.refresh_tasks_list)
        self.status_filter.currentIndexChanged.connect(self.refresh_tasks_list)
        filter_layout.addWidget(self.status_filter)
        self.layout.addLayout(filter_layout)

        # Tasks list
        self.tasks_list = TaskListWidget()
        self.tasks_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tasks_list.setDragEnabled(True)
        self.tasks_list.itemSelectionChanged.connect(self.on_item_selection_changed)
        self.tasks_list.itemDoubleClicked.connect(self.toggle_status_ui)
        self.tasks_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tasks_list.customContextMenuRequested.connect(self.show_tasks_context_menu)
        self.layout.addWidget(self.tasks_list)

        # Label shown when there are no tasks
        self.empty_label = QLabel("No tasks available.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.empty_label)

        # Calendar view
        self.calendar = DroppableCalendarWidget(self)
        self.calendar.activated.connect(self.on_date_activated)
        self.layout.addWidget(self.calendar)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("New Task")
        self.add_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileIcon')))
        self.add_button.setToolTip("Create a new task.")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        # Edit and Delete Buttons (initially hidden)
        self.edit_button = QPushButton("Edit")
        self.edit_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileDialogDetailedView')))
        self.edit_button.setToolTip("Edit the selected task.")
        self.edit_button.hide()
        btn_layout.addWidget(self.edit_button)

        self.bulk_edit_button = QPushButton("Bulk Edit")
        self.bulk_edit_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileDialogContentsView')))
        self.bulk_edit_button.setToolTip("Edit multiple tasks.")
        self.bulk_edit_button.hide()
        btn_layout.addWidget(self.bulk_edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_TrashIcon')))
        self.delete_button.setToolTip("Delete the selected task.")
        self.delete_button.hide()
        btn_layout.addWidget(self.delete_button)

        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileDialogNewFolder')))
        self.duplicate_button.setToolTip("Duplicate the selected task.")
        self.duplicate_button.hide()
        btn_layout.addWidget(self.duplicate_button)

        self.status_button = QPushButton("Toggle Status")
        self.status_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_BrowserReload')))
        self.status_button.setToolTip("Toggle between pending and completed.")
        self.status_button.hide()
        btn_layout.addWidget(self.status_button)

        # Connect signals
        self.add_button.clicked.connect(self.add_task_ui)
        self.edit_button.clicked.connect(self.edit_task_ui)
        self.bulk_edit_button.clicked.connect(self.bulk_edit_ui)
        self.delete_button.clicked.connect(self.delete_task_ui)
        self.duplicate_button.clicked.connect(self.duplicate_task_ui)
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
            self.duplicate_button.show()
            self.status_button.show()
            if len(selected_items) > 1:
                self.bulk_edit_button.show()
            else:
                self.bulk_edit_button.hide()
        else:
            self.edit_button.hide()
            self.delete_button.hide()
            self.duplicate_button.hide()
            self.status_button.hide()
            self.bulk_edit_button.hide()

    def refresh_tasks_list(self):
        """
        Refresh the tasks list in the UI.
        """
        self.tasks_list.clear()
        agent_filter = self.agent_filter.currentText()
        status_filter = self.status_filter.currentText()
        filtered = []
        for task in self.tasks:
            if agent_filter != "All Assignees" and task.get("agent_name") != agent_filter:
                continue
            if status_filter != "All Statuses" and task.get("status", "pending") != status_filter:
                continue
            filtered.append(task)

        if not filtered:
            self.tasks_list.hide()
            self.empty_label.show()
        else:
            self.empty_label.hide()
            for t in filtered:
                item = QListWidgetItem()
                row_widget = self._create_task_widget(t)
                item.setSizeHint(row_widget.sizeHint())
                item.setData(Qt.UserRole, t['id'])
                self.tasks_list.addItem(item)
                self.tasks_list.setItemWidget(item, row_widget)
            self.tasks_list.show()

        self.highlight_task_dates()

    def _create_task_widget(self, task):
        """Return a widget with summary text and action buttons for a task."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        due_time = task.get("due_time", "")
        agent_name = task.get("agent_name", "")
        prompt = task.get("prompt", "")
        status = task.get("status", "pending")
        repeat = task.get("repeat_interval", 0)
        repeat_str = f" every {repeat}m" if repeat else ""
        agent_combo = QComboBox()
        agent_combo.addItems(self.parent_app.agents_data.keys())
        agent_combo.setCurrentText(agent_name)
        agent_combo.setProperty("task_id", task["id"])
        agent_combo.currentTextChanged.connect(
            lambda val, tid=task["id"]: self.inline_set_agent(tid, val)
        )
        layout.addWidget(agent_combo)

        due_edit = QDateTimeEdit()
        dt = QDateTime.fromString(due_time, Qt.ISODate)
        if not dt.isValid():
            dt = QDateTime.fromString(due_time, "yyyy-MM-dd HH:mm:ss")
        if dt.isValid():
            due_edit.setDateTime(dt)
        due_edit.setCalendarPopup(True)
        due_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        due_edit.setProperty("task_id", task["id"])
        due_edit.editingFinished.connect(
            lambda tid=task["id"], widget=due_edit: self.inline_set_due(tid, widget.dateTime())
        )
        layout.addWidget(due_edit)

        summary_label = QLabel(f"{prompt[:30]}...{repeat_str} ({status})")
        tooltip = f"Assignee: {agent_name}\nStatus: {status}\nDue: {due_time}"
        reason = task.get("status_reason", "")
        action_hint = task.get("action_hint", "")
        link = task.get("error_link", "")
        if reason:
            tooltip += f"\nReason: {reason}"
        if action_hint:
            tooltip += f"\nAction: {action_hint}"
        summary_label.setToolTip(tooltip)
        layout.addWidget(summary_label)

        if reason and status in ("failed", "on_hold"):
            reason_label = QLabel(reason)
            color = "#f44336" if status == "failed" else "#9e9e9e"
            reason_label.setStyleSheet(f"color: {color}; font-weight: bold;")
            reason_label.setWordWrap(True)
            layout.addWidget(reason_label)
            if action_hint:
                hint_label = QLabel(action_hint)
                hint_label.setStyleSheet("font-style: italic;")
                hint_label.setWordWrap(True)
                layout.addWidget(hint_label)
            if link:
                link_label = QLabel(f'<a href="{link}">More Info</a>')
                link_label.setOpenExternalLinks(True)
                layout.addWidget(link_label)

        style = STATUS_STYLES.get(status, {"color": "black", "icon": QStyle.SP_FileIcon})
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel()
        icon = self.style().standardIcon(style["icon"])
        icon_label.setPixmap(icon.pixmap(16, 16))
        status_layout.addWidget(icon_label)
        text_label = QLabel(status.replace("_", " ").title())
        text_label.setStyleSheet(f"color: {style['color']}; font-weight: bold;")
        status_layout.addWidget(text_label)
        status_widget = QWidget()
        status_widget.setLayout(status_layout)
        layout.addWidget(status_widget)

        progress = compute_task_progress(task)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(progress)
        bar.setFixedWidth(100)
        layout.addWidget(bar)

        elapsed, remaining = compute_task_times(task)
        elapsed_label = QLabel(f"Elapsed: {timedelta(seconds=elapsed)}")
        remaining_label = QLabel(f"ETA: {timedelta(seconds=remaining)}")
        layout.addWidget(elapsed_label)
        layout.addWidget(remaining_label)

        edit_btn = QPushButton("Edit")
        edit_btn.setProperty("task_id", task["id"])
        edit_btn.clicked.connect(lambda _=False, tid=task["id"]: self.edit_task_ui(tid))
        layout.addWidget(edit_btn)

        dup_btn = QPushButton("Duplicate")
        dup_btn.setProperty("task_id", task["id"])
        dup_btn.clicked.connect(lambda _=False, tid=task["id"]: self.duplicate_task_ui(tid))
        layout.addWidget(dup_btn)

        del_btn = QPushButton("Delete")
        del_btn.setProperty("task_id", task["id"])
        del_btn.clicked.connect(lambda _=False, tid=task["id"]: self.delete_task_ui(tid))
        layout.addWidget(del_btn)

        status_btn = QPushButton("Complete" if status != "completed" else "Undo")
        status_btn.setProperty("task_id", task["id"])
        status_btn.clicked.connect(lambda _=False, tid=task["id"]: self.toggle_status_ui(tid))
        layout.addWidget(status_btn)

        return widget

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

    def edit_task_ui(self, task_id=None):
        """
        Display a dialog to edit an existing task.
        """
        if task_id is None:
            selected_items = self.tasks_list.selectedItems()
            if not selected_items:
                return
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

    def delete_task_ui(self, task_id=None):
        """
        Delete a task after user confirmation.
        """
        if task_id is None:
            selected_items = self.tasks_list.selectedItems()
            if not selected_items:
                return
            task_id = selected_items[0].data(Qt.UserRole)

        reply = QMessageBox.question(
            self,
            'Confirm Delete',
            "Are you sure you want to delete this task?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            idx = next((i for i, t in enumerate(self.tasks) if t["id"] == task_id), None)
            task_obj = next((t for t in self.tasks if t["id"] == task_id), None)
            err = delete_task(self.tasks, task_id, debug_enabled=self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Deleting Task", err)
            else:
                self.last_deleted_task = (task_obj, idx)
                self.refresh_tasks_list()
                msg = QMessageBox(self)
                msg.setWindowTitle("Task Deleted")
                msg.setText("Task moved to trash.")
                undo_button = msg.addButton("Undo", QMessageBox.ActionRole)
                msg.addButton(QMessageBox.Close)
                msg.exec_()
                if msg.clickedButton() == undo_button:
                    self.undo_delete()

    def undo_delete(self):
        if not hasattr(self, "last_deleted_task"):
            return
        task, idx = self.last_deleted_task
        if task:
            self.tasks.insert(idx, task)
            save_tasks(self.tasks, self.parent_app.debug_enabled)
            self.refresh_tasks_list()
        self.last_deleted_task = None

    def duplicate_task_ui(self, task_id=None):
        if task_id is None:
            selected_items = self.tasks_list.selectedItems()
            if not selected_items:
                return
            task_id = selected_items[0].data(Qt.UserRole)
        new_id = duplicate_task(self.tasks, task_id, debug_enabled=self.parent_app.debug_enabled)
        if new_id:
            self.refresh_tasks_list()

    def toggle_status_ui(self, task_id=None):
        """Toggle the status of the selected task between pending and completed."""
        if task_id is None:
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


    def inline_set_agent(self, task_id, agent_name):
        """Inline update of the task's agent."""
        update_task_agent(
            self.tasks, task_id, agent_name, debug_enabled=self.parent_app.debug_enabled
        )
        self.refresh_tasks_list()

    def inline_set_due(self, task_id, qdatetime):
        """Inline update of the task's due time."""
        due_str = qdatetime.toString(Qt.ISODate)
        update_task_due_time(
            self.tasks, task_id, due_str, debug_enabled=self.parent_app.debug_enabled
        )
        self.refresh_tasks_list()

    def bulk_edit_ui(self):
        """Edit multiple selected tasks at once."""
        selected_items = self.tasks_list.selectedItems()
        if len(selected_items) < 2:
            return
        ids = [it.data(Qt.UserRole) for it in selected_items]
        dialog = BulkEditDialog(self, list(self.parent_app.agents_data.keys()))
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            for tid in ids:
                if "agent_name" in data:
                    update_task_agent(
                        self.tasks, tid, data["agent_name"], debug_enabled=self.parent_app.debug_enabled
                    )
                if "due_time" in data:
                    update_task_due_time(
                        self.tasks, tid, data["due_time"], debug_enabled=self.parent_app.debug_enabled
                    )
                if "status" in data:
                    set_task_status(
                        self.tasks, tid, data["status"], debug_enabled=self.parent_app.debug_enabled
                    )
            self.refresh_tasks_list()

    def show_tasks_context_menu(self, pos):
        """Show context menu for the task under the cursor."""
        item = self.tasks_list.itemAt(pos)
        if not item:
            return
        task_id = item.data(Qt.UserRole)
        task = next((t for t in self.tasks if t["id"] == task_id), None)
        if not task:
            return
        menu = QMenu(self)
        menu.addAction("Edit", lambda tid=task_id: self.edit_task_ui(tid))
        menu.addAction("Delete", lambda tid=task_id: self.delete_task_ui(tid))
        status_text = "Mark Completed" if task.get("status") != "completed" else "Mark Pending"
        menu.addAction(status_text, lambda tid=task_id: self.toggle_status_ui(tid))
        menu.exec_(self.tasks_list.mapToGlobal(pos))

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

    def update_task_order(self):
        """Persist the current visual order of tasks."""
        ids = [self.tasks_list.item(i).data(Qt.UserRole) for i in range(self.tasks_list.count())]
        ordered = [next(t for t in self.tasks if t["id"] == tid) for tid in ids]
        self.tasks[:] = ordered
        save_tasks(self.tasks, self.parent_app.debug_enabled)
