import os
from PyQt5.QtWidgets import QApplication
import tab_finetune

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_progress_updates():
    app = QApplication.instance() or QApplication([])
    tab = tab_finetune.FineTuneTab()
    tab.update_progress(42, "step")
    assert tab.progress_bar.value() == 42
    assert "step" in tab.log_edit.toPlainText()
    app.quit()


def test_cancel_stops_thread():
    app = QApplication.instance() or QApplication([])
    tab = tab_finetune.FineTuneTab()
    tab.start_fine_tune()
    assert tab.thread is not None
    tab.cancel_fine_tune()
    assert tab.thread is None
    app.quit()
