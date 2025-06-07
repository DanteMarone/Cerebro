import json
import sys
import types
import automation_sequences as auto


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

    result = auto.run_automation([{"name": "test", "events": data}], "test")
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

    result = auto.run_automation([{"name": "demo", "events": events}], "demo")
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
    result = auto.run_automation([{"name": "x", "events": []}], "x")
    assert "pyautogui not installed" in result
