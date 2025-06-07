"""Simple speech recognition helpers."""

from typing import Optional

try:
    import speech_recognition as sr
except Exception:  # pragma: no cover - library missing
    sr = None


def recognize_speech(timeout: int = 5) -> str:
    """Return recognized text from the default microphone.

    Parameters
    ----------
    timeout:
        Maximum number of seconds to wait for speech.
    """
    if sr is None:
        return "[Speech Recognition Error] speech_recognition not installed."

    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            audio = recognizer.listen(source, timeout=timeout)
        return recognizer.recognize_google(audio)
    except Exception as exc:  # pragma: no cover - depends on environment
        return f"[Speech Recognition Error] {exc}"
