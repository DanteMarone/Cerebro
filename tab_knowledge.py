# tab_knowledge.py
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QFileDialog, QMessageBox
)
import os
from services.document_processor import DocumentProcessor
from services.vector_store_service import vector_store_service

class KnowledgeTab(QWidget):
    """Knowledge Base UI for uploading, listing, and deleting documents."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.doc_processor = DocumentProcessor()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(layout)

        header = QLabel("Knowledge Base")
        header.setObjectName("chatTitle")
        layout.addWidget(header)

        controls = QHBoxLayout()
        layout.addLayout(controls)

        self.upload_btn = QPushButton("Add Document…")
        self.upload_btn.clicked.connect(self.on_add_document)
        controls.addWidget(self.upload_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_list)
        controls.addWidget(self.refresh_btn)

        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self.on_delete_selected)
        controls.addWidget(self.delete_btn)

        controls.addStretch(1)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        hint = QLabel("Supported: .pdf, .txt")
        hint.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(hint)

        self.refresh_list()

    def on_add_document(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select document", os.getcwd(), "Documents (*.pdf *.txt)")
        if not file_path:
            return
        ok, msg = self.doc_processor.process_document(file_path, {"source": "user_upload"})
        if ok:
            self.parent_app.show_notification("Document indexed")
            self.refresh_list()
        else:
            QMessageBox.warning(self, "Upload failed", msg)

    def refresh_list(self):
        self.list_widget.clear()
        docs = vector_store_service.list_documents()
        for d in docs:
            label = f"{d.get('file_name','(unnamed)')}  —  chunks: {d.get('chunk_count',0)}  —  id: {d.get('id')}"
            self.list_widget.addItem(label)

    def on_delete_selected(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        # Expect id at the end after 'id: '
        text = item.text()
        doc_id = text.split('id:')[-1].strip()
        confirm = QMessageBox.question(self, "Confirm delete", f"Delete document '{doc_id}' and all its chunks?")
        if confirm != QMessageBox.Yes:
            return
        ok, msg = self.doc_processor.delete_document(doc_id)
        if ok:
            self.parent_app.show_notification("Document deleted")
            self.refresh_list()
        else:
            QMessageBox.warning(self, "Delete failed", msg) 