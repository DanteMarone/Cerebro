import os
import logging

logger = logging.getLogger("cerebro")

LOG_FILE = os.path.join(os.path.dirname(__file__), "cerebro.log")


def setup_logging(debug_enabled: bool = False) -> None:
    """Configure application logging."""
    level = logging.DEBUG if debug_enabled else logging.INFO
    logging.basicConfig(
        filename=LOG_FILE,
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.setLevel(level)


def get_log_file_path() -> str:
    """Return the absolute path to the log file."""
    return os.path.abspath(LOG_FILE)


def format_user_friendly(error_msg: str, api_url: str | None = None) -> str:
    """Translate a technical error into a user-friendly message."""
    if not error_msg:
        return "An unknown error occurred."

    msg_lower = error_msg.lower()

    if "econnrefused" in msg_lower or "connection refused" in msg_lower:
        message = "Agent could not connect to the AI service."
        if api_url:
            message += f" Ensure the service at {api_url} is running."
        return message

    if "timeout" in msg_lower:
        return "The request to the AI service timed out."

    return error_msg
