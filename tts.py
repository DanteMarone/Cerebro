"""Simple text-to-speech helper functions."""

from typing import List, Optional


def get_available_voice_names() -> List[str]:
    """Return a list of available system voice names."""
    try:
        import pyttsx3
    except Exception:
        return []

    try:
        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        return [voice.name for voice in voices]
    except Exception:
        return []


def speak_text(text: str, voice: Optional[str] = None) -> str:
    """Speak the provided ``text`` using pyttsx3 if available.

    Parameters
    ----------
    text:
        The text to speak.
    voice:
        Optional voice name returned by :func:`get_available_voice_names`.
    """
    try:
        import pyttsx3
    except Exception:
        return "[TTS Error] pyttsx3 not installed."

    try:
        engine = pyttsx3.init()
        if voice:
            for v in engine.getProperty("voices"):
                if voice.lower() in (v.name.lower(), v.id.lower()):
                    engine.setProperty("voice", v.id)
                    break
        engine.say(text)
        engine.runAndWait()
        return "Speaking text"
    except Exception as exc:
        return f"[TTS Error] {exc}"
