import os
from PyQt5.QtWidgets import QApplication
from app import AIChatApp

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_tray_actions_exist():
    app = QApplication.instance() or QApplication([])
    window = AIChatApp()
    actions = {a.text() for a in window.tray_icon.contextMenu().actions()}
    expected = {
        "Open Cerebro",
        "New Task",
        "Toggle Dark Mode",
        "Pause Notifications",
        "Start Screenshot Capture",
        "Quit",
    }
    assert expected <= actions
    window.tray_icon.hide()
    app.quit()
