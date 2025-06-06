TOOL_METADATA = {
    "name": "text-to-speech",
    "description": "Speak the provided text using the OS text-to-speech engine.",
    "args": ["text"],
}


def run_tool(args):
    """Speak the text out loud using pyttsx3."""
    text = args.get("text", "Hello from Cerebro")
    try:
        import pyttsx3
    except Exception:
        return "[text-to-speech Error] pyttsx3 not installed."
    try:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        return "Speaking text"
    except Exception as exc:
        return f"[text-to-speech Error] {exc}"
