"""Simple text-to-speech helper."""


def speak_text(text: str) -> str:
    """Speak the provided text using pyttsx3 if available."""
    try:
        import pyttsx3
    except Exception:
        return "[TTS Error] pyttsx3 not installed."
    try:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        return "Speaking text"
    except Exception as exc:
        return f"[TTS Error] {exc}"
