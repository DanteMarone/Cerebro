import os
from datetime import datetime

LOG_FILE = "debug.log"
MAX_SIZE_MB = 10


def set_log_size_limit(mb: float):
    """Set the maximum log size in megabytes."""
    global MAX_SIZE_MB
    try:
        MAX_SIZE_MB = max(0.001, float(mb))
    except (TypeError, ValueError):
        MAX_SIZE_MB = 10


def log_debug(message: str, enabled: bool = False):
    """Append a message to the debug log if enabled."""
    if not enabled:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Writing to log failed, fall back to stdout
        print(line.strip())
        return

    _enforce_size_limit()


def _enforce_size_limit():
    """Truncate the log file if it exceeds MAX_SIZE_MB."""
    try:
        size_limit = int(MAX_SIZE_MB * 1024 * 1024)
        if os.path.getsize(LOG_FILE) <= size_limit:
            return
        with open(LOG_FILE, "rb") as f:
            f.seek(-size_limit, os.SEEK_END)
            data = f.read()
        with open(LOG_FILE, "wb") as f:
            f.write(data)
    except Exception:
        pass
