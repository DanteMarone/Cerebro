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


def test_dialog_ui_and_data_fields():
    app = QApplication.instance() or QApplication([])
    parent = DummyParent()
    dlg = dialogs.TaskDialog(parent, {"agent1": {}}, priority=2)
    
    # Test for collapsible sections
    toolbox = dlg.findChild(dialogs.QToolBox)
    assert toolbox is not None
    assert toolbox.itemText(0) == "Details"
    
    # Set and test template fields
    dlg.save_template_cb.setChecked(True)
    dlg.template_name_edit.setText("temp")
    
    # Get data
    data = dlg.get_data()
    
    # Assert all data conditions
    assert data["priority"] == 2
    assert data["save_as_template"] is True
    assert data["template_name"] == "temp"
    app.quit()
