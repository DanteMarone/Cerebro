import os
from PyQt5.QtWidgets import QApplication
import tab_chat

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.user_name = "User"
        self.agents_data = {}
        self.user_color = "#000000"
    def show_notification(self, message, type="info"):
        pass
    def export_chat_histories(self):
        pass
    def clear_chat_histories(self):
        pass
    def clear_chat(self):
        pass
    def send_message(self, msg):
        pass


def test_message_status_update():
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    msg_id = tab.append_message_html(
        "<span style='color:#000000'>[00:00] User:</span> hello", from_user=True
    )
    assert msg_id
    assert "⏳" in tab.chat_display.toHtml()
    tab.update_message_status(msg_id, "read")
    html = tab.chat_display.toHtml()
    assert "0000ff" in html
    app.quit()


def test_typing_indicator_name():
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    tab.show_typing_indicator("Alice")
    assert "Alice is typing" in tab.typing_indicator.text()
    tab.update_typing_indicator()
    assert "Alice is typing" in tab.typing_indicator.text()
    app.quit()
