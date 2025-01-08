#tab_chat.py
from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QStyle
)

class ChatTab(QWidget):
    """
    Encapsulates the chat UI: display, input, send/clear buttons.
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Chat display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setLineWrapMode(QTextEdit.WidgetWidth)  # Enable word wrap
        self.layout.addWidget(self.chat_display)

        # Input area
        self.user_input = QTextEdit()
        self.user_input.setPlaceholderText("Type your message here...")
        self.user_input.setMinimumHeight(30)  # Set minimum height
        self.user_input.setMaximumHeight(100)
        self.user_input.installEventFilter(self)
        self.layout.addWidget(self.user_input)

        # Button row
        btn_layout = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.send_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogApplyButton')))  # Add icon
        self.send_button.setToolTip("Send the message.")
        self.clear_chat_button = QPushButton("Clear Chat")
        self.clear_chat_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogDiscardButton')))
        self.clear_chat_button.setToolTip("Clear the chat history.")
        btn_layout.addWidget(self.send_button)
        btn_layout.addWidget(self.clear_chat_button)
        self.layout.addLayout(btn_layout)

        # Wire up signals
        self.send_button.clicked.connect(self.on_send_clicked)
        self.clear_chat_button.clicked.connect(self.on_clear_chat_clicked)
        self.user_input.textChanged.connect(self.adjust_input_height)

    def eventFilter(self, obj, event):
        """
        Capture Enter key in user_input for sending.
        """
        if obj == self.user_input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Return and not event.modifiers() & QtCore.Qt.ShiftModifier:
                self.on_send_clicked()
                return True
        return super().eventFilter(obj, event)

    def adjust_input_height(self):
        doc_height = self.user_input.document().size().height()
        new_height = int(doc_height + 10)
        self.user_input.setFixedHeight(min(new_height, 100))

    def on_send_clicked(self):
        """
        Send message to the AIChatApp logic.
        """
        user_text = self.user_input.toPlainText().strip()
        if not user_text:
            return
        self.user_input.clear()
        self.user_input.setFixedHeight(30)
        self.parent_app.send_message(user_text)

    def on_clear_chat_clicked(self):
        """
        Clear the chat display and the parent app's history.
        """
        self.parent_app.clear_chat()

    def append_message_html(self, html_text):
        """
        Append a new message (in HTML) to the chat display.
        """
        self.chat_display.append(html_text)
        # Ensure automatic scrolling to the bottom
        self.chat_display.verticalScrollBar().setValue(self.chat_display.verticalScrollBar().maximum())