# tools.py

import os
import json

TOOLS_FILE = "tools.json"

def load_tools(debug_enabled=False):
    if not os.path.exists(TOOLS_FILE):
        return []
    try:
        with open(TOOLS_FILE, "r") as f:
            tools = json.load(f)
            if debug_enabled:
                print("[Debug] Tools loaded:", tools)
            return tools
    except Exception as e:
        print(f"[Error] Failed to load tools: {e}")
        return []

def save_tools(tools, debug_enabled=False):
    try:
        with open(TOOLS_FILE, "w") as f:
            json.dump(tools, f, indent=2)
        if debug_enabled:
            print("[Debug] Tools saved.")
    except Exception as e:
        print(f"[Error] Failed to save tools: {e}")

def run_tool(tools, tool_name, args, debug_enabled=False):
    tool = next((t for t in tools if t["name"] == tool_name), None)
    if not tool:
        return f"[Tool Error] Tool '{tool_name}' not found."

    script = tool.get("script", "")
    if not script.strip():
        return f"[Tool Error] Tool '{tool_name}' has no script."

    # Execute the script in a temporary namespace
    namespace = {}
    try:
        exec(script, namespace)
        if "run_tool" not in namespace:
            return f"[Tool Error] run_tool(args) function not defined in '{tool_name}' script."
        result = namespace["run_tool"](args)
        return result
    except Exception as e:
        if debug_enabled:
            print(f"[Debug] Exception while running tool '{tool_name}': {e}")
        return f"[Tool Error] Exception running tool '{tool_name}': {e}"

def add_tool(tools, name, description, script, debug_enabled=False):
    # Check if tool with same name exists
    if any(t['name'] == name for t in tools):
        return f"[Tool Error] A tool with name '{name}' already exists."
    tools.append({"name": name, "description": description, "script": script})
    save_tools(tools, debug_enabled)
    return None

def edit_tool(tools, old_name, new_name, description, script, debug_enabled=False):
    tool = next((t for t in tools if t["name"] == old_name), None)
    if not tool:
        return f"[Tool Error] Tool '{old_name}' not found."

    # If changing the name, ensure no duplicate
    if new_name != old_name and any(t['name'] == new_name for t in tools):
        return f"[Tool Error] A tool with name '{new_name}' already exists."

    tool["name"] = new_name
    tool["description"] = description
    tool["script"] = script
    save_tools(tools, debug_enabled)
    return None

def delete_tool(tools, name, debug_enabled=False):
    idx = next((i for i, t in enumerate(tools) if t["name"] == name), None)
    if idx is None:
        return f"[Tool Error] Tool '{name}' not found."
    del tools[idx]
    save_tools(tools, debug_enabled)
    return None
