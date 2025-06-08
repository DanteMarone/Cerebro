import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
import tab_tools


class DummyApp:
    def __init__(self):
        self.debug_enabled = False
        self.tools = [
            {
                "name": "demo",
                "description": "Demo",
                "plugin_module": object(),
                "script": "",
                "script_path": ""
            }
        ]

    def refresh_tools_list(self):
        pass


def test_status_column(monkeypatch):
    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(
        tab_tools,
        "get_available_plugins",
        lambda debug=False: [
            {"name": "demo", "description": "Demo", "enabled": True, "path": ""},
            {"name": "other", "description": "Other", "enabled": False, "path": ""},
        ],
    )

    tab = tab_tools.ToolsTab(DummyApp())
    tab.refresh_tools_list()

    assert tab.tools_list.topLevelItemCount() == 2
    enabled_item = tab.tools_list.topLevelItem(0)
    disabled_item = tab.tools_list.topLevelItem(1)

    assert enabled_item.text(2) == "Enabled"
    assert disabled_item.text(2) == "Disabled"
    assert not (disabled_item.flags() & tab_tools.Qt.ItemIsEnabled)
    app.quit()
