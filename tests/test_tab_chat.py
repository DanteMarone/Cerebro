import os
from PyQt5.QtWidgets import QApplication
import tab_chat

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


def test_append_message_bubble(tmp_path):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    tab.append_message_bubble("Tester", "hello", "#000000", align="left")
    html = tab.chat_display.toHtml()
    assert "Tester" in html
    assert "#000000" in html
    app.quit()
