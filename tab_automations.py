from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout,
    QListWidgetItem, QLabel, QMessageBox, QInputDialog, QLineEdit, QStyle
)
from PyQt5.QtCore import Qt

from automation_sequences import (
    record_automation,
    add_automation,
    delete_automation,
    run_automation,
)


class AutomationsTab(QWidget):
    """Manage recorded automation sequences."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.automations = self.parent_app.automations

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self.list_widget)

        self.no_label = QLabel("No automations available.")
        self.no_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.no_label)
        self.no_label.hide()

        btn_layout = QHBoxLayout()
        self.record_btn = QPushButton("Record")
        self.record_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogYesButton')))
        btn_layout.addWidget(self.record_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_TrashIcon')))
        self.delete_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_btn)

        self.run_btn = QPushButton("Run")
        self.run_btn.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_MediaPlay')))
        self.run_btn.setEnabled(False)
        btn_layout.addWidget(self.run_btn)

        layout.addLayout(btn_layout)

        self.record_btn.clicked.connect(self.record_automation_ui)
        self.delete_btn.clicked.connect(self.delete_automation_ui)
        self.run_btn.clicked.connect(self.run_automation_ui)
        self.list_widget.itemSelectionChanged.connect(self.update_buttons)

        self.refresh_automations_list()

    def update_buttons(self):
        has_sel = bool(self.list_widget.selectedItems())
        self.delete_btn.setEnabled(has_sel)
        self.run_btn.setEnabled(has_sel)

    def refresh_automations_list(self):
        self.list_widget.clear()
        if not self.automations:
            self.no_label.show()
            return
        self.no_label.hide()
        for auto in self.automations:
            item = QListWidgetItem(auto.get("name", ""))
            self.list_widget.addItem(item)

    def record_automation_ui(self):
        name, ok = QInputDialog.getText(self, "Record Automation", "Name:")
        if not ok or not name.strip():
            return
        duration_str, ok = QInputDialog.getText(
            self, "Record Automation", "Duration (seconds):", QLineEdit.Normal, "5"
        )
        if not ok:
            return
        try:
            duration = float(duration_str)
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Duration must be a number.")
            return
        events = record_automation(duration)
        if not events:
            QMessageBox.warning(self, "Error", "Recording failed or pynput not installed.")
            return
        add_automation(self.parent_app.automations, name, events, self.parent_app.debug_enabled)
        self.automations = self.parent_app.automations
        self.refresh_automations_list()

    def delete_automation_ui(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        name = items[0].text()
        if QMessageBox.question(self, "Confirm Delete", f"Delete automation '{name}'?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        delete_automation(self.parent_app.automations, name, self.parent_app.debug_enabled)
        self.automations = self.parent_app.automations
        self.refresh_automations_list()

    def run_automation_ui(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        name = items[0].text()
        result = run_automation(self.parent_app.automations, name)
        QMessageBox.information(self, "Automation Result", result)
