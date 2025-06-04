# transcripts.py

import json
import os
from datetime import datetime

HISTORY_FILE = "chat_history.json"

def load_history(debug_enabled=False):
    """Load chat history from disk."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
        if debug_enabled:
            print("[Debug] History loaded", data)
        return data
    except Exception as e:
        print(f"[Error] Failed to load history: {e}")
        return []

def save_history(history, debug_enabled=False):
    """Save chat history to disk."""
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
        if debug_enabled:
            print("[Debug] History saved")
    except Exception as e:
        print(f"[Error] Failed to save history: {e}")

def append_message(history, role, content, agent=None, debug_enabled=False):
    """Append a message to history and save it."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "role": role,
        "content": content,
    }
    if agent:
        entry["agent"] = agent
    history.append(entry)
    save_history(history, debug_enabled)
    return entry

def clear_history(debug_enabled=False):
    """Delete the saved history file."""
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
            if debug_enabled:
                print("[Debug] History cleared")
    except Exception as e:
        print(f"[Error] Failed to clear history: {e}")

def export_history(dest_path, debug_enabled=False):
    """Export current history to the given path."""
    history = load_history(debug_enabled)
    try:
        with open(dest_path, "w") as f:
            json.dump(history, f, indent=2)
        if debug_enabled:
            print(f"[Debug] History exported to {dest_path}")
    except Exception as e:
        print(f"[Error] Failed to export history: {e}")
