import os
from PyQt5.QtWidgets import QApplication
import tab_agents

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.agents_data = {"AgentA": {}, "AgentB": {}}
        self.nav_buttons = {}
        self.docs_tab = type("Dummy", (), {"doc_map": {}, "selector": None})()
    def change_tab(self, *args, **kwargs):
        pass

def test_get_agent_names():
    app_instance = QApplication.instance() or QApplication([])
    tab = tab_agents.AgentsTab(DummyApp())
    assert sorted(tab.get_agent_names()) == ["AgentA", "AgentB"]
    app_instance.quit()
