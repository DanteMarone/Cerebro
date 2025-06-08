import os
from PyQt5.QtWidgets import QApplication, QWidget
import dialogs

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DummyParent(QWidget):
    def __init__(self):
        super().__init__()
        self.agents_data = {"agent1": {}}


def test_ok_button_disabled_until_fields_complete():
    app = QApplication.instance() or QApplication([])
    parent = DummyParent()
    dlg = dialogs.TaskDialog(parent, {"agent1": {}})
    dlg.prompt_edit.clear()
    dlg.validate_fields()
    assert not dlg.ok_button.isEnabled()
    dlg.prompt_edit.setPlainText("Do something")
    dlg.validate_fields()
    assert dlg.ok_button.isEnabled()
    app.quit()


def test_focus_on_first_missing_field():
    app = QApplication.instance() or QApplication([])
    parent = DummyParent()
    dlg = dialogs.TaskDialog(parent, {"agent1": {}})
    dlg.prompt_edit.clear()
    dlg.accept()
    assert dlg.prompt_edit.styleSheet() != ""
    app.quit()


def test_template_fields():
    app = QApplication.instance() or QApplication([])
    parent = DummyParent()
    dlg = dialogs.TaskDialog(parent, {"agent1": {}})
    dlg.save_template_cb.setChecked(True)
    dlg.template_name_edit.setText("temp")
    data = dlg.get_data()
    assert data["save_as_template"] is True
    assert data["template_name"] == "temp"
    app.quit()
