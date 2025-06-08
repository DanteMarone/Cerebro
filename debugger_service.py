from typing import List, Optional, Any
from PyQt5.QtCore import QObject, pyqtSignal

# Assuming debugger_events.py is in the same directory (project root)
from debugger_events import BaseEvent # Import BaseEvent and other specific events if needed directly

class DebuggerService(QObject):
    # Signal to notify when a new event is added
    event_added = pyqtSignal(BaseEvent)
    # Signal to notify when the session is cleared
    session_cleared = pyqtSignal()
    # Signal to notify when the enabled state changes
    enabled_state_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._events_history: List[BaseEvent] = []
        self._is_enabled: bool = False

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the debugger service."""
        if self._is_enabled != enabled:
            self._is_enabled = enabled
            self.enabled_state_changed.emit(self._is_enabled)
            if self._is_enabled:
                print("[DebuggerService] Debugger enabled.") # Or use a proper logger
            else:
                print("[DebuggerService] Debugger disabled.")

    def is_debugger_enabled(self) -> bool:
        """Check if the debugger is currently enabled."""
        return self._is_enabled

    def record_event(self, event: BaseEvent) -> None:
        """
        Records a debug event if the debugger is enabled.
        Emits the event_added signal.
        """
        if not self._is_enabled:
            return

        self._events_history.append(event)
        self.event_added.emit(event)
        # For console logging, if helpful during development
        # print(f"[DebuggerService] Event recorded: {event.event_type}")

    def get_events_history(self) -> List[BaseEvent]:
        """Returns a copy of the current events history."""
        return list(self._events_history) # Return a copy

    def clear_session(self) -> None:
        """Clears all recorded events from the current session."""
        self._events_history.clear()
        self.session_cleared.emit()
        if self._is_enabled:
            print("[DebuggerService] Debug session cleared.")

    def get_event_by_index(self, index: int) -> Optional[BaseEvent]:
        """
        Retrieves a specific event by its index.
        Returns None if the index is out of bounds.
        """
        if 0 <= index < len(self._events_history):
            return self._events_history[index]
        return None

# Example usage (optional, for self-testing or demonstration):
if __name__ == '__main__':
    from debugger_events import UserMessageEvent, LLMRequestEvent
    import time

    # This example won't run Qt event loop, so signals might not behave as in app
    service = DebuggerService()
    service.set_enabled(True)

    def handle_event_added(event):
        print(f"Signal received: New event - {event.event_type}, Data: {event.model_dump_json(indent=2)}")

    def handle_session_cleared():
        print("Signal received: Session cleared")

    service.event_added.connect(handle_event_added)
    service.session_cleared.connect(handle_session_cleared)

    # Record some events
    user_event = UserMessageEvent(user_text="Hello from debugger test!")
    service.record_event(user_event)

    time.sleep(0.1) # To see timestamp differences

    llm_event_data = {
        "agent_name": "TestAgent",
        "model_name": "gpt-test",
        "messages": [{"role": "user", "content": "Test prompt"}],
        "temperature": 0.5,
        "max_tokens": 50,
    }
    llm_event = LLMRequestEvent(**llm_event_data)
    service.record_event(llm_event)

    print(f"\nTotal events recorded: {len(service.get_events_history())}")

    first_event = service.get_event_by_index(0)
    if first_event:
        print(f"\nFirst event by index: {first_event.event_type}")

    service.clear_session()
    print(f"\nEvents after clear: {len(service.get_events_history())}")

    service.set_enabled(False)
    service.record_event(UserMessageEvent(user_text="This should not be recorded."))
    print(f"\nEvents after disabling and trying to record: {len(service.get_events_history())}")
