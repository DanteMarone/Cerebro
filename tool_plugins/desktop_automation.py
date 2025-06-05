TOOL_METADATA = {
    "name": "desktop-automation",
    "description": "Perform OS-level actions such as launching programs or moving files.",
    "args": ["action", "target", "destination"]
}

import os
import platform
import subprocess
import shutil


def run_tool(args):
    """Execute a desktop automation command."""
    action = args.get("action")
    target = args.get("target")
    dest = args.get("destination")

    if action == "launch":
        if not target:
            return "[desktop-automation Error] Missing target"
        try:
            if platform.system() == "Windows":
                os.startfile(target)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
            return f"Launched {target}"
        except Exception as e:
            return f"[desktop-automation Error] {e}"

    if action == "move":
        if not target or not dest:
            return "[desktop-automation Error] Missing target or destination"
        try:
            shutil.move(target, dest)
            return f"Moved {target} to {dest}"
        except Exception as e:
            return f"[desktop-automation Error] {e}"

    return "[desktop-automation Error] Unknown action"
