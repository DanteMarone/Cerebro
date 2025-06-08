import os
from PyQt5.QtWidgets import QApplication
import dialogs

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_tool_dialog_validation():
    app = QApplication.instance() or QApplication([])
    dlg = dialogs.ToolDialog()
    dlg.name_edit.clear()
    dlg.description_edit.clear()
    if hasattr(dlg.script_edit, "set_text"):
        dlg.script_edit.set_text("")
    elif hasattr(dlg.script_edit, "setPlainText"):
        dlg.script_edit.setPlainText("")
    dlg.validate_fields()
    assert not dlg.ok_button.isEnabled()

    dlg.name_edit.setText("demo")
    dlg.description_edit.setText("desc")
    script = "def run_tool(args):\n    return 'ok'"
    if hasattr(dlg.script_edit, "set_text"):
        dlg.script_edit.set_text(script)
    elif hasattr(dlg.script_edit, "setPlainText"):
        dlg.script_edit.setPlainText(script)
    else:
        dlg.script_edit.setText(script)
    dlg.validate_fields()
    assert dlg.ok_button.isEnabled()
    app.quit()
