TOOL_METADATA = {
    "name": "huggingface-auth",
    "description": "Login or logout of Hugging Face to access private models.",
    "args": ["action", "token"],
}


def run_tool(args):
    """Authenticate with Hugging Face using huggingface_hub."""
    try:
        from huggingface_hub import login, logout
    except Exception:
        return "[huggingface-auth Error] huggingface_hub not installed."

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
