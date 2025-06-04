from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit
import os


class DocumentationTab(QWidget):
    """Display application documentation from docs/user_guide.md."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.doc_view = QTextEdit()
        self.doc_view.setReadOnly(True)
        layout.addWidget(self.doc_view)

        self.load_documentation()

    def load_documentation(self):
        """Load the markdown documentation into the view."""
        doc_path = os.path.join(os.path.dirname(__file__), "docs", "user_guide.md")
        try:
            with open(doc_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.doc_view.setMarkdown(content)
        except Exception as exc:
            self.doc_view.setPlainText(f"Failed to load documentation: {exc}")

