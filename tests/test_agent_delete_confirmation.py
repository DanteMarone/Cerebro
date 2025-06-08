import os
from PyQt5.QtWidgets import QApplication, QMessageBox
import tab_agents

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.tasks = []
        self.agents_data = {"a1": {}}
        self.deleted = None
    def delete_agent(self, name=None):
        self.deleted = name
        self.agents_data.pop(name, None)


def build_tab(dummy):
    tab = tab_agents.AgentsTab.__new__(tab_agents.AgentsTab)
    tab.parent_app = dummy
    tab.current_agent = "a1"
    tab.show_agent_list = lambda: None
    return tab


def test_delete_agent_warning(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = build_tab(dummy)
    captured = {}

    def fake_question(*args, **kwargs):
        captured['text'] = args[2]
        return QMessageBox.No

    monkeypatch.setattr(tab_agents.QMessageBox, "question", fake_question)
    tab.on_delete_agent_clicked()
    assert "assigned" not in captured['text']

    dummy.tasks = [{"agent_name": "a1"}, {"agent_name": "a1"}, {"agent_name": "b"}]
    tab = build_tab(dummy)
    monkeypatch.setattr(tab_agents.QMessageBox, "question", fake_question)
    tab.on_delete_agent_clicked()
    assert "2 tasks" in captured['text']
    app.quit()
