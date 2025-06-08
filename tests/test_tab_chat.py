import os
from PyQt5.QtWidgets import QApplication
import tab_chat
import app as app_module

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.notifications = []
    def show_notification(self, message, type="info"):
        self.notifications.append((message, type))
    def export_chat_histories(self):
        pass
    def clear_chat_histories(self):
        pass
    def clear_chat(self):
        pass
    def send_message(self, msg):
        pass


def test_save_conversation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    tab.chat_display.setPlainText("hello world")
    dest = tmp_path / "conv.txt"
    monkeypatch.setattr(tab_chat.QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), "txt"))
    tab.save_conversation()
    with open(dest, "r", encoding="utf-8") as f:
        assert f.read() == "hello world"
    assert dummy.notifications
    app.quit()


def test_send_button_updates_with_text(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = app_module.AIChatApp()
    window.agents_data = {
        "a": {"enabled": True, "desktop_history_enabled": False, "role": "Assistant"}
    }
    window.chat_tab.user_input.setPlainText("")
    window.update_send_button_state()
    assert not window.chat_tab.send_button.isEnabled()

    window.chat_tab.user_input.setPlainText("hi")
    window.update_send_button_state()
    assert window.chat_tab.send_button.isEnabled()
    window.close()
    app.quit()


def test_cannot_send_empty_message(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = app_module.AIChatApp()
    window.agents_data = {
        "a": {"enabled": True, "desktop_history_enabled": False, "role": "Assistant"}
    }
    called = []
    monkeypatch.setattr(window, "send_message", lambda msg: called.append(msg))
    window.chat_tab.user_input.setPlainText("")
    window.chat_tab.on_send_clicked()
    assert not called
    window.close()
    app.quit()
