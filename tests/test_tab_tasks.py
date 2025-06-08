import os
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QProgressBar,
    QMenu,
    QComboBox,
    QDateTimeEdit,
)
import tab_tasks

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.tasks = []
        self.agents_data = {}
        self.debug_enabled = False
        self.metrics = {}

    def refresh_metrics_display(self):
        pass


def test_refresh_empty_state():
    app = QApplication.instance() or QApplication([])
    tab = tab_tasks.TasksTab(DummyApp())
    tab.refresh_tasks_list()
    tab.refresh_tasks_list()
    labels = [w for w in tab.findChildren(QLabel) if w.text() == "No tasks available."]
    assert len(labels) == 1
    app.quit()


def test_filters_and_row_actions():
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    dummy.agents_data = {"a1": {}, "a2": {}}
    dummy.tasks = [
        {"id": "1", "agent_name": "a1", "prompt": "p1", "due_time": "2024-01-01", "status": "pending", "repeat_interval": 0},
        {"id": "2", "agent_name": "a2", "prompt": "p2", "due_time": "2024-01-01", "status": "completed", "repeat_interval": 0},
    ]
    tab = tab_tasks.TasksTab(dummy)

    tab.agent_filter.setCurrentText("a1")
    tab.refresh_tasks_list()
    assert tab.tasks_list.count() == 1

    tab.status_filter.setCurrentText("completed")
    tab.agent_filter.setCurrentText("All Assignees")
    tab.refresh_tasks_list()
    assert tab.tasks_list.count() == 1

    item_widget = tab.tasks_list.itemWidget(tab.tasks_list.item(0))
    buttons = item_widget.findChildren(QPushButton)
    assert len(buttons) == 4
    bars = item_widget.findChildren(QProgressBar)
    assert len(bars) == 1
    assert 0 <= bars[0].value() <= 100
    combos = item_widget.findChildren(QComboBox)
    edits = item_widget.findChildren(QDateTimeEdit)
    assert combos and edits
    assert (
        tab.tasks_list.selectionMode()
        == tab_tasks.QAbstractItemView.ExtendedSelection
    )
    app.quit()


def test_bulk_edit(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    dummy.agents_data = {"a1": {}, "a2": {}}
    dummy.tasks = [
        {"id": "1", "agent_name": "a1", "prompt": "p1", "due_time": "2024-01-01", "status": "pending", "repeat_interval": 0},
        {"id": "2", "agent_name": "a1", "prompt": "p2", "due_time": "2024-01-01", "status": "pending", "repeat_interval": 0},
    ]
    tab = tab_tasks.TasksTab(dummy)

    class FakeDlg:
        def exec_(self):
            return tab_tasks.QDialog.Accepted

        def get_data(self):
            return {"agent_name": "a2"}

    monkeypatch.setattr(tab_tasks, "BulkEditDialog", lambda *args, **kwargs: FakeDlg())
    tab.refresh_tasks_list()
    for i in range(2):
        tab.tasks_list.item(i).setSelected(True)
    tab.bulk_edit_ui()
    assert all(t["agent_name"] == "a2" for t in dummy.tasks)
    app.quit()


def test_context_menu(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    dummy.agents_data = {"a1": {}}
    dummy.tasks = [
        {"id": "1", "agent_name": "a1", "prompt": "p", "due_time": "2024-01-01", "status": "pending", "repeat_interval": 0}
    ]
    tab = tab_tasks.TasksTab(dummy)
    tab.refresh_tasks_list()

    captured = []

    def fake_exec_(self, *_args, **_kwargs):
        captured.extend([a.text() for a in self.actions()])

    monkeypatch.setattr(QMenu, "exec_", fake_exec_)
    item = tab.tasks_list.item(0)
    pos = tab.tasks_list.visualItemRect(item).center()
    tab.show_tasks_context_menu(pos)

    assert "Edit" in captured and "Delete" in captured
    assert any(t in captured for t in ["Mark Completed", "Mark Pending"])
    app.quit()


def test_failed_reason_display():
    """
    Tests that the reason, hint, and link for a failed task are displayed.
    (from codex/add-error-reason-and-suggestions-to-task-details)
    """
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    dummy.agents_data = {"a1": {}}
    dummy.tasks = [
        {
            "id": "1",
            "agent_name": "a1",
            "prompt": "p",
            "due_time": "2024-01-01",
            "status": "failed",
            "status_reason": "Agent offline",
            "action_hint": "Start the agent",
            "error_link": "http://example.com",
            "repeat_interval": 0,
        }
    ]
    tab = tab_tasks.TasksTab(dummy)
    tab.refresh_tasks_list()
    item_widget = tab.tasks_list.itemWidget(tab.tasks_list.item(0))
    # Find all QLabel widgets and check their text content
    texts = [w.text() for w in item_widget.findChildren(QLabel)]
    assert "Agent offline" in texts
    assert "Start the agent" in texts
    # Check for the link label, which contains HTML
    assert any('<a href="http://example.com">More Info</a>' in w.text() for w in item_widget.findChildren(QLabel))

def test_board_view_basic():
    """
    Tests that the board view displays tasks in the correct status column.
    (from main)
    """
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    dummy.agents_data = {"a1": {}}
    dummy.tasks = [
       {"id": "1", "agent_name": "a1", "prompt": "p1", "due_time": "2024-01-01", "status": "pending", "priority": 2, "repeat_interval": 0},
    ]
    tab = tab_tasks.TasksTab(dummy)
    # Switch to the Board View tab
    tab.view_tabs.setCurrentIndex(1)
    tab.refresh_board_view()
    # Check that the 'pending' column exists and has a task in it
    assert "pending" in tab.board_columns
    assert tab.board_columns["pending"].count() > 0
    app.quit()
