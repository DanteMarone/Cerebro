# tools.py

import os
import json
import subprocess
import sys
import tempfile

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

    script_path = tool.get("script_path", "")
    cleanup_tmp = False

    if not script_path:
        script_content = tool.get("script")
        if not script_content:
            return f"[Tool Error] Tool '{tool_name}' has no script."
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".py")
        tmp_file.write(script_content.encode())
        tmp_file.close()
        script_path = tmp_file.name
        cleanup_tmp = True
        if debug_enabled:
            print(f"[Debug] Created temporary script for '{tool_name}' at: {script_path}")

    if not os.path.exists(script_path):
        return f"[Tool Error] Script path for tool '{tool_name}' does not exist: {script_path}"

    try:
        # Use subprocess.run with a timeout and capture output
        result = subprocess.run(
            [sys.executable, script_path] + [json.dumps(args)],
            capture_output=True,
            text=True,
            check=True,  # Raise an exception if the subprocess fails
            timeout=10,  # Set a timeout (e.g., 10 seconds)
        )

        if debug_enabled:
            print(f"[Debug] Tool '{tool_name}' output: {result.stdout}")

        return result.stdout

    except subprocess.CalledProcessError as e:
        error_msg = f"[Tool Error] Error running tool '{tool_name}': {e.stderr}"
        if debug_enabled:
            print(f"[Debug] {error_msg}")
        return error_msg
    except subprocess.TimeoutExpired as e:
        error_msg = f"[Tool Error] Tool '{tool_name}' timed out."
        if debug_enabled:
            print(f"[Debug] {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"[Tool Error] Exception running tool '{tool_name}': {e}"
        if debug_enabled:
            print(f"[Debug] {error_msg}")
        return error_msg
    finally:
        if cleanup_tmp:
            try:
                os.remove(script_path)
                if debug_enabled:
                    print(f"[Debug] Deleted temporary script: {script_path}")
            except Exception:
                pass

def add_tool(tools, name, description, script, debug_enabled=False):
    if any(t['name'] == name for t in tools):
        return f"[Tool Error] A tool with name '{name}' already exists."

    # Get the directory of the current script (tools.py)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Construct the absolute path for the new tool's script
    script_path = os.path.join(current_dir, f"{name}.py")

    # Create the script file
    try:
        with open(script_path, "w") as f:
            f.write(script)
        if debug_enabled:
            print(f"[Debug] Created script file at: {script_path}")
    except Exception as e:
        return f"[Tool Error] Failed to create script file: {e}"

    tools.append({
        "name": name,
        "description": description,
        "script": script,
        "script_path": script_path,
    })
    save_tools(tools, debug_enabled)
    return None

def edit_tool(tools, old_name, new_name, description, script, debug_enabled=False):
    tool = next((t for t in tools if t["name"] == old_name), None)
    if not tool:
        return f"[Tool Error] Tool '{old_name}' not found."

    if new_name != old_name and any(t['name'] == new_name for t in tools):
        return f"[Tool Error] A tool with name '{new_name}' already exists."

    # Update the script file if the script has changed
    if script != tool.get("script", ""):
        try:
            with open(tool["script_path"], "w") as f:
                f.write(script)
            tool["script"] = script
            if debug_enabled:
                print(f"[Debug] Updated script file at: {tool['script_path']}")
        except Exception as e:
            return f"[Tool Error] Failed to update script file: {e}"

    tool["name"] = new_name
    tool["description"] = description
    save_tools(tools, debug_enabled)
    return None

def delete_tool(tools, name, debug_enabled=False):
    tool = next((t for t in tools if t["name"] == name), None)
    if not tool:
        return f"[Tool Error] Tool '{name}' not found."

    # Delete the associated script file
    script_path = tool.get("script_path", "")
    if script_path and os.path.exists(script_path):
        try:
            os.remove(script_path)
            if debug_enabled:
                print(f"[Debug] Deleted script file: {script_path}")
        except Exception as e:
            print(f"[Error] Failed to delete script file: {e}")

    tools.remove(tool)
    save_tools(tools, debug_enabled)
    return None