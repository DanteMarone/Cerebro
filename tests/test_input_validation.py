import os
from PyQt5.QtWidgets import QApplication
import tab_chat

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def show_notification(self, *a, **k):
        pass
    def export_chat_histories(self):
        pass
    def clear_chat_histories(self):
        pass
    def clear_chat(self):
        pass
    def send_message(self, msg):
        pass

def test_send_button_state():
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    tab.user_input.setPlainText("")
    tab.update_send_button_state()
    assert not tab.send_button.isEnabled()
    tab.user_input.setPlainText("hi")
    tab.update_send_button_state()
    assert tab.send_button.isEnabled()
    app.quit()
