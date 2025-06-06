TOOL_METADATA = {
    "name": "task-sequence-recorder",
    "description": "Record mouse clicks and keystrokes then replay them later.",
    "args": ["action", "path", "duration"],
}

import json
import time


def run_tool(args):
    """Record or replay a sequence of user input events."""
    action = args.get("action")
    path = args.get("path", "sequence.json")
    duration = float(args.get("duration", 5))

    if action == "record":
        try:
            from pynput import mouse, keyboard
        except Exception:
            return "[task-sequence-recorder Error] pynput not installed."
        events = []
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

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(events, f)
            return f"Sequence recorded to {path}"
        except Exception as exc:
            return f"[task-sequence-recorder Error] {exc}"

    if action == "play":
        try:
            import pyautogui
        except Exception:
            return "[task-sequence-recorder Error] pyautogui not installed."
        try:
            with open(path, "r", encoding="utf-8") as f:
                events = json.load(f)
        except Exception as exc:
            return f"[task-sequence-recorder Error] {exc}"
        last = 0
        for evt in events:
            delay = evt.get("time", 0) - last
            if delay > 0:
                time.sleep(delay)
            last = evt.get("time", 0)
            if evt["type"] == "move":
                pyautogui.moveTo(evt["x"], evt["y"])
            elif evt["type"] == "click" and evt.get("pressed"):
                pyautogui.click(evt["x"], evt["y"], button=evt.get("button", "left"))
            elif evt["type"] == "press":
                key = evt["key"].replace("'", "")
                pyautogui.keyDown(key)
            elif evt["type"] == "release":
                key = evt["key"].replace("'", "")
                pyautogui.keyUp(key)
        return "Sequence played"

    return "[task-sequence-recorder Error] Unknown action"
