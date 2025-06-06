import os
from PyQt5.QtWidgets import QApplication
import dialogs

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

def test_code_editor_roundtrip():
    app = QApplication.instance() or QApplication([])
    editor = dialogs.CodeEditor()
    test_text = "print('hello')"
    if hasattr(editor, "set_text"):
        editor.set_text(test_text)
    elif hasattr(editor, "setPlainText"):
        editor.setPlainText(test_text)
    else:
        editor.setText(test_text)

    if hasattr(editor, "text"):
        result = editor.text()
    else:
        result = editor.toPlainText()
    assert "hello" in result
    app.quit()
