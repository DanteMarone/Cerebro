TOOL_METADATA = {
    "name": "credential-manager",
    "description": "Store, retrieve, and delete credentials using the system keyring.",
    "args": ["action", "service", "username", "value"],
    "dependencies": ["keyring"]
}


def run_tool(args):
    """Manage credentials with the keyring library.

    Args:
        args (dict): action ('store', 'get', 'delete'), service name,
            username, and optional value when storing.
    """
    try:
        import keyring
    except Exception:
        return "[credential-manager Error] keyring not installed."

    action = args.get("action")
    service = args.get("service", "cerebro")
    username = args.get("username", "default")

    if action == "store":
        value = args.get("value")
        if value is None:
            return "[credential-manager Error] No value provided."
        try:
            keyring.set_password(service, username, value)
            return "Credential stored"
        except Exception as e:
            return f"[credential-manager Error] {e}"
    elif action == "get":
        try:
            value = keyring.get_password(service, username)
            return value if value is not None else "[credential-manager Error] Credential not found."
        except Exception as e:
            return f"[credential-manager Error] {e}"
    elif action == "delete":
        try:
            keyring.delete_password(service, username)
            return "Credential deleted"
        except keyring.errors.PasswordDeleteError:
            return "[credential-manager Error] Credential not found."
        except Exception as e:
            return f"[credential-manager Error] {e}"
    else:
        return "[credential-manager Error] Invalid action."
