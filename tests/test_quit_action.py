import os
from PyQt5.QtWidgets import QApplication
from app import AIChatApp

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_quit_from_tray(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = AIChatApp()
    called = {"flag": False}

    def fake_quit():
        called["flag"] = True

    monkeypatch.setattr(QApplication, "quit", staticmethod(fake_quit))
    window.quit_from_tray()
    assert called["flag"]
    assert window.force_quit
    app.quit()
