from PyQt5.QtWidgets import (
    QWidget, QFormLayout, QLabel, QComboBox, QLineEdit,
    QHBoxLayout, QPushButton, QFileDialog, QDoubleSpinBox, QSpinBox,
    QMessageBox
)
from local_llm_helper import get_installed_models


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
        """Placeholder for starting the training process."""
        QMessageBox.information(self, "Finetune", "Training not yet implemented.")

