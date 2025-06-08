# tasks.py

import os
import json
import uuid
import sys
import platform
import subprocess
from datetime import datetime

TASKS_FILE = "tasks.json"

# Supported task statuses. Additional states like ``in_progress`` and
# ``failed`` can be assigned by the UI or other components.
STATUS_CHOICES = [
    "pending",
    "in_progress",
    "completed",
    "failed",
    "on_hold",
]


def _schedule_os_task(task_id, due_time, debug_enabled=False):
    """Register a task with the OS scheduler."""
    script = os.path.join(os.path.dirname(__file__), "run_task.py")
    try:
        dt = (
            datetime.fromisoformat(due_time)
            if "T" in due_time
            else datetime.strptime(due_time, "%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        if debug_enabled:
            print(f"[Debug] Invalid due_time for scheduling: {due_time}")
        return

    if platform.system() == "Windows":
        date_str = dt.strftime("%m/%d/%Y")
        time_str = dt.strftime("%H:%M")
        cmd = [
            "schtasks",
            "/Create",
            "/SC",
            "ONCE",
            "/TN",
            f"Cerebro_{task_id}",
            "/TR",
            f'\"{sys.executable}\" \"{script}\" {task_id}',
            "/ST",
            time_str,
            "/SD",
            date_str,
            "/F",
        ]
        try:
            subprocess.run(cmd, check=True)
            if debug_enabled:
                print(f"[Debug] Scheduled Windows task {task_id}")
        except Exception as e:
            if debug_enabled:
                print(f"[Debug] Failed to schedule Windows task: {e}")
    else:
        cron_line = (
            f"{dt.minute} {dt.hour} {dt.day} {dt.month} * "
            f"{sys.executable} {script} {task_id} # cerebro_{task_id}\n"
        )
        try:
            result = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, check=False
            )
            existing = result.stdout if result.returncode == 0 else ""
            new_cron = existing + cron_line
            subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)
            if debug_enabled:
                print(f"[Debug] Scheduled cron job for task {task_id}")
        except Exception as e:
            if debug_enabled:
                print(f"[Debug] Failed to schedule cron job: {e}")


def _remove_os_task(task_id, debug_enabled=False):
    """Remove a task from the OS scheduler."""
    if platform.system() == "Windows":
        cmd = ["schtasks", "/Delete", "/TN", f"Cerebro_{task_id}", "/F"]
        try:
            subprocess.run(cmd, check=True)
            if debug_enabled:
                print(f"[Debug] Removed Windows task {task_id}")
        except Exception as e:
            if debug_enabled:
                print(f"[Debug] Failed to remove Windows task: {e}")
    else:
        try:
            result = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                return
            lines = [
                line
                for line in result.stdout.splitlines()
                if f"# cerebro_{task_id}" not in line
            ]
            new_cron = "\n".join(lines) + "\n"
            subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)
            if debug_enabled:
                print(f"[Debug] Removed cron job for task {task_id}")
        except Exception as e:
            if debug_enabled:
                print(f"[Debug] Failed to remove cron job: {e}")

def load_tasks(debug_enabled=False):
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            tasks = json.load(f)
            for t in tasks:
                t.setdefault("status", "pending")
                t.setdefault("repeat_interval", 0)
                t.setdefault("created_time", t.get("due_time", datetime.utcnow().isoformat()))
            if debug_enabled:
                print("[Debug] Tasks loaded:", tasks)
            return tasks
    except Exception as e:
        print(f"[Error] Failed to load tasks: {e}")
        return []

def save_tasks(tasks, debug_enabled=False):
    try:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)
        if debug_enabled:
            print("[Debug] Tasks saved.")
    except Exception as e:
        print(f"[Error] Failed to save tasks: {e}")

def add_task(
    tasks,
    agent_name,
    prompt,
    due_time,
    creator="user",
    repeat_interval=0,
    debug_enabled=False,
    os_schedule=False,
):
    """
    Creates a new task and saves to tasks.json
    :param tasks: current list of tasks in memory
    :param agent_name: name of the agent that will receive the prompt
    :param prompt: the text to send
    :param due_time: ISO 8601 string or "YYYY-MM-DD HH:MM:SS" local time
    :param creator: "user" or "agent"
    :param repeat_interval: minutes between repeats, 0 for none
    """
    task_id = str(uuid.uuid4())
    new_task = {
        "id": task_id,
        "creator": creator,
        "agent_name": agent_name,
        "prompt": prompt,
        "due_time": due_time,
        "created_time": datetime.utcnow().isoformat(),
        "status": "pending",
        "repeat_interval": repeat_interval,
    }
    tasks.append(new_task)
    save_tasks(tasks, debug_enabled)
    if debug_enabled:
        print(
            f"[Debug] Added task {task_id} for agent '{agent_name}'"
            f" due {due_time} (repeat every {repeat_interval} min)"
        )
    if os_schedule:
        _schedule_os_task(task_id, due_time, debug_enabled)
    return task_id

def edit_task(
    tasks,
    task_id,
    agent_name,
    prompt,
    due_time,
    repeat_interval=0,
    debug_enabled=False,
    os_schedule=False,
):
    """Edit an existing task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["agent_name"] = agent_name
    task["prompt"] = prompt
    task["due_time"] = due_time
    task["repeat_interval"] = repeat_interval
    save_tasks(tasks, debug_enabled)
    if debug_enabled:
        print(
            f"[Debug] Edited task {task_id}: agent='{agent_name}', due {due_time}, repeat {repeat_interval}"
        )
    if os_schedule:
        _remove_os_task(task_id, debug_enabled)
        _schedule_os_task(task_id, due_time, debug_enabled)
    return None

def delete_task(tasks, task_id, debug_enabled=False, os_schedule=False):
    idx = next((i for i, t in enumerate(tasks) if t["id"] == task_id), None)
    if idx is None:
        return f"[Task Error] Task '{task_id}' not found."
    del tasks[idx]
    save_tasks(tasks, debug_enabled)
    if debug_enabled:
        print(f"[Debug] Deleted task {task_id}")
    if os_schedule:
        _remove_os_task(task_id, debug_enabled)
    return None

def duplicate_task(tasks, task_id, debug_enabled=False, os_schedule=False):
    """Duplicate an existing task and return the new task id."""
    original = next((t for t in tasks if t["id"] == task_id), None)
    if not original:
        return None
    new_task = original.copy()
    new_task["id"] = str(uuid.uuid4())
    new_task["created_time"] = datetime.utcnow().isoformat()
    tasks.append(new_task)
    save_tasks(tasks, debug_enabled)
    if debug_enabled:
        print(f"[Debug] Duplicated task {task_id} -> {new_task['id']}")
    if os_schedule:
        _schedule_os_task(new_task["id"], new_task.get("due_time", ""), debug_enabled)
    return new_task["id"]

def set_task_status(tasks, task_id, status, debug_enabled=False):
    """Set the status of a task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["status"] = status
    save_tasks(tasks, debug_enabled)
    if debug_enabled:
        print(f"[Debug] Set task {task_id} status to '{status}'")
    return None

def update_task_agent(tasks, task_id, agent_name, debug_enabled=False):
    """Update the agent assigned to a task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["agent_name"] = agent_name
    save_tasks(tasks, debug_enabled)
    if debug_enabled:
        print(f"[Debug] Updated task {task_id} agent to {agent_name}")
    return None

def update_task_due_time(tasks, task_id, due_time, debug_enabled=False, os_schedule=False):
    """Update the due time for a task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["due_time"] = due_time
    save_tasks(tasks, debug_enabled)
    if debug_enabled:
        print(f"[Debug] Updated task {task_id} due time to {due_time}")
    if os_schedule:
        _remove_os_task(task_id, debug_enabled)
        _schedule_os_task(task_id, due_time, debug_enabled)
    return None


def compute_task_progress(task, now=None):
    """Return progress percentage from creation to due time."""
    now = now or datetime.utcnow()
    due_str = task.get("due_time", "")
    created_str = task.get("created_time", "")
    try:
        due_dt = datetime.fromisoformat(due_str) if "T" in due_str else datetime.strptime(due_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0
    try:
        created_dt = (
            datetime.fromisoformat(created_str)
            if "T" in created_str
            else datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        created_dt = now
    total = (due_dt - created_dt).total_seconds()
    if total <= 0:
        return 100 if now >= due_dt else 0
    elapsed = (now - created_dt).total_seconds()
    percent = int(max(0, min(100, (elapsed / total) * 100)))
    return percent


def compute_task_times(task, now=None):
    """Return elapsed and remaining seconds for a task."""
    now = now or datetime.utcnow()
    due_str = task.get("due_time", "")
    created_str = task.get("created_time", "")
    try:
        due_dt = (
            datetime.fromisoformat(due_str)
            if "T" in due_str
            else datetime.strptime(due_str, "%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        return 0, 0
    try:
        created_dt = (
            datetime.fromisoformat(created_str)
            if "T" in created_str
            else datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        created_dt = now

    elapsed = max(0, int((now - created_dt).total_seconds()))
    remaining = max(0, int((due_dt - now).total_seconds()))
    return elapsed, remaining
