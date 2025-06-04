# tasks.py

import os
import json
import uuid
from datetime import datetime

TASKS_FILE = "tasks.json"

def load_tasks(debug_enabled=False):
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r") as f:
            tasks = json.load(f)
            for t in tasks:
                t.setdefault("status", "pending")
            if debug_enabled:
                print("[Debug] Tasks loaded:", tasks)
            return tasks
    except Exception as e:
        print(f"[Error] Failed to load tasks: {e}")
        return []

def save_tasks(tasks, debug_enabled=False):
    try:
        with open(TASKS_FILE, "w") as f:
            json.dump(tasks, f, indent=2)
        if debug_enabled:
            print("[Debug] Tasks saved.")
    except Exception as e:
        print(f"[Error] Failed to save tasks: {e}")

def add_task(tasks, agent_name, prompt, due_time, creator="user", debug_enabled=False):
    """
    Creates a new task and saves to tasks.json
    :param tasks: current list of tasks in memory
    :param agent_name: name of the agent that will receive the prompt
    :param prompt: the text to send
    :param due_time: ISO 8601 string or "YYYY-MM-DD HH:MM:SS" local time
    :param creator: "user" or "agent"
    """
    task_id = str(uuid.uuid4())
    new_task = {
        "id": task_id,
        "creator": creator,
        "agent_name": agent_name,
        "prompt": prompt,
        "due_time": due_time,
        "status": "pending",
    }
    tasks.append(new_task)
    save_tasks(tasks, debug_enabled)
    return task_id

def edit_task(tasks, task_id, agent_name, prompt, due_time, debug_enabled=False):
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["agent_name"] = agent_name
    task["prompt"] = prompt
    task["due_time"] = due_time
    save_tasks(tasks, debug_enabled)
    return None

def delete_task(tasks, task_id, debug_enabled=False):
    idx = next((i for i, t in enumerate(tasks) if t["id"] == task_id), None)
    if idx is None:
        return f"[Task Error] Task '{task_id}' not found."
    del tasks[idx]
    save_tasks(tasks, debug_enabled)
    return None

def set_task_status(tasks, task_id, status, debug_enabled=False):
    """Set the status of a task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["status"] = status
    save_tasks(tasks, debug_enabled)
    return None