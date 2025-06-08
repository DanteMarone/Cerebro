import json
import sys
import types
import pytest # Import pytest for parametrize if not already there
from unittest.mock import patch, MagicMock

import automation_sequences as auto
from automation_sequences import (
    STEP_TYPE_MOUSE_CLICK,
    STEP_TYPE_KEYBOARD_INPUT,
    STEP_TYPE_WAIT,
    STEP_TYPE_MOUSE_DRAG, # New import
    MouseClickParams, # Example, if you decide to use it for test data
    KeyboardInputParams,
    WaitParams,
    MouseDragParams, # New import
    is_valid_step,      # For testing validation
    run_step_automation # For testing execution
)


def test_record_and_play(tmp_path, monkeypatch):
    events = []

    class FakeMouseListener:
        def __init__(self, on_move=None, on_click=None):
            self.on_move = on_move
            self.on_click = on_click
            self.running = True

        def __enter__(self):
            if self.on_move:
                self.on_move(10, 20)
            if self.on_click:
                FakeButton = type("Button", (), {"name": "left"})
                self.on_click(10, 20, FakeButton(), True)
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeKeyboardListener:
        def __init__(self, on_press=None, on_release=None):
            self.on_press = on_press
            self.on_release = on_release
            self.running = True

        def __enter__(self):
            if self.on_press:
                self.on_press("a")
            if self.on_release:
                self.on_release("a")
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_pynput = types.SimpleNamespace(
        mouse=types.SimpleNamespace(Listener=FakeMouseListener),
        keyboard=types.SimpleNamespace(Listener=FakeKeyboardListener, Key=types.SimpleNamespace(esc="esc")),
    )
    monkeypatch.setitem(sys.modules, "pynput", fake_pynput)
    monkeypatch.setattr(auto.time, "sleep", lambda s: None)

    events_recorded = auto.record_automation(0)
    assert events_recorded
    data = events_recorded
    assert any(e["type"] == "move" for e in data)

    actions = []
    fake_pg = types.SimpleNamespace(
        moveTo=lambda x, y: actions.append(("move", x, y)),
        mouseDown=lambda button="left": actions.append(("down", button)),
        mouseUp=lambda button="left": actions.append(("up", button)),
        click=lambda x, y, button="left": actions.append(("click", x, y, button)),
        keyDown=lambda k: actions.append(("down", k)),
        keyUp=lambda k: actions.append(("up", k)),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pg)

    result = auto.run_automation([{"name": "test", "events": data}], "test", step_delay=0)
    assert "Automation executed" in result
    assert any(a[0] == "move" for a in actions)


def test_run_automation_jumps_to_clicks(monkeypatch):
    events = [
        {"type": "move", "x": 1, "y": 1, "time": 0.0},
        {"type": "click", "x": 1, "y": 1, "button": "left", "pressed": True, "time": 0.1},
        {"type": "move", "x": 2, "y": 2, "time": 0.2},
        {"type": "move", "x": 3, "y": 3, "time": 0.3},
        {"type": "click", "x": 5, "y": 5, "button": "left", "pressed": False, "time": 0.4},
    ]

    actions = []
    fake_pg = types.SimpleNamespace(
        moveTo=lambda x, y: actions.append(("move", x, y)),
        mouseDown=lambda button="left": actions.append(("down", button)),
        mouseUp=lambda button="left": actions.append(("up", button)),
        keyDown=lambda k: actions.append(("downkey", k)),
        keyUp=lambda k: actions.append(("upkey", k)),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pg)

    monkeypatch.setattr(auto.time, "sleep", lambda s: None)
    result = auto.run_automation([{"name": "demo", "events": events}], "demo", step_delay=0)
    assert result == "Automation executed"
    assert actions == [
        ("move", 1, 1),
        ("down", "left"),
        ("move", 5, 5),
        ("up", "left"),
    ]


def test_missing_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynput", types.ModuleType("pynput"))
    result = auto.record_automation(0)
    assert result == []

    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyautogui":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(auto.time, "sleep", lambda s: None)
    result = auto.run_automation([{"name": "x", "events": []}], "x", step_delay=0)
    assert "pyautogui not installed" in result


def test_run_automation_delay(monkeypatch):
    events = [
        {"type": "press", "key": "a", "time": 0.0},
        {"type": "release", "key": "a", "time": 0.1},
    ]

    actions = []
    fake_pg = types.SimpleNamespace(
        moveTo=lambda x, y: None,
        mouseDown=lambda button="left": actions.append(("down", button)),
        mouseUp=lambda button="left": actions.append(("up", button)),
        keyDown=lambda k: actions.append(("down", k)),
        keyUp=lambda k: actions.append(("up", k)),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pg)

    sleeps = []
    monkeypatch.setattr(auto.time, "sleep", lambda s: sleeps.append(s))
    result = auto.run_automation([{"name": "demo", "events": events}], "demo", step_delay=0.25)
    assert result == "Automation executed"
    assert sleeps == [0.25, 0.25]


def test_run_automation_invalid_events(monkeypatch):
    """run_automation should handle missing or invalid events list."""
    monkeypatch.setattr(auto.time, "sleep", lambda s: None)
    result = auto.run_automation([{"name": "bad", "events": None}], "bad", step_delay=0)
    assert "Invalid event list" in result


# --- Tests for Step-based Automations ---

@patch('automation_sequences.pyautogui', new_callable=MagicMock)
def test_run_step_automation_mouse_click(mock_pyautogui):
    """Test MouseClick step execution."""
    actions = []
    mock_pyautogui.moveTo = lambda x, y: actions.append(("moveTo", x, y))
    mock_pyautogui.click = lambda x, y, button: actions.append(("click", x, y, button))

    steps_data = [
        {"type": STEP_TYPE_MOUSE_CLICK, "params": {"x": 100, "y": 150, "button": "left"}}
    ]
    context = run_step_automation(steps_data, step_delay=0)

    assert context['status'] == 'completed'
    assert actions == [("moveTo", 100, 150), ("click", 100, 150, "left")]
    mock_pyautogui.moveTo.assert_called_with(100, 150)
    mock_pyautogui.click.assert_called_with(x=100, y=150, button="left")


@patch('automation_sequences.pyautogui', new_callable=MagicMock)
def test_run_step_automation_mouse_drag(mock_pyautogui):
    """Test MouseDrag step execution."""
    actions = []
    # Configure the mock pyautogui object
    mock_pyautogui.moveTo = lambda x, y: actions.append(("moveTo", x, y))
    # dragTo is usually mouseDown, moveTo, mouseUp. Let's simulate that or mock dragTo directly
    # For simplicity, if dragTo is a direct pyautogui call in the implementation:
    mock_pyautogui.dragTo = lambda x, y, duration: actions.append(("dragTo", x, y, duration))


    steps_data = [
        {"type": STEP_TYPE_MOUSE_DRAG, "params": {"start_x": 50, "start_y": 60, "end_x": 150, "end_y": 160}}
    ]
    context = run_step_automation(steps_data, step_delay=0)

    assert context['status'] == 'completed'
    # Based on current implementation of MouseDrag in automation_sequences.py:
    # pyautogui.moveTo(start_x, start_y)
    # pyautogui.dragTo(end_x, end_y, duration=0.2)
    expected_actions = [
        ("moveTo", 50, 60),
        ("dragTo", 150, 160, 0.2) # Assuming default duration 0.2
    ]
    assert actions == expected_actions
    mock_pyautogui.moveTo.assert_called_with(50, 60)
    mock_pyautogui.dragTo.assert_called_with(150, 160, duration=0.2)


def test_is_valid_step_mouse_drag():
    """Test validation for MouseDrag steps."""
    # Valid case
    valid_step = {"type": STEP_TYPE_MOUSE_DRAG, "params": {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 10}}
    assert is_valid_step(valid_step) is True

    # Invalid cases
    invalid_params = [
        {}, # Missing all params
        {"start_x": 0, "start_y": 0, "end_x": 10}, # Missing end_y
        {"start_x": 0, "start_y": 0, "end_y": 10}, # Missing end_x
        {"start_x": 0, "end_x": 10, "end_y": 10}, # Missing start_y
        {"start_y": 0, "end_x": 10, "end_y": 10}, # Missing start_x
        {"start_x": "0", "start_y": 0, "end_x": 10, "end_y": 10}, # Incorrect type for start_x
        {"start_x": 0, "start_y": "0", "end_x": 10, "end_y": 10}, # Incorrect type for start_y
        {"start_x": 0, "start_y": 0, "end_x": "10", "end_y": 10}, # Incorrect type for end_x
        {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": "10"}, # Incorrect type for end_y
    ]

    for params in invalid_params:
        step = {"type": STEP_TYPE_MOUSE_DRAG, "params": params}
        assert is_valid_step(step) is False, f"Failed for params: {params}"

    # Test with a completely wrong type
    assert is_valid_step({"type": "NotARealType", "params": {}}) is False
    # Test with missing 'params'
    assert is_valid_step({"type": STEP_TYPE_MOUSE_DRAG}) is False
    # Test with params not being a dict
    assert is_valid_step({"type": STEP_TYPE_MOUSE_DRAG, "params": "not_a_dict"}) is False


@patch('automation_sequences.pyautogui', new_callable=MagicMock)
def test_run_step_automation_mouse_drag_invalid_params(mock_pyautogui):
    """Test error handling in run_step_automation for invalid MouseDrag params."""
    # Case 1: Missing parameter (e.g., end_x)
    # Note: is_valid_step should catch this first if called, but run_step_automation also has internal checks.
    # The implementation of run_step_automation calls is_valid_step first.
    # So, this test effectively also tests that is_valid_step is correctly integrated.

    steps_data_missing_param = [
        {"type": STEP_TYPE_MOUSE_DRAG, "params": {"start_x": 50, "start_y": 60, "end_y": 160}} # Missing end_x
    ]
    context_missing = run_step_automation(steps_data_missing_param, step_delay=0)
    assert context_missing['status'] == 'error'
    assert "invalid or has missing parameters" in context_missing['error_message'] # From is_valid_step check

    # Case 2: Incorrect parameter type (e.g., start_x is a string)
    # This will also be caught by the is_valid_step check within run_step_automation
    steps_data_wrong_type = [
        {"type": STEP_TYPE_MOUSE_DRAG, "params": {"start_x": "50", "start_y": 60, "end_x": 150, "end_y": 160}}
    ]
    context_wrong_type = run_step_automation(steps_data_wrong_type, step_delay=0)
    assert context_wrong_type['status'] == 'error'
    assert "invalid or has missing parameters" in context_wrong_type['error_message'] # From is_valid_step check


    # Case 3: Test internal validation within the STEP_TYPE_MOUSE_DRAG block in run_step_automation
    # This requires is_valid_step to pass, but the specific handler to fail.
    # The current is_valid_step for MouseDrag is quite comprehensive.
    # However, if we imagine a scenario where is_valid_step was less strict,
    # or if a parameter was valid type but invalid value (e.g. negative, though current spec doesn't forbid).
    # Let's assume the internal check for integer types on all coordinates within the MouseDrag handler.
    # To specifically test the error message from *within* the MouseDrag handler block,
    # we'd need to bypass the initial `is_valid_step` or make a step that passes `is_valid_step`
    # but fails the internal check.
    # The current `is_valid_step` checks for `isinstance(params["start_x"], int)`.
    # The internal check in `run_step_automation` for `STEP_TYPE_MOUSE_DRAG` is:
    # `if not all(isinstance(val, int) for val in [start_x, start_y, end_x, end_y]):`
    # This is redundant if `is_valid_step` is perfect.
    # For the sake of completeness, if we manually construct a scenario where `is_valid_step` might pass
    # but the internal one fails (e.g., by mocking `is_valid_step` to always return True for this specific call)
    # or if `is_valid_step` was simpler.

    # Given the current code, the error "Start and End X, Y must be integers"
    # from within the MouseDrag specific block in `run_step_automation`
    # will NOT be reached if `is_valid_step` is working as expected, because `is_valid_step`
    # already checks for `isinstance(..., int)`.
    # So, the "invalid or has missing parameters" from the top-level check in `run_step_automation`
    # (which calls `is_valid_step`) is the expected error message.
    # The tests above (context_missing, context_wrong_type) correctly cover this.

    # If we wanted to ensure the specific error message "Start and End X, Y must be integers"
    # could be triggered, we would need a case where `is_valid_step` returns True,
    # but the params are still somehow wrong in a way that this specific check catches.
    # Example: If `is_valid_step` only checked for presence, not type.
    # But `is_valid_step` *does* check for type.
    # So, the prior assertions are sufficient for the current code structure.
