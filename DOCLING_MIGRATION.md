# Docling-only ingestion migration

Current behavior: **Docling is required and enabled for every new PDF/DOCX upload. There is no legacy extraction fallback or engine-selection switch.** This supersedes the earlier optional/hybrid implementation described in the historical engineering report.

## Changes

- `services/api/document_ingestion.py` now obtains document text, hierarchy, page provenance, structured tables, figures and image crops entirely from Docling. No standalone PyMuPDF or hand-written ZIP/XML extraction is used.
- `services/api/pdf_processor.py` contains compatibility entry points only. All three old function names delegate to Docling; the previous extraction implementations were removed.
- Docling and its tested dependency profile are included by the main backend requirements. PyMuPDF is retained only in `requirements-test.txt` for fixtures and output verification. Docling's own DOCX backend still uses its declared python-docx dependency internally.
- The application environment `.venv` has Docling installed. Local layout/table model weights have been provisioned under `storage/docling-models/`.
- The launcher verifies the required Docling dependency and runs `docling_setup.py` before starting services. First setup downloads the selected local models; subsequent starts check a versioned readiness manifest and reuse them offline. No `SOP_EXTRACTION_ENGINE=docling` flag is needed. An obsolete flag requesting a legacy engine is ignored with a warning.
- Missing dependencies/models return actionable service errors. Failed or partial conversions are rejected rather than processed with another parser. Partial asset writes are cleaned up.
- The existing `(pages, artifacts, stats)` contract, original uploads, SQLite schema, LangGraph agents, FAISS FlatIP indexes, translation/scoring gateway and ReportLab output remain in place. Health and processing traces identify `extraction_engine: docling`.

## Table and asset fidelity

The selected profile uses Docling's supported V2 layout model and accurate TableFormer with source-cell matching. The initially evaluated layout profile misclassified some synthetic tables and merged a column; the selected configuration passed the existing three-column, multiple-table and multi-page continuation regressions.

Continuation tables retain matching headers once, all source rows, page ranges, source references and per-page parts/crops. Original table parts remain available to prevent generated PDFs from rendering both the source parts and the combined table twice. DOCX tables have structured-cell SVG previews because they have no physical PDF page crop. These previews contain only Docling-extracted values; they are not presented as additional source evidence.

Traversal includes text inside figures and all document content layers, avoiding the default omission of text nested within picture elements. Original list markers are retained. PDF page numbers remain physical source pages; DOCX references remain logical document pages rather than claimed Word pagination.

## Execution and failure isolation

Docling conversion runs in one reusable spawned worker process, invoked from the existing ingestion worker threads. The converter/model cache is reused there, and only portable document data crosses back to the API. This avoids mixing native PDF/model execution with the web server's thread context and contains native failures. A stopped worker returns a service error and can be recreated for a later request; no alternate extractor is invoked.

Initial tests exposed an OpenMP shared-memory failure under the tool sandbox. The complete final regression run used normal shared-memory access, with local models and Hugging Face offline mode. No live Azure calls or customer documents were used.

## Verification

- **95 tests passed, with no skips**, in the final isolated full regression run (65.380 seconds).
- Real Docling PDF and DOCX conversions were exercised, including uploads through FastAPI/LangGraph, source/page references, nested headings, structured tables, three-page continuation, images, asset rendering and previews.
- Existing optimization grounding, numeric/tolerance checks, multilingual file isolation, similarity, RAG, harmonization, simplification/refinement, version/file isolation, persistence and download checks passed.
- Conversion failure, missing dependency, incomplete result, empty/scanned input and partial-asset cleanup checks passed. Tests also confirm an obsolete legacy-engine setting cannot disable Docling.
- All **46 Python files** passed syntax parsing.
- The updated frontend production build passed.
- The launcher's readiness check was executed successfully with offline mode after provisioning, confirming subsequent setup does not require another model download.

## Running the application

From this project folder, start or restart normally:

```bash
python3 run.py
```

No database migration or manual engine-enabling step is required. Existing uploads and previously generated versions are not reprocessed or overwritten. Re-upload a document to obtain a new extraction through the current engine.

OCR remains a separate, explicit configuration: `DOCLING_OCR=1` requires existing local detection, classification, recognition and key files documented in the README. OCR accuracy was not validated in this migration; scanned input without usable text and configured OCR is rejected clearly. Passing synthetic extraction tests does not establish perfect accuracy on every document, and the source-grounding/author-review gates remain active.
