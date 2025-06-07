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
    assert tab.model_combo.isEditable()
    assert tab.lr_input.value() > 0
    app.quit()


def test_model_name_passthrough(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(tab_finetune, "get_installed_models", lambda: ["m"])
    captured = {}

    def dummy_start(*args, **kwargs):
        captured.update({"args": args, "kwargs": kwargs})
        class DummyThread:
            def join(self):
                pass
        return DummyThread()

    monkeypatch.setattr(tab_finetune, "start_fine_tune", dummy_start)
    tab = tab_finetune.FinetuneTab(DummyApp())
    tab.train_edit.setText("train.json")
    tab.name_edit.setText("named-model")
    tab.start_training()
    assert captured["kwargs"].get("model_name") == "named-model"
    assert captured["args"][2]["output_dir"] == "named-model"
    app.quit()

