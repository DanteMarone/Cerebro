from PyQt5.QtWidgets import (
    QWidget, QFormLayout, QLabel, QComboBox, QLineEdit,
    QHBoxLayout, QPushButton, QFileDialog, QDoubleSpinBox, QSpinBox,
    QMessageBox, QVBoxLayout, QTextEdit, QDialog, QApplication, QProgressBar
)
import threading
from local_llm_helper import get_installed_models
from fine_tuning import start_fine_tune


class TrainingDialog(QDialog):
    """Dialog window to display training logs."""

    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Fine-tuning - {model}")
        layout = QVBoxLayout(self)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        btn_layout = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel)
        btn_layout.addWidget(self.cancel_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.stop_event = None

    def append_line(self, text: str) -> None:
        self.log_display.append(text)

    def set_progress(self, value: float) -> None:
        self.progress.setValue(int(value))

    def cancel(self) -> None:
        if self.stop_event and not self.stop_event.is_set():
            self.stop_event.set()
            self.cancel_btn.setDisabled(True)


class FinetuneTab(QWidget):
    """UI for fine-tuning language models."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        layout = QFormLayout(self)
        self.setLayout(layout)

        # Base model selection
        self.model_combo = QComboBox()
        self.refresh_models()
        layout.addRow(QLabel("Base Model:"), self.model_combo)

        self.name_edit = QLineEdit()
        layout.addRow("Model Name:", self.name_edit)

        # Training dataset path
        self.train_edit = QLineEdit()
        train_browse = QPushButton("Browse")
        train_browse.clicked.connect(self.browse_train)
        train_layout = QHBoxLayout()
        train_layout.addWidget(self.train_edit)
        train_layout.addWidget(train_browse)
        layout.addRow("Training Dataset:", train_layout)

        # Validation dataset path
        self.val_edit = QLineEdit()
        val_browse = QPushButton("Browse")
        val_browse.clicked.connect(self.browse_val)
        val_layout = QHBoxLayout()
        val_layout.addWidget(self.val_edit)
        val_layout.addWidget(val_browse)
        layout.addRow("Validation Dataset:", val_layout)

        # Hyperparameters
        self.lr_input = QDoubleSpinBox()
        self.lr_input.setDecimals(5)
        self.lr_input.setRange(0.00001, 1.0)
        self.lr_input.setSingleStep(0.0001)
        self.lr_input.setValue(0.0001)
        layout.addRow("Learning Rate:", self.lr_input)

        self.epochs_input = QSpinBox()
        self.epochs_input.setRange(1, 1000)
        self.epochs_input.setValue(3)
        layout.addRow("Epochs:", self.epochs_input)

        self.batch_input = QSpinBox()
        self.batch_input.setRange(1, 1024)
        self.batch_input.setValue(4)
        layout.addRow("Batch Size:", self.batch_input)

        self.train_btn = QPushButton("Start Training")
        self.train_btn.clicked.connect(self.start_training)
        layout.addRow(self.train_btn)

    def refresh_models(self):
        """Populate the model combo with installed models."""
        models = get_installed_models()
        self.model_combo.clear()
        self.model_combo.addItems(models)

    def browse_train(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Training Dataset")
        if path:
            self.train_edit.setText(path)

    def browse_val(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Validation Dataset")
        if path:
            self.val_edit.setText(path)

    def start_training(self):
        """Start fine-tuning using the selected options."""
        model = self.model_combo.currentText()
        train_path = self.train_edit.text().strip()
        model_name = self.name_edit.text().strip()
        if not model or not train_path:
            QMessageBox.warning(self, "Finetune", "Model and training dataset are required.")
            return

        params = {
            "learning_rate": self.lr_input.value(),
            "epochs": self.epochs_input.value(),
            "batch_size": self.batch_input.value(),
        }
        if model_name:
            params["output_dir"] = model_name

        dlg = TrainingDialog(model, self)
        dlg.show()
        stop_event = threading.Event()
        dlg.stop_event = stop_event

        def log(msg: str) -> None:
            dlg.append_line(msg)
            QApplication.processEvents()

        def progress(pct: float) -> None:
            dlg.set_progress(pct)
            QApplication.processEvents()

        thread = start_fine_tune(
            model,
            train_path,
            params,
            log_callback=log,
            progress_callback=progress,
            stop_event=stop_event,
            model_name=model_name or None,
        )
        dlg.finished.connect(stop_event.set)
        dlg.thread = thread
