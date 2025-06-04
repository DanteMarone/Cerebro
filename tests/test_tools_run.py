import tools
from tool_plugins import echo_plugin


def test_run_tool_echo():
    plugins = tools.load_tools()
    result_direct = echo_plugin.run_tool({"msg": "hello"})
    result_via_tools = tools.run_tool(plugins, "echo-plugin", {"msg": "hello"})
    assert result_direct == result_via_tools
