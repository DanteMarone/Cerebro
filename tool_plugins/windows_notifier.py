TOOL_METADATA = {
    "name": "windows-notifier",
    "description": "Send a Windows 11 notification using win10toast.",
    "args": ["title", "message"]
}


def run_tool(args):
    """Display a Windows notification."""
    title = args.get("title", "Cerebro")
    message = args.get("message", "Notification from Cerebro")
    try:
        from win10toast import ToastNotifier
    except Exception:
        return "[windows-notifier Error] win10toast not installed."
    try:
        toaster = ToastNotifier()
        # Run notification in a separate thread to prevent WNDPROC errors
        toaster.show_toast(title, message, duration=5, threaded=True)
        return "Notification sent"
    except Exception as e:
        return f"[windows-notifier Error] {e}"
