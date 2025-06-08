TOOL_METADATA = {
    "name": "huggingface-auth",
    "description": "Login or logout of Hugging Face to access private models.",
    "args": ["action", "token"],
    "dependencies": ["huggingface_hub"],
    "needs_config": True,
}

try:
    from huggingface_hub import login as hf_login, logout as hf_logout
except Exception:  # pragma: no cover - optional dependency
    hf_login = None
    hf_logout = None


def login(token=None, add_to_git_credential=True):
    if hf_login is None:
        raise RuntimeError("huggingface_hub not installed.")
    return hf_login(token=token, add_to_git_credential=add_to_git_credential)


def logout():
    if hf_logout is None:
        raise RuntimeError("huggingface_hub not installed.")
    return hf_logout()


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
        except Exception as exc:
            return f"[huggingface-auth Error] {exc}"

    if action == "logout":
        try:
            logout()
            return "Logged out of Hugging Face."
        except Exception as exc:
            return f"[huggingface-auth Error] {exc}"

    return "[huggingface-auth Error] Invalid action."
