import json
import sys
import os
from tool_plugins.windows_notifier import run_tool as notify

TASKS_FILE = "tasks.json"


def main(task_id):
    if not os.path.exists(TASKS_FILE):
        return
    with open(TASKS_FILE, "r") as f:
        tasks = json.load(f)
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        return
    title = "Cerebro Task"
    message = f"{task.get('agent_name', '')}: {task.get('prompt', '')}"
    try:
        notify({"title": title, "message": message})
    except Exception:
        pass
    task["status"] = "completed"
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
