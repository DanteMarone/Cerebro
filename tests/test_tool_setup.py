import importlib.util
import tools
import tab_tools
from PyQt5.QtWidgets import QApplication


def test_missing_dependencies(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    monkeypatch.setattr(tools, "PLUGIN_DIR", str(plugin_dir))
    monkeypatch.setattr(tools, "PLUGINS_FILE", str(tmp_path / "plugins.json"))
    plugin_file = plugin_dir / "demo.py"
    plugin_file.write_text(
        "TOOL_METADATA={'name':'demo','description':'d',"
        "'dependencies':['pkg']}\n"
        "def run_tool(args):\n    return 'ok'"
    )
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "pkg" else importlib.util.find_spec(name),
    )
    app = QApplication.instance() or QApplication([])
    app_obj = type(
        "Dummy",
        (),
        {
            "tools": tools.load_tools(),
            "debug_enabled": False,
            "refresh_tools_list": lambda self: None,
            "open_settings_dialog": lambda self: None,
        },
    )()
    tab = tab_tools.ToolsTab(app_obj)
    tab.tools = app_obj.tools
    tab.refresh_tools_list()
    demo_tool = next(t for t in tab.tools if t["name"] == "demo")
    deps = tab.missing_dependencies(demo_tool)
    assert deps == ["pkg"]
    app.quit()
