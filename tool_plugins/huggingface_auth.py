TOOL_METADATA = {
    "name": "huggingface-auth",
    "description": "Login or logout of Hugging Face to access private models.",
    "args": ["action", "token"],
}

try:
    from huggingface_hub import login, logout
except Exception:  # pragma: no cover - optional dependency
    def login(*_args, **_kwargs):
        raise ImportError("huggingface_hub not installed.")

    def logout(*_args, **_kwargs):
        raise ImportError("huggingface_hub not installed.")


def run_tool(args):
    """Authenticate with Hugging Face using huggingface_hub."""

    action = args.get("action", "login")

    if action == "login":
        token = args.get("token")
        if not token:
            return "[huggingface-auth Error] 'token' is required for login."
        try:
            login(token=token, add_to_git_credential=True)
            return "Logged in to Hugging Face."
        except ImportError as exc:
            return f"[huggingface-auth Error] {exc}"
        except Exception as exc:
            return f"[huggingface-auth Error] {exc}"

    if action == "logout":
        try:
            logout()
            return "Logged out of Hugging Face."
        except ImportError as exc:
            return f"[huggingface-auth Error] {exc}"
        except Exception as exc:
            return f"[huggingface-auth Error] {exc}"

    return "[huggingface-auth Error] Invalid action."
