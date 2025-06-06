"""Utility functions for managing agent workflows."""

import os
import json
import uuid

WORKFLOWS_FILE = "workflows.json"


def load_workflows(debug_enabled=False):
    if not os.path.exists(WORKFLOWS_FILE):
        return []
    try:
        with open(WORKFLOWS_FILE, "r", encoding="utf-8") as f:
            workflows = json.load(f)
        if debug_enabled:
            print("[Debug] Workflows loaded", workflows)
        return workflows
    except Exception as e:
        print(f"[Error] Failed to load workflows: {e}")
        return []


def save_workflows(workflows, debug_enabled=False):
    try:
        with open(WORKFLOWS_FILE, "w", encoding="utf-8") as f:
            json.dump(workflows, f, indent=2)
        if debug_enabled:
            print("[Debug] Workflows saved")
    except Exception as e:
        print(f"[Error] Failed to save workflows: {e}")


def add_workflow(workflows, name, wf_type, coordinator=None, agents=None, max_turns=10, steps=None, debug_enabled=False):
    """Create a new workflow and add it to the list."""
    wf_id = str(uuid.uuid4())
    workflow = {
        "id": wf_id,
        "name": name,
        "type": wf_type,
        "coordinator": coordinator,
        "agents": agents or [],
        "max_turns": max_turns,
        "steps": steps or [],
    }
    workflows.append(workflow)
    save_workflows(workflows, debug_enabled)
    return wf_id


def edit_workflow(workflows, wf_id, **updates):
    wf = next((w for w in workflows if w["id"] == wf_id), None)
    if not wf:
        return f"[Workflow Error] Workflow '{wf_id}' not found."
    wf.update(updates)
    save_workflows(workflows)
    return None


def delete_workflow(workflows, wf_id):
    idx = next((i for i, w in enumerate(workflows) if w["id"] == wf_id), None)
    if idx is None:
        return f"[Workflow Error] Workflow '{wf_id}' not found."
    workflows.pop(idx)
    save_workflows(workflows)
    return None
