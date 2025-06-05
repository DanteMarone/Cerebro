from tool_plugins import ar_overlay


def test_run_overlay_returns_string():
    result = ar_overlay.run_tool({"message": "test"})
    assert isinstance(result, str)
