from PyQt5.QtCore import QObject, pyqtSignal, QThread
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTextEdit,
    QProgressBar, QHBoxLayout
)
import time


class FineTuneWorker(QObject):
    """Background worker that emits fine-tuning progress."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._cancelled = False

    def run(self):
        for pct in range(101):
            if self._cancelled:
                break
            self.progress.emit(pct, f"Completed {pct}%")
            time.sleep(0.05)
        self.finished.emit()

    def cancel(self):
        self._cancelled = True


class FineTuneTab(QWidget):
    """UI for managing model fine-tuning."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.thread = None

        layout = QVBoxLayout(self)
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Fine-Tune")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.cancel_btn)

        self.progress_bar = QProgressBar()
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)

        layout.addLayout(btn_layout)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_edit)

        self.start_btn.clicked.connect(self.start_fine_tune)
        self.cancel_btn.clicked.connect(self.cancel_fine_tune)

    def start_fine_tune(self):
        """Begin fine tuning in a separate thread."""
        if self.thread:
            return
        self.worker = FineTuneWorker()
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.finetune_finished)
        self.thread.started.connect(self.worker.run)
        self.thread.start()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

    def update_progress(self, pct, message):
        self.progress_bar.setValue(pct)
        self.log_edit.append(message)

    def finetune_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread.deleteLater()
            self.thread = None
        self.worker = None

    def cancel_fine_tune(self):
        if self.worker:
            self.worker.cancel()
        self.finetune_finished()
