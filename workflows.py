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


def add_workflow(
    workflows,
    name,
    wf_type,
    coordinator=None,
    agents=None,
    max_turns=10,
    steps=None,
    debug_enabled=False,
):
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


def find_workflow_by_name(workflows, name):
    """Return the workflow dict matching the given name or ``None``."""
    return next((wf for wf in workflows if wf.get("name") == name), None)


def execute_workflow(workflow, start_prompt, agents_data=None):
    """Execute a workflow and return the log lines and final result."""
    log_lines = []
    if not workflow:
        return log_lines, "[Workflow Error] Invalid workflow"

    wf_type = workflow.get("type")
    if wf_type == "user_managed":
        current = start_prompt
        for step in workflow.get("steps", []):
            agent = step.get("agent", "Unknown")
            prompt = step.get("prompt", "")
            message = f"[{agent}]: {prompt or current}"
            log_lines.append(message)
            current = message
        result = current or ""
    else:  # agent_managed
        coordinator = workflow.get("coordinator", "Coordinator")
        agents = workflow.get("agents", [])
        max_turns = workflow.get("max_turns", 10)

        info_lines = []
        if agents_data:
            for name in agents:
                settings = agents_data.get(name, {})
                desc = settings.get("description", "")
                tools = ", ".join(settings.get("tools_enabled", []))
                tool_text = f" Tools: {tools}" if tools else ""
                info_lines.append(f"{name} - {desc}{tool_text}")
        else:
            info_lines = agents

        agents_info = "\n".join(f"- {line}" for line in info_lines)

        turn = 1
        log_lines.append(
            f"[{coordinator}]: Task: {start_prompt}\n"
            f"Current turn {turn}/{max_turns}\n"
            f"Available agents:\n{agents_info}"
        )

        conversation = []
        for agent in agents:
            log_lines.append(f"[{coordinator}]: {agent}")
            log_lines.append(
                f"[{agent}]: Working on '{start_prompt}' "
                f"(turn {turn}/{max_turns})"
            )
            conversation.append(f"{agent} response")
            turn += 1
            if turn > max_turns:
                break
            context = "; ".join(conversation)
            log_lines.append(
                f"[{coordinator}]: Context so far: {context}\n"
                f"Current turn {turn}/{max_turns}"
            )

        log_lines.append(f"[{coordinator}]: Finalizing response.")
        result = "Workflow completed"

    return log_lines, result
