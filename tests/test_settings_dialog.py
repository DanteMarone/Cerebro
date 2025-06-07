import os
from PyQt5.QtWidgets import QApplication, QWidget
import dialogs
import app

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyAgentsTab:
    def __init__(self):
        self.global_agent_preferences = {"available_models": []}
    def load_global_preferences(self):
        pass
    def update_model_dropdown(self):
        pass

class DummyManager:
    def __init__(self):
        self.started = None
        self.stopped = False
    def start(self, interval):
        self.started = interval
    def stop(self):
        self.stopped = True

class DummyAppBase:
    def __init__(self):
        self.dark_mode = False
        self.user_name = "You"
        self.user_color = "#0000FF"
        self.accent_color = "#803391"
        self.debug_enabled = False
        self.screenshot_interval = 5
        self.summarization_threshold = 20
        self.agents_tab = DummyAgentsTab()
        self.screenshot_manager = DummyManager()
        self.screenshot_paused = False
        self.agents_data = {"a": {"desktop_history_enabled": True}}
    def apply_updated_styles(self):
        pass
    def save_settings(self):
        pass
    def show_notification(self, *a, **k):
        pass


class DummyApp(DummyAppBase, QWidget):
    def __init__(self):
        QWidget.__init__(self)
        DummyAppBase.__init__(self)


def test_settings_dialog_returns_interval():
    app_instance = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    dlg = dialogs.SettingsDialog(dummy)
    dlg.interval_spin.setValue(8)
    dlg.threshold_spin.setValue(30)
    data = dlg.get_data()
    assert data["screenshot_interval"] == 8
    assert data["summarization_threshold"] == 30
    app_instance.quit()

def test_update_screenshot_timer_uses_global(monkeypatch):
    dummy = DummyAppBase()
    dummy.screenshot_interval = 7
    app.AIChatApp.update_screenshot_timer(dummy)
    assert dummy.screenshot_manager.started == 7

    dummy.screenshot_paused = True
    dummy.screenshot_manager = DummyManager()
    app.AIChatApp.update_screenshot_timer(dummy)
    assert dummy.screenshot_manager.stopped

    dummy.screenshot_paused = False
    dummy.agents_data = {}
    dummy.screenshot_manager = DummyManager()
    app.AIChatApp.update_screenshot_timer(dummy)
    assert dummy.screenshot_manager.stopped

