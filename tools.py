# tools.py

import os
import json
import sys
import tempfile
import importlib.util
from importlib import metadata
from typing import List, Dict, Any, Type
from pydantic import BaseModel

TOOLS_FILE = "tools.json"
PLUGIN_DIR = "tool_plugins"
PLUGINS_FILE = "plugins.json"

ENTRY_POINT_GROUP = "cerebro_tools"


class BaseTool(BaseModel):
    """Base class for all structured tools."""
    name: str
    description: str
    args_schema: Type[BaseModel]

    def run(self, args: BaseModel) -> str:
        """Execute the tool with validated arguments."""
        raise NotImplementedError("Tool must implement run method")

    class Config:
        arbitrary_types_allowed = True


class SchemaGenerator:
    """Generates JSON schemas for tools."""

    @staticmethod
    def generate(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate a JSON schema that allows selecting one of the provided tools
        or returning a normal response.
        """
        tool_options = []

        for tool in tools:
            if "args_schema" in tool:
                # Pydantic-based tool
                # tool is a dict representation of the loaded tool,
                # but we need the actual schema.
                # In discover_plugin_tools, we will store the class or instance.
                # Let's assume tool['instance'] holds the BaseTool instance
                # OR tool['args_schema'] holds the Pydantic model class.

                tool_name = tool["name"]
                args_schema = tool["args_schema"]

                # Get the schema for the arguments
                schema = args_schema.model_json_schema()
                # Remove title/definitions if not needed or inline them
                # For simplicity, we use the properties directly.

                tool_option = {
                    "type": "object",
                    "properties": {
                        "name": {"const": tool_name},
                        "args": schema
                    },
                    "required": ["name", "args"]
                }
                tool_options.append(tool_option)

            else:
                # Legacy tool
                tool_name = tool["name"]
                args = tool.get("args", [])

                # Assume all legacy args are required strings
                arg_props = {arg: {"type": "string"} for arg in args}

                tool_option = {
                    "type": "object",
                    "properties": {
                        "name": {"const": tool_name},
                        "args": {
                            "type": "object",
                            "properties": arg_props,
                            "required": args if args else []
                        }
                    },
                    "required": ["name", "args"]
                }
                tool_options.append(tool_option)

        # Construct the final schema
        # We allow either a "tool_request" with one of the tool options
        # OR no tool request (which we handle by making tool_request optional/nullable
        # or by structure).
        # The structure requested by `tool_utils.py` is:
        # { "role": "assistant", "content": "...", "tool_request": { ... } }

        schema = {
            "type": "object",
            "properties": {
                "role": {"const": "assistant"},
                "content": {"type": "string"},
                "tool_request": {
                    "anyOf": [
                        {"type": "null"},
                        {
                            "oneOf": tool_options
                        }
                    ]
                }
            },
            "required": ["role", "content"]
        }

        return schema


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

        # Check for BaseTool subclass first
        name = None
        if hasattr(module, "TOOL_MODEL") and issubclass(module.TOOL_MODEL, BaseTool):
            # Instantiate to get name if it's a property, or get field default
            # But usually name is a field. We can access the default value from schema or instantiate.
            # Easier to instantiate if no args, but BaseTool has fields.
            # Let's assume TOOL_MODEL is the class, and we need to look at __fields__ or just instantiate it?
            # Wait, BaseTool definition above:
            # class BaseTool(BaseModel): name: str ...
            # So we expect TOOL_MODEL to be a class that has default values for name/description?
            # Or we expect an INSTANCE of BaseTool?
            # Let's assume an INSTANCE is exported as TOOL_INSTANCE, or TOOL_MODEL is the class and we need to instantiate it.
            # For Pydantic models, fields usually don't have defaults unless specified.
            # Let's assume the pattern is:
            # class MyTool(BaseTool): ...
            # TOOL_DEFINITION = MyTool(name="...", description="...", args_schema=MyArgs)

            if hasattr(module, "TOOL_DEFINITION") and isinstance(module.TOOL_DEFINITION, BaseTool):
                name = module.TOOL_DEFINITION.name

        if not name:
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

                name = ""
                desc = ""

                # Check for Pydantic Tool
                if hasattr(module, "TOOL_DEFINITION") and isinstance(module.TOOL_DEFINITION, BaseTool):
                    name = module.TOOL_DEFINITION.name
                    desc = module.TOOL_DEFINITION.description
                else:
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
                name = ""
                desc = ""

                if hasattr(module, "TOOL_DEFINITION") and isinstance(module.TOOL_DEFINITION, BaseTool):
                    name = module.TOOL_DEFINITION.name
                    desc = module.TOOL_DEFINITION.description
                else:
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

    # Helper to process module
    def process_module(module, path, source="local"):
        nonlocal changed
        try:
            name = None
            desc = ""
            args = []
            dependencies = []
            needs_config = False
            tool_instance = None

            # Check for Pydantic Tool Definition
            if hasattr(module, "TOOL_DEFINITION") and isinstance(module.TOOL_DEFINITION, BaseTool):
                tool_instance = module.TOOL_DEFINITION
                name = tool_instance.name
                desc = tool_instance.description
                # We won't list args here like legacy, but we can if we want to.
                # But we should store the instance/schema.

            # Fallback to Legacy Metadata
            if not name:
                meta = getattr(module, "TOOL_METADATA", None)
                if meta and "name" in meta:
                    name = meta["name"]
                    desc = meta.get("description", "")
                    args = meta.get("args", [])
                    dependencies = meta.get("dependencies", [])
                    needs_config = meta.get("needs_config", False)

            if not name:
                return

            if name not in settings:
                settings[name] = {"enabled": True}
                changed = True

            if not settings[name].get("enabled", True):
                return

            with open(path, "r", encoding="utf-8") as f:
                script_text = f.read()

            tool_def = {
                "name": name,
                "description": desc,
                "plugin_module": module,
                "script_path": path,
                "script": script_text,
                "dependencies": dependencies,
                "needs_config": needs_config,
            }

            if tool_instance:
                tool_def["tool_instance"] = tool_instance
                tool_def["args_schema"] = tool_instance.args_schema
            else:
                tool_def["args"] = args

            tools.append(tool_def)
            if debug_enabled:
                print(f"[Debug] Loaded plugin tool '{name}' from {source}")

        except Exception as e:
            print(f"[Error] Failed to load plugin '{path}': {e}")

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
                process_module(module, path, "local")
                if getattr(module, "TOOL_METADATA", {}).get("name") not in settings and getattr(module, "TOOL_DEFINITION", None) is None:
                    # Check if we need to update settings (hacky logic replication)
                    pass
            except Exception as e:
                print(f"[Error] Failed to load plugin '{path}': {e}")

    # Load tools registered via entry points
    try:
        eps = metadata.entry_points()
        for ep in eps.select(group=ENTRY_POINT_GROUP):
            try:
                module = ep.load()
                path = getattr(module, "__file__", "")
                if path and os.path.exists(path):
                    process_module(module, path, "entry_point")
            except Exception as e:
                print(f"[Error] Failed to load entry point '{ep.name}': {e}")
    except Exception as e:
        if debug_enabled:
            print(f"[Error] Failed to inspect entry points: {e}")

    if changed:
        save_plugin_settings(settings)

    # Re-save settings if we found new ones (process_module didn't handle saving)
    # This is a bit disjointed due to the refactor, but we can just save current settings if modified.
    # Actually process_module reads/writes settings? No, it reads.
    # We should iterate again or just trust that load_plugin_settings returns a mutable dict
    # but we reload it inside process_module which is bad.
    # Let's fix this properly:

    # Simplified logic: just run the discovery again properly or fix process_module.
    # For now, I'll rely on the fact that existing logic handles settings.
    # I modified process_module to use `settings` from outer scope, but I need to make sure I save it.

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
        # We only save non-plugin tools to tools.json
        # Filter out tools that have 'plugin_module' or 'tool_instance'
        to_save = [t for t in tools if not t.get("plugin_module") and not t.get("tool_instance")]
        with open(TOOLS_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2)
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
    tool_instance = tool.get("tool_instance")
    script_path = tool.get("script_path", "")
    cleanup_tmp = False

    # Priority 1: Pydantic Tool Instance
    if tool_instance:
        try:
            # Validate args
            if hasattr(tool_instance, "args_schema"):
                try:
                    validated_args = tool_instance.args_schema(**args)
                except Exception as e:
                    return f"[Tool Error] Invalid arguments for '{tool_name}': {e}"

                result = tool_instance.run(validated_args)
            else:
                # Should not happen if correctly defined
                result = tool_instance.run(args)

            if debug_enabled:
                print(f"[Debug] Tool '{tool_name}' output: {result}")
            return result
        except Exception as exc:
            error_msg = f"[Tool Error] Exception running tool '{tool_name}': {exc}"
            if debug_enabled:
                print(f"[Debug] {error_msg}")
            return error_msg

    # Priority 2: Legacy Plugin Module
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

    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, f"{name}.py")

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

    if script != tool.get("script", ""):
        try:
            with open(tool["script_path"], "w", encoding="utf-8") as f:
                f.write(script)
            tool["script"] = script
            if "plugin_module" in tool:
                del tool["plugin_module"]
            if "tool_instance" in tool:
                del tool["tool_instance"]
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
