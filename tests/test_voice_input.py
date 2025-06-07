import os
from PyQt5.QtWidgets import QApplication
import tab_chat

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DummyApp:
    def __init__(self):
        self.sent = []
        self.cleared = 0

    def show_notification(self, *a, **k):
        pass

    def export_chat_histories(self):
        pass

    def clear_chat_histories(self):
        pass

    def clear_chat(self):
        self.cleared += 1

    def send_message(self, msg):
        self.sent.append(msg)


def test_voice_insert(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    monkeypatch.setattr(tab_chat.voice_input, "recognize_speech", lambda timeout=5: "hello")
    tab.on_voice_clicked()
    assert tab.user_input.toPlainText() == "hello"
    app.quit()


def test_voice_commands(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    tab.user_input.setPlainText("hi")
    monkeypatch.setattr(tab_chat.voice_input, "recognize_speech", lambda timeout=5: "send")
    tab.on_voice_clicked()
    assert dummy.sent == ["hi"]
    monkeypatch.setattr(tab_chat.voice_input, "recognize_speech", lambda timeout=5: "clear chat")
    tab.on_voice_clicked()
    assert dummy.cleared == 1
    app.quit()
