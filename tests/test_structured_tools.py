from worker import AIWorker
from tools import load_tools, SchemaGenerator, run_tool
import sys
import os
import json
from unittest.mock import MagicMock, patch

# Ensure root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_schema_generation():
    # Load tools (should include our new weather tool)
    tools = load_tools(debug_enabled=True)
    weather_tool = next((t for t in tools if t['name'] == 'weather'), None)
    assert weather_tool is not None, "Weather tool not found"

    # Generate schema
    schema = SchemaGenerator.generate([weather_tool])

    print(json.dumps(schema, indent=2))

    # Verify schema structure
    assert schema['type'] == 'object'
    assert 'tool_request' in schema['properties']
    tool_req = schema['properties']['tool_request']
    assert 'anyOf' in tool_req

    # Find the non-null option in anyOf
    options = tool_req['anyOf']
    tool_option = next((opt for opt in options if opt.get('type') != 'null'), None)
    assert tool_option is not None
    assert 'oneOf' in tool_option

    # Verify weather option
    weather_opt = next((opt for opt in tool_option['oneOf'] if opt['properties']['name']['const'] == 'weather'), None)
    assert weather_opt is not None
    assert 'args' in weather_opt['properties']
    args_schema = weather_opt['properties']['args']
    assert 'location' in args_schema['properties']


@patch('requests.post')
def test_ai_worker_format_param(mock_post):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_lines.return_value = [
        json.dumps({"message": {"content": "Test response"}}).encode('utf-8'),
        json.dumps({"done": True}).encode('utf-8')
    ]
    mock_post.return_value = mock_response

    # Setup worker
    agents_data = {"test_agent": {"model": "llama3.2", "role": "Assistant"}}
    schema = {"type": "object", "properties": {"foo": {"type": "string"}}}

    worker = AIWorker(
        model_name="llama3.2",
        chat_history=[],
        temperature=0.7,
        max_tokens=100,
        debug_enabled=True,
        agent_name="test_agent",
        agents_data=agents_data,
        json_format=schema
    )

    worker.run()

    # Verify requests.post called with format
    args, kwargs = mock_post.call_args
    payload = kwargs['json']
    assert 'format' in payload
    assert payload['format'] == schema


def test_run_tool_pydantic():
    tools = load_tools()

    # Run weather tool
    result = run_tool(tools, "weather", {"location": "London", "unit": "celsius"}, debug_enabled=True)
    assert "Weather in London" in result
    assert "22 degrees celsius" in result
