from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QComboBox
import os


class DocumentationTab(QWidget):
    """Display application documentation from docs/user_guide.md."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.selector = QComboBox()
        self.doc_map = {
            "User Guide": "user_guide.md",
            "Getting Started": "getting_started.md",
            "Application Tabs": "app_tabs.md",
            "Configuration": "configuration.md",
            "Plugins": "plugins.md",
        }
        self.selector.addItems(self.doc_map.keys())
        self.selector.currentTextChanged.connect(self.load_documentation)
        layout.addWidget(self.selector)

        self.doc_view = QTextEdit()
        self.doc_view.setReadOnly(True)
        layout.addWidget(self.doc_view)

        self.load_documentation(self.selector.currentText())

    def load_documentation(self, key):
        """Load the markdown documentation into the view."""
        filename = self.doc_map.get(key, "user_guide.md")
        doc_path = os.path.join(os.path.dirname(__file__), "docs", filename)
        try:
            with open(doc_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.doc_view.setMarkdown(content)
        except Exception as exc:
            self.doc_view.setPlainText(f"Failed to load documentation: {exc}")


