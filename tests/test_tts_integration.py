import message_broker
import tts

class DummyApp:
    def __init__(self):
        self.debug_enabled = False
        self.agents_data = {
            'agent1': {
                'role': 'Assistant',
                'enabled': True,
                'tool_use': False,
                'tools_enabled': [],
                'tts_enabled': True,
                'tts_voice': '',
                'color': '#000'
            }
        }
        self.chat_tab = type(
            'Tab',
            (),
            {
                'append_message_html': lambda self, html: None,
                'append_message_bubble': lambda self, *a, **k: None,
            },
        )()
        self.current_responses = {'agent1': 'hello'}
        self.tools = []
        self.tasks = []
        self.chat_history = []


def test_tts_called(monkeypatch):
    app = DummyApp()
    broker = message_broker.MessageBroker(app)
    called = {}
    monkeypatch.setattr(tts, 'speak_text', lambda text, voice=None: called.setdefault('text', text))

    class DummyThread:
        def quit(self):
            pass
        def wait(self):
            pass
        def deleteLater(self):
            pass

    class DummyWorker:
        def deleteLater(self):
            pass

    thread = DummyThread()
    worker = DummyWorker()
    broker.active_worker_threads = [(worker, thread)]

    broker.worker_finished_sequential(worker, thread, 'agent1')

    assert called['text'] == 'hello'
