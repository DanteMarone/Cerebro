import os
from PyQt5.QtWidgets import QApplication
from app import AIChatApp

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_tray_actions_exist():
    app = QApplication.instance() or QApplication([])
    window = AIChatApp()
    actions = {a.text() for a in window.tray_icon.contextMenu().actions()}
    assert {"Open Cerebro", "Add Task", "Toggle Dark Mode", "Quit"} <= actions
    window.tray_icon.hide()
    app.quit()
