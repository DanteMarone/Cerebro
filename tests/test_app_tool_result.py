import types
import app

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

def test_worker_finished_sends_result_back(monkeypatch):
    dummy = types.SimpleNamespace()
    dummy.debug_enabled = False
    dummy.chat_history = []
    dummy.current_responses = {
        'agent1': (
            '{"role": "assistant", "content": "hi", '
            '"tool_request": {"name": "echo-plugin", "args": {"msg": "hi"}}}'
        )
    }
    dummy.agents_data = {
        'agent1': {
            'role': 'Assistant',
            'tool_use': True,
            'tools_enabled': ['echo-plugin'],
            'color': '#000'
        }
    }
    dummy.chat_tab = types.SimpleNamespace(append_message_html=lambda *a, **k: None)
    dummy.tools = [{'name': 'echo-plugin', 'description': 'Echo', 'args': []}]
    dummy.metrics = {}
    dummy.refresh_metrics_display = lambda: None
    dummy.show_notification = lambda *a, **k: None
    sent = {}
    def fake_send(agent, msg):
        sent['agent'] = agent
        sent['msg'] = msg
    dummy.send_message_to_agent = fake_send
    dummy.response_start_times = {}
    dummy.active_worker_threads = []
    thread = DummyThread()
    worker = DummyWorker()
    dummy.active_worker_threads.append((worker, thread))
    dummy.response_start_times[worker] = 0

    monkeypatch.setattr(app, 'run_tool', lambda *a, **k: 'ok')
    monkeypatch.setattr(app, 'append_message', lambda *a, **k: None)
    monkeypatch.setattr(app, 'record_tool_usage', lambda *a, **k: None)

    app.AIChatApp.worker_finished_sequential(dummy, worker, thread, 'agent1', None, None)

    assert sent['agent'] == 'agent1'
    assert 'Tool echo-plugin result' in sent['msg']
