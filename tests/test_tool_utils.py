import types
import tool_utils

class DummyApp:
    def __init__(self):
        self.agents_data = {
            'agent1': {
                'tool_use': True,
                'tools_enabled': ['echo-plugin']
            },
            'agent2': {
                'tool_use': False,
                'tools_enabled': []
            }
        }
        self.tools = [
            {'name': 'echo-plugin', 'description': 'Echo', 'args': ['msg']}
        ]


def test_generate_tool_instructions_enabled():
    app = DummyApp()
    instructions = tool_utils.generate_tool_instructions_message(app, 'agent1')
    assert 'echo-plugin' in instructions
    assert 'Available tools' in instructions


def test_generate_tool_instructions_disabled():
    app = DummyApp()
    instructions = tool_utils.generate_tool_instructions_message(app, 'agent2')
    assert instructions == ''


def test_format_tool_call_html():
    html = tool_utils.format_tool_call_html('echo-plugin', {'msg': 'hi'})
    assert 'echo-plugin' in html
    assert 'msg' in html
    assert 'toolCall' in html


def test_format_tool_result_html():
    html = tool_utils.format_tool_result_html('ok')
    assert 'ok' in html
    assert 'toolResult' in html

