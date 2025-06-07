import os
import importlib.util
import tools


def test_install_and_toggle_plugin(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugins_file = tmp_path / "plugins.json"
    monkeypatch.setattr(tools, "PLUGIN_DIR", str(plugin_dir))
    monkeypatch.setattr(tools, "PLUGINS_FILE", str(plugins_file))

    plugin_src = tmp_path / "demo.py"
    plugin_src.write_text("TOOL_METADATA={'name':'demo','description':'d'}\n\n" "def run_tool(args):\n    return 'ok'")

    err = tools.install_plugin(str(plugin_src))
    assert err is None
    assert (plugin_dir / "demo.py").exists()

    tools_list = tools.discover_plugin_tools()
    assert any(t["name"] == "demo" for t in tools_list)

    tools.set_plugin_enabled("demo", False)
    tools_list = tools.discover_plugin_tools()
    assert all(t["name"] != "demo" for t in tools_list)

