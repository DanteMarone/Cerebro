TOOL_METADATA = {
    "name": "ar-overlay",
    "description": "Display a floating desktop overlay message.",
    "args": ["message"],
}

import os
import subprocess
import sys
import textwrap


def run_tool(args):
    """Show an HUD-style overlay message using Tkinter."""
    message = args.get("message", "Cerebro")
    try:
        script = textwrap.dedent(
            """
            import sys
            import tkinter as tk

            msg = sys.argv[1] if len(sys.argv) > 1 else "Cerebro"
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes('-topmost', True)
            root.attributes('-alpha', 0.85)
            root.configure(bg='black')
            label = tk.Label(root, text=msg, fg='white', bg='black', font=('Segoe UI', 12, 'bold'))
            label.pack(ipadx=10, ipady=5)
            root.update_idletasks()
            x = root.winfo_screenwidth() - root.winfo_reqwidth() - 20
            root.geometry(f'+{x}+40')
            root.after(5000, root.destroy)
            root.mainloop()
            """
        )
        if sys.platform != 'win32' and not os.environ.get('DISPLAY'):
            return "[ar-overlay Warning] Display not available."
        subprocess.Popen([sys.executable, '-c', script, message])
        return "Overlay shown"
    except Exception as e:
        return f"[ar-overlay Error] {e}"
