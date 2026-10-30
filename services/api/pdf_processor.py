"""Backward-compatible extraction names; all parsing is performed by Docling.

The old PyMuPDF and hand-written DOCX extraction implementations were removed.
These entry points remain for existing internal callers and tests.
"""
from document_ingestion import extract_document
from minio_storage import minio_storage


def extract_sop_pdf(file_bytes, conversation_id="default", filename="document.pdf"):
    return extract_document(file_bytes, conversation_id, filename, storage=minio_storage)


def extract_sop_docx(file_bytes, conversation_id="default", filename="document.docx"):
    return extract_document(file_bytes, conversation_id, filename, storage=minio_storage)


def extract_sop_document(file_bytes, conversation_id, filename):
    return extract_document(file_bytes, conversation_id, filename, storage=minio_storage)
