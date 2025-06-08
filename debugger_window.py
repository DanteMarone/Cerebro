import json
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QListWidget, QTextEdit, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QLabel, QSplitter, QListWidgetItem, QAction, QToolBar,
    QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSlot, QCoreApplication
from PyQt5.QtGui import QFont

# Assuming debugger_service.py and debugger_events.py are in the same directory
from debugger_service import DebuggerService
from debugger_events import BaseEvent

class DebuggerWindow(QMainWindow):
    def __init__(self, debugger_service: DebuggerService, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.debugger_service = debugger_service

        self.setWindowTitle("Cerebro Interactive Debugger")
        self.setGeometry(150, 150, 1200, 700)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # --- Toolbar for Controls ---
        toolbar = QToolBar("Debugger Controls")
        self.addToolBar(toolbar)

        self.enable_debugger_checkbox = QCheckBox("Enable Debugging")
        self.enable_debugger_checkbox.setChecked(self.debugger_service.is_debugger_enabled())
        self.enable_debugger_checkbox.toggled.connect(self.handle_toggle_debugging)
        toolbar.addWidget(self.enable_debugger_checkbox)

        toolbar.addSeparator()

        refresh_action = QAction("Refresh Events", self)
        refresh_action.triggered.connect(self.refresh_event_list_display)
        toolbar.addAction(refresh_action)

        clear_action = QAction("Clear Session", self)
        clear_action.triggered.connect(self.handle_clear_session)
        toolbar.addAction(clear_action)

        toolbar.addSeparator()

        self.prev_event_action = QAction("Previous Event", self)
        self.prev_event_action.triggered.connect(self.handle_previous_event)
        toolbar.addAction(self.prev_event_action)

        self.next_event_action = QAction("Next Event", self)
        self.next_event_action.triggered.connect(self.handle_next_event)
        toolbar.addAction(self.next_event_action)

        # --- Main Content Area (Splitter) ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)

        # Left Pane: Event List
        self.event_list_widget = QListWidget()
        self.event_list_widget.setFont(QFont("Monospace", 9)) # Monospace for better alignment if needed
        self.splitter.addWidget(self.event_list_widget)

        # Right Pane: Event Details
        self.event_detail_widget = QTextEdit()
        self.event_detail_widget.setReadOnly(True)
        self.event_detail_widget.setFont(QFont("Monospace", 10))
        self.event_detail_widget.setLineWrapMode(QTextEdit.WidgetWidth) # Or NoWrap
        self.splitter.addWidget(self.event_detail_widget)

        self.splitter.setSizes([400, 800])  # Initial sizes for panes

        # --- Connect Signals from DebuggerService ---
        self.debugger_service.event_added.connect(self.add_event_to_list_display)
        self.debugger_service.session_cleared.connect(self.clear_all_displays)
        self.debugger_service.enabled_state_changed.connect(self.update_enabled_controls_state)

        # --- Connect UI Signals ---
        self.event_list_widget.currentItemChanged.connect(self.display_event_details)

        # --- Initial Population ---
        self.refresh_event_list_display()
        self.update_enabled_controls_state(self.debugger_service.is_debugger_enabled())
        self.update_prev_next_button_states()

    def format_event_summary(self, event: BaseEvent) -> str:
        timestamp_str = event.timestamp.strftime('%H:%M:%S.%f')[:-3]

        prefix_map = {
            "user_message": "[USR]",
            "agent_request": "[AGENT_REQ]",
            "llm_request": "[LLM_REQ]",
            "agent_thought": "[THOUGHT]",
            "llm_response": "[LLM_RESP]",
            "tool_call": "[TOOL_CALL]",
            "tool_result": "[TOOL_RSLT]",
            "agent_handoff": "[HANDOFF]",
            "error": "[ERROR]",
        }
        event_prefix = prefix_map.get(event.event_type, f"[{event.event_type.upper()}]")

        parts = [timestamp_str, event_prefix]

        agent_name = getattr(event, 'agent_name', None)
        if agent_name:
            parts.append(f"Agent: {agent_name}")

        # Event specific details
        if event.event_type == "user_message":
            parts.append(f"'{getattr(event, 'user_text', '')[:30].strip()}...'")
        elif event.event_type == "llm_request":
            parts.append(f"Model: {getattr(event, 'model_name', 'N/A')}")
        elif event.event_type == "llm_response":
            if getattr(event, 'parsed_tool_request', None):
                parts.append("Tool Req Parsed")
        elif event.event_type == "tool_call":
            tool_name = getattr(event, 'tool_name', 'N/A')
            tool_args = getattr(event, 'tool_args', {})
            args_summary = json.dumps(tool_args, separators=(',', ':'))[:30]
            parts.append(f"Tool: {tool_name}({args_summary}...)")
        elif event.event_type == "tool_result":
            tool_name = getattr(event, 'tool_name', 'N/A')
            status = "ERROR" if getattr(event, 'is_error', False) else "SUCCESS"
            result_data = getattr(event, 'result', '')
            result_summary = str(result_data)[:30].replace('\n', ' ')
            parts.append(f"Tool: {tool_name} -> {status} ({result_summary}...)")
        elif event.event_type == "error":
            source = getattr(event, 'source', 'Unknown')
            error_msg = getattr(event, 'error_message', '')[:30].replace('\n', ' ')
            parts.append(f"Src: {source} - '{error_msg}...'")
        elif event.event_type == "agent_request":
            parts.append(f"Trigger: {getattr(event, 'triggering_event_type', 'N/A')}")
        elif event.event_type == "agent_handoff":
            from_agent = getattr(event, 'from_agent_name', 'N/A')
            to_agent = getattr(event, 'to_agent_name', 'N/A')
            parts.append(f"{from_agent} -> {to_agent}")

        return " | ".join(parts)

    @pyqtSlot(BaseEvent)
    def add_event_to_list_display(self, event: BaseEvent):
        summary = self.format_event_summary(event)
        list_item = QListWidgetItem(summary)
        list_item.setData(Qt.UserRole, event)  # Store the full event object
        self.event_list_widget.addItem(list_item)
        self.event_list_widget.scrollToBottom() # Auto-scroll
        self.update_prev_next_button_states()

    @pyqtSlot()
    def refresh_event_list_display(self):
        self.event_list_widget.clear()
        self.event_detail_widget.clear()
        history = self.debugger_service.get_events_history()
        for event in history:
            self.add_event_to_list_display(event)
        self.update_prev_next_button_states()

    @pyqtSlot()
    def clear_all_displays(self):
        self.event_list_widget.clear()
        self.event_detail_widget.clear()
        self.update_prev_next_button_states()
        # self.show_status_message("Debug session cleared.") # Optional status bar message

    @pyqtSlot(QListWidgetItem, QListWidgetItem)
    def display_event_details(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]):
        if current_item:
            event: Optional[BaseEvent] = current_item.data(Qt.UserRole)
            if event:
                try:
                    # Use model_dump_json for Pydantic v2, or .json() for v1
                    detail_json = event.model_dump_json(indent=2)
                    self.event_detail_widget.setText(detail_json)
                except Exception as e:
                    self.event_detail_widget.setText(f"Error displaying event details: {str(e)}\n\n{str(event)}")
            else:
                self.event_detail_widget.clear()
        else:
            self.event_detail_widget.clear()
        self.update_prev_next_button_states()

    @pyqtSlot()
    def handle_previous_event(self):
        current_row = self.event_list_widget.currentRow()
        if current_row > 0:
            self.event_list_widget.setCurrentRow(current_row - 1)

    @pyqtSlot()
    def handle_next_event(self):
        current_row = self.event_list_widget.currentRow()
        if current_row < self.event_list_widget.count() - 1:
            self.event_list_widget.setCurrentRow(current_row + 1)

    def update_prev_next_button_states(self):
        current_row = self.event_list_widget.currentRow()
        count = self.event_list_widget.count()

        self.prev_event_action.setEnabled(current_row > 0 and count > 0)
        self.next_event_action.setEnabled(current_row < count - 1 and count > 0)

    @pyqtSlot(bool)
    def handle_toggle_debugging(self, checked: bool):
        self.debugger_service.set_enabled(checked)

    @pyqtSlot()
    def handle_clear_session(self):
        self.debugger_service.clear_session()
        # The session_cleared signal will trigger clear_all_displays

    @pyqtSlot(bool)
    def update_enabled_controls_state(self, enabled: bool):
        # Update checkbox if state changed externally (e.g. by setting in main app)
        if self.enable_debugger_checkbox.isChecked() != enabled:
            self.enable_debugger_checkbox.setChecked(enabled)

        # Potentially disable/enable other controls if needed when debugger is off
        self.event_list_widget.setEnabled(enabled)
        self.event_detail_widget.setEnabled(enabled)


    def closeEvent(self, event):
        # Override to just hide the window, standard practice for tool windows
        # Or handle disconnection of signals if they were connected with Qt.DirectConnection
        # For default AutoConnection, Qt usually handles it.
        self.hide()
        event.ignore() # Ignore the close event to allow reopening

# Example usage (for testing this window independently)
if __name__ == '__main__':
    import sys
    from PyQt5.QtWidgets import QApplication
    from debugger_events import UserMessageEvent, LLMRequestEvent # For sample data

    app = QApplication(sys.argv)

    # Create a dummy DebuggerService for testing
    test_service = DebuggerService()
    test_service.set_enabled(True) # Enable it for testing

    # Add some sample events
    test_service.record_event(UserMessageEvent(user_text="Hello from debugger window test!"))
    test_service.record_event(LLMRequestEvent(
        agent_name="TestAgent", model_name="gpt-test-model",
        messages=[{"role": "user", "content": "Test prompt for UI"}],
        temperature=0.6, max_tokens=60
    ))

    debugger_win = DebuggerWindow(debugger_service=test_service)
    debugger_win.show()

    # Add an event after window is shown
    import time
    # time.sleep(1) # Not ideal in UI thread
    # test_service.record_event(UserMessageEvent(user_text="Another message after window shown."))

    sys.exit(app.exec_())
