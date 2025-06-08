import os
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QProgressBar
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
    tab.agent_filter.setCurrentText("All Agents")
    tab.refresh_tasks_list()
    assert tab.tasks_list.count() == 1

    item_widget = tab.tasks_list.itemWidget(tab.tasks_list.item(0))
    buttons = item_widget.findChildren(QPushButton)
    assert len(buttons) == 4
    bars = item_widget.findChildren(QProgressBar)
    assert len(bars) == 1
    assert 0 <= bars[0].value() <= 100
    app.quit()
