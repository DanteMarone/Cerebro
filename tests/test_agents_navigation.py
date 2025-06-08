import os
from PyQt5.QtWidgets import QApplication, QPushButton
import tab_agents
import app as app_module

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.agents_data = {"agent": {"color": "#000000"}}
        self.tools = []
        self.automations = []
        self.tasks = []
        self.debug_enabled = False
    def add_agent(self):
        pass
    def save_agents(self):
        pass
    def update_send_button_state(self):
        pass
    def delete_agent(self, name):
        pass


def test_back_button_exists():
    app = QApplication.instance() or QApplication([])
    tab = tab_agents.AgentsTab(DummyApp())
    tab.edit_agent("agent")
    buttons = [b for b in tab.findChildren(QPushButton) if b.text() == "Back"]
    assert buttons
    app.quit()


def test_change_tab_trashes_unsaved(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = app_module.AIChatApp()
    window.agents_data = {"agent": {"color": "#000000"}}
    window.content_stack.setCurrentIndex(1)
    window.agents_tab.edit_agent("agent")
    window.agents_data["agent"]["color"] = "#FFFFFF"
    window.agents_tab.unsaved_changes = True
    window.change_tab(0)
    assert window.agents_data["agent"]["color"] == "#000000"
    app.quit()
