import os
from datetime import datetime, timedelta
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


def test_format_helpers():
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    now = datetime.now()
    label_today = tab.format_date_label(now.date())
    label_yesterday = tab.format_date_label(now.date() - timedelta(days=1))
    assert label_today == "Today"
    assert label_yesterday == "Yesterday"
    ts_label, title = tab.format_timestamp(now - timedelta(minutes=5))
    assert ts_label == "5m ago"
    assert title.startswith(now.strftime("%Y-%m-%d"))
    app.quit()
