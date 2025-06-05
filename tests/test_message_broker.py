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
        self.tools = [{'name': 'echo-plugin', 'description': 'Echo', 'args': []}]


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

