import sys
import types
import tool_plugins.text_to_speech as tts


class FakeEngine:
    def __init__(self):
        self.texts = []

    def say(self, text):
        self.texts.append(text)

    def runAndWait(self):
        pass


def test_run_tool(monkeypatch):
    engine = FakeEngine()
    mod = types.ModuleType('pyttsx3')
    mod.init = lambda: engine
    monkeypatch.setitem(sys.modules, 'pyttsx3', mod)
    result = tts.run_tool({'text': 'hi'})
    assert 'Speaking' in result
    assert engine.texts == ['hi']
