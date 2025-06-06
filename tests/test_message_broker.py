import message_broker

class DummyApp:
    def __init__(self):
        self.debug_enabled = False
        self.agents_data = {
            'agent1': {
                'system_prompt': 'hi',
                'role': 'Coordinator',
                'tool_use': True,
                'managed_agents': [],
                'tools_enabled': ['echo-plugin']
            }
        }
        self.tools = [{'name': 'echo-plugin', 'description': 'Echo', 'args': [], 'silent': False}]


def test_build_agent_chat_history(monkeypatch):
    app = DummyApp()
    history = [
        {'role': 'user', 'content': 'Q'},
        {'role': 'assistant', 'content': 'A', 'agent': 'agent1'}
    ]
    monkeypatch.setattr(message_broker, 'load_history', lambda debug=False: history)
    monkeypatch.setattr(message_broker, 'summarize_history', lambda h: h)
    monkeypatch.setattr(message_broker, 'generate_tool_instructions_message', lambda app, name: 'tools')
    broker = message_broker.MessageBroker(app)
    chat = broker.build_agent_chat_history('agent1')
    assert chat[0]['role'] == 'system'
    assert 'tools' in chat[0]['content']
    # user and assistant messages preserved
    assert chat[1]['role'] == 'user'
    assert chat[2]['role'] == 'assistant'


def test_handle_worker_finished_runs_tool_for_assistant(monkeypatch):
    app = DummyApp()
    app.agents_data['agent1']['role'] = 'Assistant'
    app.agents_data['agent1']['tool_use'] = True
    app.chat_tab = type('Tab', (), {'append_message_html': lambda self, html: None})()
    app.current_responses = {
        'agent1': (
            '{"role": "assistant", "content": "hi", '
            '"tool_request": {"name": "echo-plugin", "args": {"msg": "hi"}}}'
        )
    }

    broker = message_broker.MessageBroker(app)

    called = {}

    def fake_run_tool(tools, name, args, debug):
        called['name'] = name
        called['args'] = args
        return 'ok'

    monkeypatch.setattr(message_broker, 'run_tool', fake_run_tool)
    monkeypatch.setattr(message_broker, 'append_message', lambda *a, **k: None)

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

    assert called['name'] == 'echo-plugin'
    assert called['args'] == {'msg': 'hi'}


def test_delivers_tool_result(monkeypatch):
    app = DummyApp()
    app.agents_data['agent1']['role'] = 'Assistant'
    app.agents_data['agent1']['tool_use'] = True
    app.chat_tab = type('Tab', (), {'append_message_html': lambda self, html: None})()
    app.current_responses = {
        'agent1': (
            '{"role": "assistant", "content": "hi", '
            '"tool_request": {"name": "echo-plugin", "args": {"msg": "hi"}}}'
        )
    }

    broker = message_broker.MessageBroker(app)

    monkeypatch.setattr(message_broker, 'append_message', lambda *a, **k: None)
    monkeypatch.setattr(message_broker, 'run_tool', lambda *a, **k: 'ok')

    delivered = {}

    def fake_deliver(agent, name, result):
        delivered['agent'] = agent
        delivered['name'] = name
        delivered['result'] = result

    monkeypatch.setattr(broker, 'deliver_tool_result', fake_deliver)

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

    assert delivered['agent'] == 'agent1'
    assert delivered['name'] == 'echo-plugin'
    assert delivered['result'] == 'ok'


def test_deliver_tool_result_skips_silent(monkeypatch):
    app = DummyApp()
    app.tools.append({'name': 'text-to-speech', 'description': '', 'args': [], 'silent': True})
    broker = message_broker.MessageBroker(app)

    monkeypatch.setattr(message_broker, 'append_message', lambda *a, **k: None)

    called = {}

    def fake_route(sender, recipient, message, role="user", add_next=True):
        called['message'] = message

    monkeypatch.setattr(broker, '_route_message', fake_route)

    broker.deliver_tool_result('agent1', 'text-to-speech', 'ok')

    assert called == {}

