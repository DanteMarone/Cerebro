#tab_chat.py
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QStyle,
    QLabel, QSplitter, QFrame, QScrollArea, QToolButton, QMenu, QAction
)

class ChatTab(QWidget):
    """
    Encapsulates the chat UI: display, input, send/clear buttons.
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.typing_dots_count = 0
        self.typing_timer = None

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
        search_btn.setText("🔍")
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
        self.user_input.setMinimumHeight(40)  # Set minimum height
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
        self.send_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_ArrowRight')))
        self.send_button.setToolTip("Send the message (Ctrl+Enter)")
        btn_layout.addWidget(self.send_button)
        
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
        self.user_input.textChanged.connect(self.adjust_input_height)
        search_btn.clicked.connect(self.show_search)

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
        self.user_input.setFixedHeight(40)
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
    
    def show_search(self):
        """Show search interface in chat"""
        self.parent_app.show_notification("Search functionality coming soon", "info")
    
    def copy_conversation(self):
        """Copy conversation to clipboard"""
        text = self.chat_display.toPlainText()
        clipboard = QtCore.QCoreApplication.instance().clipboard()
        clipboard.setText(text)
        self.parent_app.show_notification("Conversation copied to clipboard", "info")
    
    def save_conversation(self):
        """Save conversation to a file"""
        # This would normally open a file dialog, but for simplicity we'll just notify
        self.parent_app.show_notification("Save functionality coming soon", "info")
    
    def show_typing_indicator(self):
        """Show the typing indicator with animated dots"""
        self.typing_indicator.show()
        
        if self.typing_timer is None:
            self.typing_timer = QTimer(self)
            self.typing_timer.timeout.connect(self.update_typing_indicator)
            self.typing_timer.start(500)  # Update every 500ms
    
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
        self.typing_indicator.setText(f"Agent is thinking{dots}")