import sys
import os
import json
import pytest
from pydantic import ValidationError

# Add root to path
sys.path.append(os.getcwd())

import tools
from core.orchestrator import Orchestrator

def test_schema_generation():
    # Load tools
    loaded_tools = tools.load_tools()
    weather_tool = next((t for t in loaded_tools if t["name"] == "weather"), None)
    assert weather_tool is not None, "Weather tool not found"
    assert weather_tool.get("args_model") is not None, "ARGS_MODEL not loaded for weather tool"

    # Setup agent data
    agents_data = {
        "WeatherAgent": {
            "tool_use": True,
            "tools_enabled": ["weather"]
        }
    }

    orch = Orchestrator(agents_data, loaded_tools)
    schema = orch.generate_response_schema("WeatherAgent")

    assert schema is not None
    # print(json.dumps(schema, indent=2))

    # Check schema structure
    # Pydantic v2 uses $defs
    defs = schema.get("$defs", {})
    # Check if we have definitions for our types
    assert len(defs) > 0

    props = schema["properties"]
    assert "content" in props
    assert "tool_request" in props

def test_tool_execution():
    loaded_tools = tools.load_tools()

    # Test valid execution
    args = {"location": "Paris", "unit": "celsius"}
    result = tools.run_tool(loaded_tools, "weather", args)
    assert "Weather in Paris is 20 degrees celsius" in result

    # Test invalid execution (validation error)
    bad_args = {"location": "Paris", "unit": "kelvin"} # Invalid unit
    result = tools.run_tool(loaded_tools, "weather", bad_args)
    assert "[Tool Error]" in result
    assert "Validation failed" in result

if __name__ == "__main__":
    test_schema_generation()
    test_tool_execution()
    print("Tests passed!")
