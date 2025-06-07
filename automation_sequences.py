import json
import os
import time
from typing import List, Dict, Any

AUTOMATIONS_FILE = "automations.json"

def load_automations(debug_enabled: bool = False) -> List[Dict[str, Any]]:
    """Return list of saved automations."""
    if not os.path.exists(AUTOMATIONS_FILE):
        return []
    try:
        with open(AUTOMATIONS_FILE, "r", encoding="utf-8") as f:
            autos = json.load(f)
        if debug_enabled:
            print("[Debug] Automations loaded:", autos)
        return autos
    except Exception as exc:
        if debug_enabled:
            print(f"[Debug] Failed to load automations: {exc}")
        return []

def save_automations(automations: List[Dict[str, Any]], debug_enabled: bool = False) -> None:
    """Persist automations to disk."""
    try:
        with open(AUTOMATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(automations, f, indent=2)
        if debug_enabled:
            print("[Debug] Automations saved.")
    except Exception as exc:
        if debug_enabled:
            print(f"[Debug] Failed to save automations: {exc}")

def record_automation(duration: float = 5) -> List[Dict[str, Any]]:
    """Record mouse and keyboard events for the given duration."""
    try:
        from pynput import mouse, keyboard
    except Exception:
        return []

    events: List[Dict[str, Any]] = []
    start = time.time()

    def on_move(x, y):
        events.append({"type": "move", "x": x, "y": y, "time": time.time() - start})

    def on_click(x, y, button, pressed):
        events.append({
            "type": "click",
            "x": x,
            "y": y,
            "button": getattr(button, "name", str(button)),
            "pressed": pressed,
            "time": time.time() - start,
        })

    def on_press(key):
        events.append({"type": "press", "key": str(key), "time": time.time() - start})

    def on_release(key):
        events.append({"type": "release", "key": str(key), "time": time.time() - start})
        if key == keyboard.Key.esc:
            return False

    with mouse.Listener(on_move=on_move, on_click=on_click) as ml, \
            keyboard.Listener(on_press=on_press, on_release=on_release) as kl:
        end = time.time() + duration
        while time.time() < end and ml.running and kl.running:
            time.sleep(0.01)
    return events

def run_automation(automations: List[Dict[str, Any]], name: str) -> str:
    """Replay events for the named automation.

    Mouse movement events are skipped. The cursor jumps to the coordinates of
    click/drag actions so sequences play back quickly regardless of the original
    recording speed.
    """
    auto = next((a for a in automations if a.get("name") == name), None)
    if not auto:
        return f"[Automation Error] '{name}' not found"
    try:
        import pyautogui
    except Exception:
        return "[Automation Error] pyautogui not installed."
    events = auto.get("events", [])
    button_down = None
    for evt in events:
        etype = evt.get("type")
        if etype == "click":
            btn = evt.get("button", "left")
            if evt.get("pressed"):
                pyautogui.moveTo(evt["x"], evt["y"])
                pyautogui.mouseDown(button=btn)
                button_down = btn
            else:
                pyautogui.moveTo(evt["x"], evt["y"])
                pyautogui.mouseUp(button=button_down or btn)
                button_down = None
        elif etype == "press":
            key = evt.get("key", "").replace("'", "")
            pyautogui.keyDown(key)
        elif etype == "release":
            key = evt.get("key", "").replace("'", "")
            pyautogui.keyUp(key)
    return "Automation executed"


def add_automation(automations: List[Dict[str, Any]], name: str, events: List[Dict[str, Any]],
                   debug_enabled: bool = False) -> None:
    """Add a new automation and save."""
    automations.append({"name": name, "events": events})
    save_automations(automations, debug_enabled)


def delete_automation(automations: List[Dict[str, Any]], name: str, debug_enabled: bool = False) -> None:
    """Delete automation by name."""
    idx = next((i for i, a in enumerate(automations) if a.get("name") == name), None)
    if idx is None:
        return
    del automations[idx]
    save_automations(automations, debug_enabled)
