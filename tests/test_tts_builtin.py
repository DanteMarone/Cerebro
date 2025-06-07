import sys
import types
import tts

class FakeVoice:
    def __init__(self, vid, name):
        self.id = vid
        self.name = name


class FakeEngine:
    def __init__(self):
        self.texts = []
        self.voice = None
        self._voices = [FakeVoice('a', 'VoiceA'), FakeVoice('b', 'VoiceB')]

    def say(self, text):
        self.texts.append(text)

    def runAndWait(self):
        pass

    def getProperty(self, name):
        if name == 'voices':
            return self._voices

    def setProperty(self, name, value):
        if name == 'voice':
            self.voice = value

def test_speak_text(monkeypatch):
    engine = FakeEngine()
    mod = types.ModuleType('pyttsx3')
    mod.init = lambda: engine
    monkeypatch.setitem(sys.modules, 'pyttsx3', mod)
    result = tts.speak_text('hi', voice='VoiceB')
    assert 'Speaking' in result
    assert engine.texts == ['hi']
    assert engine.voice == 'b'
