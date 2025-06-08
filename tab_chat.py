#tab_chat.py
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QStyle,
    QLabel, QSplitter, QFrame, QScrollArea, QToolButton, QMenu, QAction,
    QFileDialog, QToolTip
)

from dialogs import SearchDialog, HistorySearchDialog
from transcripts import load_history
import voice_input

class ChatTab(QWidget):
    """
    Encapsulates the chat UI: display, input, send/clear buttons.
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.user_avatar = "\N{slightly smiling face}"
        self.typing_dots_count = 0
        self.typing_timer = None
        self.message_counter = 0
        self.last_user_message_id = None
        self.typing_name = "Assistant"

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # Create a splitter for chat display and input areas
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        
        # Chat display with container to handle styling
        self.chat_container = QWidget()
        self.chat_container.setObjectName("chatContainer")
        chat_container_layout = QVBoxLayout(self.chat_container)
        chat_container_layout.setContentsMargins(10, 10, 10, 10)
        
        # Header with title and toolbar
        header = QWidget()
        header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        title = QLabel("Conversation")
        title.setObjectName("chatTitle")
        header_layout.addWidget(title)
        
        # Spacer to push buttons to right
        header_layout.addStretch(1)
        
        # Add search button
        search_btn = QToolButton()
        search_btn.setObjectName("chatToolButton")
        search_icon = self.style().standardIcon(QStyle.SP_FileDialogContentsView)
        search_btn.setIcon(search_icon)
        search_btn.setToolTip("Search conversation")
        header_layout.addWidget(search_btn)
        
        # Add options button with menu
        options_btn = QToolButton()
        options_btn.setObjectName("chatToolButton")
        options_btn.setText("⋮")
        options_btn.setToolTip("More options")
        options_menu = QMenu(self)
        
        # Menu actions
        copy_action = QAction("Copy conversation", self)
        copy_action.triggered.connect(self.copy_conversation)
        options_menu.addAction(copy_action)
        
        save_action = QAction("Save conversation", self)
        save_action.triggered.connect(self.save_conversation)
        options_menu.addAction(save_action)
        
        options_menu.addSeparator()
        
        clear_action = QAction("Clear conversation", self)
        clear_action.triggered.connect(self.on_clear_chat_clicked)
        options_menu.addAction(clear_action)

        export_hist_action = QAction("Export history", self)
        export_hist_action.triggered.connect(self.parent_app.export_chat_histories)
        options_menu.addAction(export_hist_action)

        search_hist_action = QAction("Search saved history", self)
        search_hist_action.triggered.connect(self.show_history_search)
        options_menu.addAction(search_hist_action)

        clear_hist_action = QAction("Clear saved history", self)
        clear_hist_action.triggered.connect(self.parent_app.clear_chat_histories)
        options_menu.addAction(clear_hist_action)
        
        options_btn.setMenu(options_menu)
        options_btn.setPopupMode(QToolButton.InstantPopup)
        header_layout.addWidget(options_btn)
        
        chat_container_layout.addWidget(header)
        
        # Add separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setObjectName("chatSeparator")
        chat_container_layout.addWidget(separator)
        
        # Chat display with scroll capability
        chat_scroll_area = QScrollArea()
        chat_scroll_area.setWidgetResizable(True)
        chat_scroll_area.setObjectName("chatScrollArea")
        chat_scroll_area.setFrameShape(QFrame.NoFrame)
        
        chat_scroll_content = QWidget()
        chat_scroll_layout = QVBoxLayout(chat_scroll_content)
        chat_scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        self.chat_display = QTextEdit()
        self.chat_display.setObjectName("chatDisplay")
        self.chat_display.setReadOnly(True)
        self.chat_display.setLineWrapMode(QTextEdit.WidgetWidth)  # Enable word wrap
        chat_scroll_layout.addWidget(self.chat_display)
        
        chat_scroll_area.setWidget(chat_scroll_content)
        chat_container_layout.addWidget(chat_scroll_area)
        
        # Typing indicator
        self.typing_indicator = QLabel("")
        self.typing_indicator.setObjectName("typingIndicator")
        self.typing_indicator.hide()
        chat_container_layout.addWidget(self.typing_indicator)
        
        self.splitter.addWidget(self.chat_container)
        
        # Input area with container for styling
        input_container = QWidget()
        input_container.setObjectName("inputContainer")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(10, 10, 10, 10)
        
        # Input field
        self.user_input = QTextEdit()
        self.user_input.setObjectName("userInput")
        self.user_input.setPlaceholderText("Type your message here...")
        # Increase minimum height so placeholder text isn't cropped
        self.user_input.setMinimumHeight(50)
        self.user_input.setMaximumHeight(100)
        self.user_input.installEventFilter(self)
        input_layout.addWidget(self.user_input)
        
        # Button row
        btn_layout = QHBoxLayout()
        input_layout.addLayout(btn_layout)
        
        # Add stretcher to push buttons to the right
        btn_layout.addStretch()
        
        # Helper text for keyboard shortcut
        shortcut_label = QLabel("Press Enter to send, Shift+Enter for new line")
        shortcut_label.setObjectName("shortcutLabel")
        btn_layout.addWidget(shortcut_label)
        
        btn_layout.addStretch()
        
        # Create send button with modern styling
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.setEnabled(False)
        icon = self.style().standardIcon(QStyle.SP_ArrowRight)
        self.send_button.setIcon(icon)
        self.send_button.setIconSize(QtCore.QSize(16, 16))
        self.send_button.setToolTip("Send the message (Enter)")
        btn_layout.addWidget(self.send_button)

        # Voice input button
        self.voice_button = QPushButton("\U0001F3A4")
        self.voice_button.setObjectName("voiceButton")
        self.voice_button.setToolTip("Dictate a prompt or command")
        btn_layout.addWidget(self.voice_button)

        # Create clear button
        self.clear_chat_button = QPushButton("Clear")
        self.clear_chat_button.setObjectName("clearButton")
        self.clear_chat_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogDiscardButton')))
        self.clear_chat_button.setToolTip("Clear the chat history (Ctrl+L)")
        btn_layout.addWidget(self.clear_chat_button)
        
        self.splitter.addWidget(input_container)
        
        # Set initial splitter sizes
        self.splitter.setSizes([700, 100])
        self.layout.addWidget(self.splitter)
        
        # Wire up signals
        self.send_button.clicked.connect(self.on_send_clicked)
        self.clear_chat_button.clicked.connect(self.on_clear_chat_clicked)
        self.voice_button.clicked.connect(self.on_voice_clicked)
        self.user_input.textChanged.connect(self.adjust_input_height)
        self.user_input.textChanged.connect(self.update_send_button_state)
        search_btn.clicked.connect(self.show_search)

    def eventFilter(self, obj, event):
        """
        Capture Enter key in user_input for sending.
        """
        if obj == self.user_input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Return and not event.modifiers() & QtCore.Qt.ShiftModifier:
                if not self.user_input.toPlainText().strip():
                    # Show a tooltip
                    tooltip_duration = 2000 # milliseconds
                    tooltip_position = self.user_input.mapToGlobal(self.user_input.rect().bottomLeft())
                    QToolTip.showText(tooltip_position, "Cannot send an empty message", self.user_input, self.user_input.rect(), tooltip_duration)
                    return True # Event handled, don't proceed to send
                self.on_send_clicked()
                return True
        return super().eventFilter(obj, event)

    def update_send_button_state(self):
        """Enable or disable the send button based on input field content."""
        user_text = self.user_input.toPlainText().strip()
        if not user_text:
            self.send_button.setEnabled(False)
        else:
            self.send_button.setEnabled(True)

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
        self.user_input.setFixedHeight(40)
        self.parent_app.send_message(user_text)

    def on_clear_chat_clicked(self):
        """
        Clear the chat display and the parent app's history.
        """
        self.parent_app.clear_chat()

    def on_voice_clicked(self):
        """Capture voice input and act on commands."""
        text = voice_input.recognize_speech()
        if text.startswith("[Speech Recognition Error]"):
            self.parent_app.show_notification(text, "error")
            return

        command = text.strip().lower()
        if command in {"send", "send message"}:
            self.on_send_clicked()
        elif command in {"clear chat", "clear conversation"}:
            self.on_clear_chat_clicked()
        else:
            if self.user_input.toPlainText():
                self.user_input.insertPlainText(" " + text)
            else:
                self.user_input.setPlainText(text)
            self.adjust_input_height()

    def append_message_html(self, html_text, from_user=False):
        """Append a new message with simple avatar styling.

        If ``from_user`` is True a status span will be added and the message id
        returned so the status can be updated later.
        """
        import re
        pattern1 = r'<span style="color:(#[0-9A-Fa-f]{6});">\[([0-9:]+)\]\s*(.+?):</span>\s*(.*)'
        pattern2 = r'\[([0-9:]+)\]\s*<span style=\'color:(#[0-9A-Fa-f]{6});\'>(.+?):</span>\s*(.*)'
        m = re.match(pattern1, html_text, re.S)
        if m:
            color, timestamp, name, message = m.groups()
        else:
            m = re.match(pattern2, html_text, re.S)
            if m:
                timestamp, color, name, message = m.groups()
        if m:
            avatar = self.get_avatar(name)
            is_user = name.startswith(self.parent_app.user_name)
            align = "flex-end" if is_user else "flex-start"
            bubble_bg = "#e0e0e0" if is_user else "#444444"
            text_color = "#000000" if is_user else "#ffffff"
            avatar_html = (
                f"<div style='font-size:20px;margin-{'left' if is_user else 'right'}:6px;'>{avatar}</div>"
            )
            bubble_html = (
                f"<div style='background-color:{bubble_bg};color:{text_color};padding:6px;border-radius:10px;max-width:80%;'>"
                f"<div style='font-size:10px;color:gray'>[{timestamp}] {name}</div>{message}</div>"
            )
            if is_user:
                html_text = f"<div style='display:flex;justify-content:{align};margin:4px;'>{bubble_html}{avatar_html}</div>"
            else:
                html_text = f"<div style='display:flex;justify-content:{align};margin:4px;'>{avatar_html}{bubble_html}</div>"

        msg_id = None
        if from_user:
            self.message_counter += 1
            msg_id = f"msg{self.message_counter}"
            html_text += f" <a name='{msg_id}'></a>⏳"
            self.last_user_message_id = msg_id

        self.chat_display.append(html_text)
        self.chat_display.verticalScrollBar().setValue(self.chat_display.verticalScrollBar().maximum())
        return msg_id

    def update_message_status(self, message_id, status):
        """Update the status icon for a message."""
        import re

        icons = {
            "sending": "\u23F3",  # hourglass not done
            "sent": "\u2713",
            "delivered": "\u2713\u2713",
            "read": "<span style='color:blue'>\u2713\u2713</span>",
            "failed": "<span style='color:red'>\u2757</span>",
        }
        tooltips = {
            "sending": "Sending",
            "sent": "Sent",
            "delivered": "Delivered",
            "read": "Read by all recipients",
            "failed": "Failed to send",
        }
        html = self.chat_display.toHtml()
        pattern = rf"<a name=\"{message_id}\"></a>[^<]*"
        replacement = f"<a name=\"{message_id}\"></a>{icons.get(status, '')}"
        new_html, count = re.subn(pattern, replacement, html)
        if count:
            self.chat_display.setHtml(new_html)
    
    def show_search(self):
        """Display a dialog to search conversation history."""
        text = self.chat_display.toPlainText()
        if not text.strip():
            self.parent_app.show_notification("No conversation to search", "info")
            return
        dialog = SearchDialog(self, text)
        dialog.exec_()

    def show_history_search(self):
        """Display a dialog to search persisted chat history."""
        history = load_history()
        if not history:
            self.parent_app.show_notification("No stored history", "info")
            return
        dialog = HistorySearchDialog(self, history)
        dialog.exec_()
    
    def copy_conversation(self):
        """Copy conversation to clipboard"""
        text = self.chat_display.toPlainText()
        clipboard = QtCore.QCoreApplication.instance().clipboard()
        clipboard.setText(text)
        self.parent_app.show_notification("Conversation copied to clipboard", "info")
    
    def save_conversation(self):
        """Save conversation to a text file chosen by the user."""
        text = self.chat_display.toPlainText()
        if not text.strip():
            self.parent_app.show_notification("Nothing to save", "info")
            return

        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Conversation",
            "conversation.txt",
            "Text Files (*.txt);;All Files (*)",
            options=options,
        )
        if not file_name:
            return

        try:
            with open(file_name, "w", encoding="utf-8") as f:
                f.write(text)
            self.parent_app.show_notification(f"Conversation saved to {file_name}")
        except Exception as e:  # pragma: no cover - just in case
            self.parent_app.show_notification(f"Failed to save conversation: {e}", "error")

    def show_typing_indicator(self, name="Assistant"):
        """Show the typing indicator with animated dots."""
        self.typing_name = name
        self.typing_indicator.show()
        self.typing_indicator.setText(f"<span style='font-size:20px'>🤔</span> {name} is typing")
        if self.typing_timer is None:
            self.typing_timer = QTimer(self)
            self.typing_timer.timeout.connect(self.update_typing_indicator)
            self.typing_timer.start(500)
    
    def hide_typing_indicator(self):
        """Hide the typing indicator"""
        if self.typing_timer:
            self.typing_timer.stop()
            self.typing_timer = None
        self.typing_indicator.hide()
    
    def update_typing_indicator(self):
        """Update the typing indicator animation"""
        self.typing_dots_count = (self.typing_dots_count + 1) % 4
        dots = "." * self.typing_dots_count
        self.typing_indicator.setText(
            f"<span style='font-size:20px'>🤔</span> {self.typing_name} is typing{dots}"
        )

    def get_avatar(self, name):
        if name.startswith(self.parent_app.user_name):
            return self.user_avatar
        return self.parent_app.agents_data.get(name, {}).get("avatar", "🤖")
