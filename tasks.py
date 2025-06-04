# tasks.py

import os
import json
import uuid
import sys
import platform
import subprocess
from datetime import datetime

TASKS_FILE = "tasks.json"


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
        with open(TASKS_FILE, "r") as f:
            tasks = json.load(f)
            for t in tasks:
                t.setdefault("status", "pending")
                t.setdefault("repeat_interval", 0)
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
        "status": "pending",
        "repeat_interval": repeat_interval,
    }
    tasks.append(new_task)
    save_tasks(tasks, debug_enabled)
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
    if os_schedule:
        _remove_os_task(task_id, debug_enabled)
    return None

def set_task_status(tasks, task_id, status, debug_enabled=False):
    """Set the status of a task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["status"] = status
    save_tasks(tasks, debug_enabled)
    return None

def update_task_due_time(tasks, task_id, due_time, debug_enabled=False, os_schedule=False):
    """Update the due time for a task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"[Task Error] Task '{task_id}' not found."
    task["due_time"] = due_time
    save_tasks(tasks, debug_enabled)
    if os_schedule:
        _remove_os_task(task_id, debug_enabled)
        _schedule_os_task(task_id, due_time, debug_enabled)
    return None
