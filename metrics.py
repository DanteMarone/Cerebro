import json
import os

METRICS_FILE = "metrics.json"


def load_metrics(debug_enabled=False):
    """Load metrics from disk."""
    if not os.path.exists(METRICS_FILE):
        return {"tool_usage": {}, "task_completion_counts": {}, "response_times": {}}
    try:
        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if debug_enabled:
            print("[Debug] Metrics loaded", data)
        return data
    except Exception as e:
        print(f"[Error] Failed to load metrics: {e}")
        return {"tool_usage": {}, "task_completion_counts": {}, "response_times": {}}


def save_metrics(metrics, debug_enabled=False):
    """Save metrics to disk."""
    try:
        with open(METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        if debug_enabled:
            print("[Debug] Metrics saved")
    except Exception as e:
        print(f"[Error] Failed to save metrics: {e}")


def record_tool_usage(metrics, tool_name, debug_enabled=False):
    """Increment usage count for a tool."""
    metrics.setdefault("tool_usage", {})
    metrics["tool_usage"][tool_name] = metrics["tool_usage"].get(tool_name, 0) + 1
    save_metrics(metrics, debug_enabled)


def record_task_completion(metrics, agent_name, debug_enabled=False):
    """Increment completed task count for an agent."""
    metrics.setdefault("task_completion_counts", {})
    metrics["task_completion_counts"][agent_name] = metrics["task_completion_counts"].get(agent_name, 0) + 1
    save_metrics(metrics, debug_enabled)


def record_response_time(metrics, agent_name, elapsed, debug_enabled=False):
    """Record response time for an agent."""
    metrics.setdefault("response_times", {})
    entry = metrics["response_times"].setdefault(agent_name, {"total_time": 0.0, "count": 0})
    entry["total_time"] += elapsed
    entry["count"] += 1
    save_metrics(metrics, debug_enabled)


def average_response_time(metrics, agent_name):
    """Return the average response time for an agent."""
    entry = metrics.get("response_times", {}).get(agent_name)
    if entry and entry.get("count"):
        return entry["total_time"] / entry["count"]
    return 0.0
