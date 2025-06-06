import sys
import types
import tts

class FakeEngine:
    def __init__(self):
        self.texts = []
    def say(self, text):
        self.texts.append(text)
    def runAndWait(self):
        pass

def test_speak_text(monkeypatch):
    engine = FakeEngine()
    mod = types.ModuleType('pyttsx3')
    mod.init = lambda: engine
    monkeypatch.setitem(sys.modules, 'pyttsx3', mod)
    result = tts.speak_text('hi')
    assert 'Speaking' in result
    assert engine.texts == ['hi']
