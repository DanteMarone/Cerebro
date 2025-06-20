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
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
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
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
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
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
        if debug_enabled:
            print(f"[Debug] History exported to {dest_path}")
    except Exception as e:
        print(f"[Error] Failed to export history: {e}")


def search_history(history, query, role=None, agent=None):
    """Search history entries matching the query and optional filters."""
    if not query:
        return []
    query_lower = query.lower()
    results = []
    for msg in history:
        if role and msg.get("role") != role:
            continue
        if agent and msg.get("agent") != agent:
            continue
        content = msg.get("content", "")
        if query_lower in content.lower():
            results.append(msg)
    return results

def summarize_history(history, threshold=20, max_chars=1000):
    """Condense older history into a single system message.

    If the number of messages exceeds ``threshold``, messages beyond the
    threshold are concatenated and truncated to ``max_chars`` characters. The
    condensed text is returned as a new system message prepended to the most
    recent ``threshold`` messages.

    Args:
        history (list): Full chat history.
        threshold (int, optional): Number of recent messages to keep. Defaults
            to 20.
        max_chars (int, optional): Maximum characters for the summary.

    Returns:
        list: Summarized chat history.
    """
    if threshold is None or threshold <= 0:
        return history[:]

    if len(history) <= threshold:
        return history[:]

    old_msgs = history[:-threshold]
    recent = history[-threshold:]

    parts = []
    for msg in old_msgs:
        content = msg.get("content", "").strip()
        if not content:
            continue
        if msg["role"] == "user":
            parts.append(f"User: {content}")
        else:
            agent = msg.get("agent", "assistant")
            parts.append(f"{agent}: {content}")

    summary_text = " ".join(parts)
    if len(summary_text) > max_chars:
        summary_text = summary_text[:max_chars].rstrip() + "..."

    summary_msg = {
        "role": "system",
        "content": f"Summary of earlier conversation: {summary_text}"
    }

    return [summary_msg] + recent
