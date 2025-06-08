# dialogs.py

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QColorDialog, QCheckBox, QSpinBox, QFormLayout, QDialogButtonBox,
    QComboBox, QTextEdit, QPlainTextEdit
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt

class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)

        if current_settings is None:
            current_settings = {}

        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()

        # Dark Mode
        self.dark_mode_checkbox = QCheckBox("Enable Dark Mode")
        self.dark_mode_checkbox.setChecked(current_settings.get("dark_mode", True))
        self.form_layout.addRow(QLabel("Theme:"), self.dark_mode_checkbox)

        # User Name
        self.user_name_edit = QLineEdit()
        self.user_name_edit.setText(current_settings.get("user_name", "You"))
        self.form_layout.addRow(QLabel("User Name:"), self.user_name_edit)

        # User Color
        self.user_color_button = QPushButton("Choose User Color")
        self.user_color_preview = QLabel()
        self.user_color_preview.setFixedSize(20, 20)
        self._user_color = QColor(current_settings.get("user_color", "#0000FF"))
        self._update_color_preview(self.user_color_preview, self._user_color)
        self.user_color_button.clicked.connect(lambda: self._choose_color('user'))
        user_color_layout = QHBoxLayout()
        user_color_layout.addWidget(self.user_color_button)
        user_color_layout.addWidget(self.user_color_preview)
        user_color_layout.addStretch()
        self.form_layout.addRow(QLabel("User Color:"), user_color_layout)

        # Accent Color
        self.accent_color_button = QPushButton("Choose Accent Color")
        self.accent_color_preview = QLabel()
        self.accent_color_preview.setFixedSize(20, 20)
        self._accent_color = QColor(current_settings.get("accent_color", "#803391"))
        self._update_color_preview(self.accent_color_preview, self._accent_color)
        self.accent_color_button.clicked.connect(lambda: self._choose_color('accent'))
        accent_color_layout = QHBoxLayout()
        accent_color_layout.addWidget(self.accent_color_button)
        accent_color_layout.addWidget(self.accent_color_preview)
        accent_color_layout.addStretch()
        self.form_layout.addRow(QLabel("Accent Color:"), accent_color_layout)
        
        # General Debug Mode (for console prints)
        self.debug_enabled_checkbox = QCheckBox("Enable General Debug Output (Console)")
        self.debug_enabled_checkbox.setChecked(current_settings.get("debug_enabled", True))
        self.form_layout.addRow(QLabel("General Debug:"), self.debug_enabled_checkbox)

        # Interactive Debugger Enabled
        self.debugger_interaction_enabled_checkbox = QCheckBox("Enable Interactive Debugger")
        self.debugger_interaction_enabled_checkbox.setChecked(current_settings.get("debugger_interaction_enabled", False))
        self.form_layout.addRow(QLabel("Interactive Debugger:"), self.debugger_interaction_enabled_checkbox)

        # Screenshot Interval
        self.screenshot_interval_spinbox = QSpinBox()
        self.screenshot_interval_spinbox.setRange(1, 300) # e.g., 1 to 300 seconds
        self.screenshot_interval_spinbox.setValue(current_settings.get("screenshot_interval", 5))
        self.screenshot_interval_spinbox.setSuffix(" seconds")
        self.form_layout.addRow(QLabel("Screenshot Interval:"), self.screenshot_interval_spinbox)

        # Summarization Threshold
        self.summarization_threshold_spinbox = QSpinBox()
        self.summarization_threshold_spinbox.setRange(5, 100) # e.g., 5 to 100 messages
        self.summarization_threshold_spinbox.setValue(current_settings.get("summarization_threshold", 20))
        self.summarization_threshold_spinbox.setSuffix(" messages")
        self.form_layout.addRow(QLabel("Summarization Threshold:"), self.summarization_threshold_spinbox)

        self.layout.addLayout(self.form_layout)

        # Dialog Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def _choose_color(self, color_type):
        current_color = self._user_color if color_type == 'user' else self._accent_color
        color = QColorDialog.getColor(current_color, self, f"Select {color_type.capitalize()} Color")
        if color.isValid():
            if color_type == 'user':
                self._user_color = color
                self._update_color_preview(self.user_color_preview, self._user_color)
            else: # accent
                self._accent_color = color
                self._update_color_preview(self.accent_color_preview, self._accent_color)

    def _update_color_preview(self, label, color):
        label.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #ccc;")

    def get_data(self):
        data = {
            "dark_mode": self.dark_mode_checkbox.isChecked(),
            "user_name": self.user_name_edit.text(),
            "user_color": self._user_color.name(),
            "accent_color": self._accent_color.name(),
            "debug_enabled": self.debug_enabled_checkbox.isChecked(),
            "debugger_interaction_enabled": self.debugger_interaction_enabled_checkbox.isChecked(), # Added
            "screenshot_interval": self.screenshot_interval_spinbox.value(),
            "summarization_threshold": self.summarization_threshold_spinbox.value()
        }
        return data

# Placeholder for WorkflowRunnerDialog if it was in dialogs.py
# class WorkflowRunnerDialog(QDialog): ...
# For now, assuming WorkflowRunnerDialog is correctly in its own file or app.py as per previous context.
# If it was meant to be in dialogs.py, its definition would go here.
# Based on app.py, it is imported from tab_workflows.py, so this is fine.
