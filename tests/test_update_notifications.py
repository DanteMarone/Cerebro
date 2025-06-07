import os
from PyQt5.QtWidgets import QApplication
import app

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def immediate_check(self, manual=False):
    self.show_notification("Update available: 1.1")


def test_check_for_updates(monkeypatch):
    monkeypatch.setattr(app.AIChatApp, "check_for_updates", immediate_check)

    app_instance = QApplication.instance() or QApplication([])
    window = app.AIChatApp()
    notes = []
    monkeypatch.setattr(
        window,
        "show_notification",
        lambda msg, type="info": notes.append(msg),
    )

    window.check_for_updates(True)
    app_instance.processEvents()
    assert any("Update available" in m for m in notes)
    window.tray_icon.hide()
    app_instance.quit()
