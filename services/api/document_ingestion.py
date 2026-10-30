"""Docling-only PDF/DOCX ingestion, adapted to the existing pipeline contracts.

No alternative extraction engine is selected or used on conversion failure.
Model conversion is serialized inside the application's existing worker pool.
"""
import hashlib
import io
import logging
import os
from pathlib import Path
import re
import threading
import atexit
import concurrent.futures
import multiprocessing

from minio_storage import minio_storage
from source_grounding import inventory_from_pages

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_CONVERTERS = {}
_PROCESS_POOL = None
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_PATH = PROJECT_ROOT / "storage" / "docling-models"


class DocumentExtractionError(ValueError):
    """Observable conversion/storage failure with partial assets for cleanup."""

    def __init__(self, message, artifacts=None, status_code=400):
        super().__init__(message)
        self.artifacts_data = artifacts or []
        self.status_code = status_code


def get_models_path():
    return Path(os.getenv("DOCLING_ARTIFACTS_PATH") or DEFAULT_MODELS_PATH).expanduser().resolve()


def _converter(is_pdf):
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    except ImportError as exc:
        raise DocumentExtractionError(
            "Docling is required for SOP ingestion. Run python run.py to install the application dependencies. " + str(exc),
            status_code=503) from exc
    models = get_models_path()
    ocr = os.getenv("DOCLING_OCR", "0") == "1"
    ocr_files = {name: os.getenv(env, "") for name, env in [
        ("det_model_path", "DOCLING_OCR_DET_MODEL"), ("cls_model_path", "DOCLING_OCR_CLS_MODEL"),
        ("rec_model_path", "DOCLING_OCR_REC_MODEL"), ("rec_keys_path", "DOCLING_OCR_REC_KEYS")
    ]}
    key = (is_pdf, str(models), ocr, tuple(ocr_files.values()))
    if key not in _CONVERTERS:
        options = {}
        if is_pdf:
            if not models.is_dir():
                raise DocumentExtractionError(
                    "Docling PDF models are missing. Run python run.py to provision the local layout and table models.", status_code=503)
            pipeline = PdfPipelineOptions(
                artifacts_path=models, do_ocr=ocr, do_table_structure=True,
                generate_page_images=True, generate_picture_images=True,
                enable_remote_services=False,
                accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=4))
            # Bind recognized table structure to the source PDF text cells.
            pipeline.table_structure_options.do_cell_matching = True
            from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_V2
            pipeline.layout_options.model_spec = DOCLING_LAYOUT_V2
            if ocr:
                if not all(value and Path(value).is_file() for value in ocr_files.values()):
                    raise DocumentExtractionError(
                        "OCR requires explicit local detection/classification/recognition/key files; automatic OCR downloads disabled",
                        status_code=503)
                pipeline.ocr_options = RapidOcrOptions(**ocr_files)
            options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pipeline)
        _CONVERTERS[key] = DocumentConverter(
            allowed_formats=[InputFormat.PDF if is_pdf else InputFormat.DOCX], format_options=options)
    return _CONVERTERS[key]


def _convert_in_worker(file_bytes, filename):
    """Native PDF/layout libraries run only in a clean, dedicated process."""
    from docling.datamodel.base_models import DocumentStream, ConversionStatus
    result = _converter(filename.lower().endswith(".pdf")).convert(
        DocumentStream(name=filename, stream=io.BytesIO(file_bytes)), raises_on_error=False)
    if result.status != ConversionStatus.SUCCESS:
        raise DocumentExtractionError(
            f"Docling conversion did not complete ({result.status}): {result.errors}. The document was not indexed.",
            status_code=422 if result.status == ConversionStatus.PARTIAL_SUCCESS else 400)
    # Only portable document data crosses the process boundary, never PDF handles.
    return result.document.model_dump(mode="json")


def _shutdown_worker():
    global _PROCESS_POOL
    if _PROCESS_POOL is not None:
        _PROCESS_POOL.shutdown(wait=False, cancel_futures=True)
        _PROCESS_POOL = None


atexit.register(_shutdown_worker)


def _convert(file_bytes, filename):
    global _PROCESS_POOL
    from docling_core.types.doc import DoclingDocument
    from concurrent.futures.process import BrokenProcessPool
    if _PROCESS_POOL is None:
        _PROCESS_POOL = concurrent.futures.ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        payload = _PROCESS_POOL.submit(_convert_in_worker, file_bytes, filename).result()
        return DoclingDocument.model_validate(payload)
    except BrokenProcessPool as exc:
        _shutdown_worker()
        raise DocumentExtractionError(
            "Docling's conversion worker stopped unexpectedly. The document was not indexed; retry or review the source file.",
            status_code=503) from exc


def _table(item, document):
    frame = item.export_to_dataframe(doc=document).fillna("")
    rows = [[str(value) for value in row] for row in frame.values.tolist()]
    headers = [str(value) for value in frame.columns]
    # Headerless DOCX/PDF tables remain explicit: the first source row supplies
    # display headers as before, without inventing or dropping a source cell.
    if list(frame.columns) == list(range(len(frame.columns))) and rows:
        headers, rows = rows[0], rows[1:]
    return headers, rows


def _markdown(headers, rows):
    escape = lambda value: str(value).replace("|", "\\|").replace("\n", "<br>")
    return "\n".join(["| " + " | ".join(map(escape, headers)) + " |",
                      "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(map(escape, row)) + " |" for row in rows])


def _table_preview(headers, rows):
    """Browser preview of Docling's structured cells; no second parser/render engine."""
    from xml.sax.saxutils import escape
    import textwrap
    matrix = [headers] + rows
    widths = [min(350, max(140, max((len(str(row[col])) for row in matrix if col < len(row)), default=0) * 7 + 16))
              for col in range(len(headers))]
    body, y = [], 0
    for index, row in enumerate(matrix):
        lines = [textwrap.wrap(str(value), max(1, (widths[col] - 16) // 7)) or [""] for col, value in enumerate(row)]
        height = max((len(value) for value in lines), default=1) * 16 + 12
        x = 0
        for col, value in enumerate(lines):
            body.append(f'<rect x="{x}" y="{y}" width="{widths[col]}" height="{height}" fill="{"#e2e8f0" if index == 0 else "white"}" stroke="#94a3b8"/>')
            for line, text in enumerate(value):
                body.append(f'<text x="{x + 8}" y="{y + 19 + line * 16}" font-size="12" font-family="sans-serif">{escape(text)}</text>')
            x += widths[col]
        y += height
    width = sum(widths) or 140
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{y}" viewBox="0 0 {width} {y}">' + "".join(body) + "</svg>").encode(), width, y


def _merge_continuations(artifacts, pages):
    merged = []
    for artifact in artifacts:
        previous = merged[-1] if merged else {}
        same_header = previous.get("headers") == artifact.get("headers") and bool(artifact.get("headers"))
        same_section = previous.get("section_id") == artifact.get("section_id") and bool(artifact.get("section_id"))
        adjacent = previous.get("page_end", -2) + 1 == artifact.get("page_start")
        if previous.get("artifact_type") == artifact.get("artifact_type") == "table" and same_header and same_section and adjacent:
            def part(value):
                return {key: value.get(key) for key in ("source_ref", "headers", "rows", "page_start", "page_end", "object_name")}
            parts = previous["table_data"].setdefault("source_parts", [part(previous)])
            parts.append(part(artifact))
            previous["rows"] = previous["rows"] + artifact["rows"]
            previous["num_rows"] = len(previous["rows"])
            previous["page_end"] = artifact["page_end"]
            previous["table_markdown"] = _markdown(previous["headers"], previous["rows"])
            previous["table_data"].update(rows=previous["rows"], num_rows=previous["num_rows"])
            for page in pages:
                for element in page["elements"]:
                    if element.get("artifact_id") == artifact["id"]:
                        element["artifact_id"] = previous["id"]
        else:
            merged.append(artifact)
    return merged


def _normalize(document, file_bytes, conversation_id, filename, document_id, storage):
    is_pdf = filename.lower().endswith(".pdf")
    identity = document_id or hashlib.sha256(file_bytes).hexdigest()[:24]
    pages = {}
    if is_pdf:
        # Preserve actual blank/source pages so gaps are observable.
        for number in document.pages:
            pages[number] = {"page": number, "text": "", "elements": []}
    artifacts, warnings, saved = [], [], []
    section_id, section_title, section_ref = None, "Document Overview", None
    try:
        from docling_core.types.doc import ContentLayer
        items = list(document.iterate_items(included_content_layers=set(ContentLayer), traverse_pictures=True))
        items.extend(document.iterate_items(root=document.furniture, included_content_layers=set(ContentLayer), traverse_pictures=True))
        seen_refs = set()
        for order, (item, level) in enumerate(items):
            if item.self_ref in seen_refs:
                continue
            seen_refs.add(item.self_ref)
            label = str(getattr(item.label, "value", item.label))
            provenance = getattr(item, "prov", [])
            first_page = provenance[0].page_no if provenance else 1
            last_page = provenance[-1].page_no if provenance else first_page
            page = pages.setdefault(first_page, {"page": first_page, "text": "", "elements": []})
            text = getattr(item, "text", "") or ""
            marker = getattr(item, "marker", "") if label == "list_item" else ""
            if marker and not text.startswith(marker + " "):
                text = marker + " " + text
            if label in {"section_header", "title"}:
                section_title, section_ref = text, item.self_ref
                match = re.match(r"^(\d+(?:\.\d+)*)(?:\.)?\s+", text)
                section_id = match[1] if match else None
            element = {"source_ref": item.self_ref, "text": text, "label": label,
                       "document_id": document_id, "filename": filename, "extraction_engine": "docling",
                       "reading_order": order, "level": level, "section_ref": section_ref,
                       "section_id": section_id, "section_title": section_title,
                       "parent_ref": item.parent.cref if item.parent else None,
                       "page_start": first_page if provenance else None,
                       "page_end": last_page if provenance else None,
                       "page_provenance": "source_pdf_page" if provenance else "logical_docx_page"}
            if label in {"table", "picture"}:
                kind = "table" if label == "table" else "image"
                aid = ("tbl_" if kind == "table" else "img_") + hashlib.sha256(
                    f"{identity}|{item.self_ref}".encode()).hexdigest()[:16]
                caption = item.caption_text(doc=document) or f"{kind.title()} from {filename}"
                artifact = {"id": aid, "document_id": document_id, "conversation_id": conversation_id,
                            "artifact_type": kind, "caption": caption, "page": first_page,
                            "page_start": first_page, "page_end": last_page,
                            "section_id": section_id, "section_title": section_title,
                            "source_filename": filename, "source_ref": item.self_ref,
                            "extraction_engine": "docling", "extraction_method": "docling",
                            "provenance": {"source_document": filename, "source_ref": item.self_ref,
                                           "page_start": first_page if provenance else None,
                                           "page_end": last_page if provenance else None}}
                if kind == "table":
                    headers, rows = _table(item, document)
                    text = _markdown(headers, rows)
                    artifact.update(headers=headers, rows=rows, num_rows=len(rows), num_cols=len(headers),
                                    table_name=caption, table_markdown=text,
                                    table_data={"headers": headers, "rows": rows, "num_rows": len(rows),
                                                "num_cols": len(headers), "cells": item.data.model_dump(mode="json")})
                image = item.get_image(doc=document)
                if image is not None:
                    buffer = io.BytesIO(); image.save(buffer, format="PNG")
                    object_name = f"{'tables' if kind == 'table' else 'images'}/{conversation_id}/{identity}_{aid}.png"
                    if not storage.upload_file_bytes(object_name, buffer.getvalue(), "image/png"):
                        raise DocumentExtractionError(f"Could not store Docling asset {aid}", artifacts, status_code=500)
                    saved.append(object_name)
                    artifact.update(object_name=object_name, width=image.width, height=image.height)
                elif kind == "image":
                    warnings.append(f"Docling image {aid} could not be materialized; source review required")
                    artifact["object_name"] = ""
                else:
                    # DOCX has no physical-page crop. Preserve its existing gallery
                    # contract with a preview drawn only from Docling's cell data.
                    preview, width, height = _table_preview(headers, rows)
                    object_name = f"tables/{conversation_id}/{identity}_{aid}.svg"
                    if not storage.upload_file_bytes(object_name, preview, "image/svg+xml"):
                        raise DocumentExtractionError(f"Could not store Docling table preview {aid}", artifacts, 500)
                    saved.append(object_name)
                    artifact.update(object_name=object_name, width=width, height=height)
                artifacts.append(artifact)
                element["artifact_id"] = aid
            element["text"] = text
            if text:
                page["text"] += ("\n\n" if page["text"] else "") + text
            page["elements"].append(element)
        normalized_pages = [pages[number] for number in sorted(pages)]
        if not any(p["text"].strip() for p in normalized_pages):
            raise DocumentExtractionError("Docling found no usable SOP text; configure OCR for scanned documents.", artifacts, 422)
        empty_pages = [p["page"] for p in normalized_pages if not p["text"].strip()]
        if empty_pages:
            warnings.append(f"No extracted text on source pages {empty_pages}; source/OCR review required")
        status = "review_required" if warnings else "complete"
        artifacts = _merge_continuations(artifacts, normalized_pages)
        for page in normalized_pages:
            page.update(extraction_engine="docling", extraction_status=status,
                        page_provenance="source_pdf_page" if is_pdf else "logical_docx_page")
        stats = {"filename": filename, "page_count": len(normalized_pages),
                 "images_extracted": sum(a["artifact_type"] == "image" for a in artifacts),
                 "tables_extracted": sum(a["artifact_type"] == "table" for a in artifacts),
                 "extraction_engine": "docling", "extraction_status": status, "extraction_warnings": warnings,
                 "structural_elements": [e for p in normalized_pages for e in p["elements"]]}
        stats["source_inventory"] = inventory_from_pages(normalized_pages, identity, filename, artifacts, status)
        return normalized_pages, artifacts, stats
    except Exception:
        # No orphaned binary assets on rejection or a partial storage failure.
        for object_name in saved:
            storage.remove_file(object_name)
        raise


def extract_document(file_bytes, conversation_id, filename, document_id=None, storage=None):
    if not filename.lower().endswith((".pdf", ".docx")):
        raise DocumentExtractionError("Only PDF and DOCX documents are supported")
    if not file_bytes:
        raise DocumentExtractionError("Empty SOP document")
    if os.getenv("SOP_EXTRACTION_ENGINE", "docling") != "docling":
        logger.warning("SOP_EXTRACTION_ENGINE is obsolete: Docling is the only supported ingestion engine")
    try:
        with _LOCK:
            document = _convert(file_bytes, filename)
            output = _normalize(document, file_bytes, conversation_id, filename, document_id, storage or minio_storage)
        logger.info("Docling ingestion complete: document=%s filename=%s pages=%d tables=%d images=%d",
                    document_id, filename, output[2]["page_count"], output[2]["tables_extracted"], output[2]["images_extracted"])
        return output
    except DocumentExtractionError:
        raise
    except ImportError as exc:
        raise DocumentExtractionError(f"Required Docling dependency is unavailable: {exc}. Run python run.py.", status_code=503) from exc
    except Exception as exc:
        raise DocumentExtractionError(f"Docling could not process {filename}: {type(exc).__name__}: {exc}") from exc
