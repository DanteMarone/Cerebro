import os
from PyQt5.QtWidgets import QApplication, QLabel
import tab_tasks

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.tasks = []
        self.agents_data = []
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
