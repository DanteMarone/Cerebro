# tools.py

import os
import json
import sys
import tempfile
import importlib.util
from importlib import metadata

TOOLS_FILE = "tools.json"
PLUGIN_DIR = "tool_plugins"
PLUGINS_FILE = "plugins.json"

ENTRY_POINT_GROUP = "cerebro_tools"


def load_plugin_settings():
    """Return the plugin settings mapping plugin name to enabled flag."""
    if os.path.exists(PLUGINS_FILE):
        try:
            with open(PLUGINS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_plugin_settings(data):
    """Persist plugin settings to disk."""
    try:
        with open(PLUGINS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def set_plugin_enabled(name, enabled):
    """Enable or disable a plugin."""
    data = load_plugin_settings()
    if name not in data:
        data[name] = {"enabled": bool(enabled)}
    else:
        data[name]["enabled"] = bool(enabled)
    save_plugin_settings(data)


def install_plugin(src_path, debug_enabled=False):
    """Install a plugin file into the plugin directory."""
    if not os.path.isfile(src_path):
        return f"[Plugin Error] File not found: {src_path}"

    os.makedirs(PLUGIN_DIR, exist_ok=True)
    dest_path = os.path.join(PLUGIN_DIR, os.path.basename(src_path))
    try:
        with open(src_path, "rb") as fsrc, open(dest_path, "wb") as fdst:
            fdst.write(fsrc.read())
        if debug_enabled:
            print(f"[Debug] Installed plugin from {src_path} to {dest_path}")
    except Exception as exc:
        return f"[Plugin Error] Failed to copy plugin: {exc}"

    # attempt to load metadata to register plugin name
    try:
        spec = importlib.util.spec_from_file_location(os.path.basename(dest_path)[:-3], dest_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        meta = getattr(module, "TOOL_METADATA", {})
        name = meta.get("name", os.path.splitext(os.path.basename(dest_path))[0])
        data = load_plugin_settings()
        if name not in data:
            data[name] = {"enabled": True}
            save_plugin_settings(data)
    except Exception as exc:
        if debug_enabled:
            print(f"[Debug] Failed to register plugin settings: {exc}")
    return None


def get_available_plugins(debug_enabled=False):
    """Return metadata for all discovered plugins including disabled ones."""
    plugins = []
    settings = load_plugin_settings()
    changed = False

    if os.path.isdir(PLUGIN_DIR):
        for fname in os.listdir(PLUGIN_DIR):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(PLUGIN_DIR, fname)
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                meta = getattr(module, "TOOL_METADATA", {})
                name = meta.get("name", fname[:-3])
                desc = meta.get("description", "")
                if name not in settings:
                    settings[name] = {"enabled": True}
                    changed = True
                plugins.append({
                    "name": name,
                    "description": desc,
                    "path": path,
                    "enabled": settings[name].get("enabled", True),
                })
            except Exception as exc:
                if debug_enabled:
                    print(f"[Debug] Failed to inspect plugin {path}: {exc}")

    try:
        eps = metadata.entry_points()
        for ep in eps.select(group=ENTRY_POINT_GROUP):
            try:
                module = ep.load()
                meta = getattr(module, "TOOL_METADATA", {})
                if not meta or "name" not in meta:
                    continue
                name = meta["name"]
                desc = meta.get("description", "")
                if name not in settings:
                    settings[name] = {"enabled": True}
                    changed = True
                plugins.append({
                    "name": name,
                    "description": desc,
                    "path": getattr(module, "__file__", ""),
                    "enabled": settings[name].get("enabled", True),
                })
            except Exception as exc:
                if debug_enabled:
                    print(f"[Debug] Failed to load entry point {ep.name}: {exc}")
    except Exception as exc:
        if debug_enabled:
            print(f"[Debug] Failed to read entry points: {exc}")

    if changed:
        save_plugin_settings(settings)
    return plugins

def discover_plugin_tools(debug_enabled=False):
    """Return a list of plugin-based tool definitions."""
    tools = []
    settings = load_plugin_settings()
    changed = False

    # Load tools from local plugin directory
    if os.path.isdir(PLUGIN_DIR):
        for fname in os.listdir(PLUGIN_DIR):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(PLUGIN_DIR, fname)
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                meta = getattr(module, "TOOL_METADATA", None)
                if not meta or "name" not in meta:
                    continue
                name = meta["name"]
                if name not in settings:
                    settings[name] = {"enabled": True}
                    changed = True
                if not settings[name].get("enabled", True):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    script_text = f.read()
                tools.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "plugin_module": module,
                    "script_path": path,
                    "script": script_text,
                    "args": meta.get("args", [])
                })
                if debug_enabled:
                    print(f"[Debug] Loaded plugin tool '{meta['name']}' from {path}")
            except Exception as e:
                print(f"[Error] Failed to load plugin '{path}': {e}")

    # Load tools registered via entry points
    try:
        eps = metadata.entry_points()
        for ep in eps.select(group=ENTRY_POINT_GROUP):
            try:
                module = ep.load()
                meta = getattr(module, "TOOL_METADATA", None)
                if not meta or "name" not in meta:
                    continue
                name = meta["name"]
                if name not in settings:
                    settings[name] = {"enabled": True}
                    changed = True
                if not settings[name].get("enabled", True):
                    continue
                path = getattr(module, "__file__", None)
                script_text = ""
                if path and os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            script_text = f.read()
                    except Exception:
                        pass
                tools.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "plugin_module": module,
                    "script_path": path,
                    "script": script_text,
                    "args": meta.get("args", [])
                })
                if debug_enabled:
                    print(f"[Debug] Loaded plugin tool '{meta['name']}' from entry point")
            except Exception as e:
                print(f"[Error] Failed to load entry point '{ep.name}': {e}")
    except Exception as e:
        if debug_enabled:
            print(f"[Error] Failed to inspect entry points: {e}")

    if changed:
        save_plugin_settings(settings)
    return tools

def load_tools(debug_enabled=False):
    """Load tools from tools.json and any installed plugins."""
    tools = []
    if os.path.exists(TOOLS_FILE):
        try:
            with open(TOOLS_FILE, "r", encoding="utf-8") as f:
                tools = json.load(f)
                if debug_enabled:
                    print("[Debug] Tools loaded:", tools)
        except Exception as e:
            print(f"[Error] Failed to load tools: {e}")

    tools.extend(discover_plugin_tools(debug_enabled))
    return tools

def save_tools(tools, debug_enabled=False):
    try:
        with open(TOOLS_FILE, "w", encoding="utf-8") as f:
            json.dump(tools, f, indent=2)
        if debug_enabled:
            print("[Debug] Tools saved.")
    except Exception as e:
        print(f"[Error] Failed to save tools: {e}")

def run_tool(tools, tool_name, args, debug_enabled=False):
    """Execute the specified tool with the provided arguments."""

    tool = next((t for t in tools if t["name"] == tool_name), None)
    if not tool:
        return f"[Tool Error] Tool '{tool_name}' not found."

    plugin_module = tool.get("plugin_module")
    script_path = tool.get("script_path", "")
    cleanup_tmp = False

    # Prefer a loaded plugin module when available

    if plugin_module and hasattr(plugin_module, "run_tool"):
        try:
            result = plugin_module.run_tool(args)
            if debug_enabled:
                print(f"[Debug] Tool '{tool_name}' output: {result}")
            return result
        except Exception as exc:
            error_msg = f"[Tool Error] Exception running tool '{tool_name}': {exc}"
            if debug_enabled:
                print(f"[Debug] {error_msg}")
            return error_msg

    if not script_path and plugin_module:
        script_path = getattr(plugin_module, "__file__", "")
        if script_path and os.path.exists(script_path):
            tool["script_path"] = script_path

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

    module_name = f"_tool_{tool_name}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if not spec or not spec.loader:
        return f"[Tool Error] Failed to load script for tool '{tool_name}'"

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        if not hasattr(module, "run_tool"):
            return f"[Tool Error] Tool '{tool_name}' has no run_tool function."
        result = module.run_tool(args)
        return result
    except Exception as exc:
        error_msg = f"[Tool Error] Exception running tool '{tool_name}': {exc}"
        if debug_enabled:
            print(f"[Debug] {error_msg}")
        return error_msg
    finally:

        # Clean up loaded module and temporary script if needed
        sys.modules.pop(module_name, None)
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
        with open(script_path, "w", encoding="utf-8") as f:
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
            with open(tool["script_path"], "w", encoding="utf-8") as f:
                f.write(script)
            tool["script"] = script
            if "plugin_module" in tool:
                # convert plugin tool to local script-based tool
                del tool["plugin_module"]
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