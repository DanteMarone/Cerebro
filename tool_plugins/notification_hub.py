TOOL_METADATA = {
    "name": "notification-hub",
    "description": "Send desktop notifications with optional delay, sound and push webhook.",
    "args": ["title", "message", "delay", "sound", "push_url"],
    "dependencies": ["requests", "plyer", "win10toast"],
}

import sys
import threading
import subprocess
import requests


def _play_sound(path):
    try:
        if not path:
            return
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            subprocess.Popen(["aplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _desktop_notify(title, message):
    if sys.platform == "win32":
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            # Use threaded=True to avoid blocking or crashing the main thread
            toaster.show_toast(title, message, duration=5, threaded=True)
            return True
        except Exception:
            return False
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="Cerebro")
        return True
    except Exception:
        return False


def _push_notify(url, title, message):
    if not url:
        return
    try:
        requests.post(url, json={"title": title, "message": message}, timeout=5)
    except Exception:
        pass


def run_tool(args):
    """Display a notification with optional delay, sound and push webhook."""
    title = args.get("title", "Cerebro")
    message = args.get("message", "Notification")
    delay = int(args.get("delay", 0))
    sound = args.get("sound")
    push_url = args.get("push_url")

    def notify():
        _desktop_notify(title, message)
        if sound:
            _play_sound(sound)
        if push_url:
            _push_notify(push_url, title, message)

    if delay > 0:
        threading.Timer(delay, notify).start()
        return f"Notification scheduled in {delay} seconds"

    notify()
    return "Notification sent"
