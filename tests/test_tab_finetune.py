import os
from PyQt5.QtWidgets import QApplication
import tab_finetune

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    pass

def test_combo_populated(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(tab_finetune, "get_installed_models", lambda: ["m1", "m2"])
    tab = tab_finetune.FinetuneTab(DummyApp())
    assert tab.model_combo.count() == 2
    assert tab.lr_input.value() > 0
    app.quit()

