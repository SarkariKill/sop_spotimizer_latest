# Kenvue SOP Optimization & Multi-SOP Harmonization Assistant

A high-performance modular AI web application for Standard Operating Procedure (SOP) Docling PDF & DOCX ingestion, multimodal artifact extraction (images & tables), FAISS IndexFlatIP exact cosine similarity analysis & automatic SOP type discovery, multi-SOP harmonization, interactive simplification, and Kenvue standard compliance scoring.

---

## 🏗️ Local Architecture (Docker-Free)

```
Frontend (React + Vite) :3000
      │
      ▼
API Service (FastAPI) :8000 ────► Local Storage (./storage/ for images, tables, PDFs)
      │                     ────► FAISS FlatIP Vector Store (Hierarchical Embeddings)
      │                     ────► SQLite Database (./storage/data/chat.db)
      ▼
LLM Service (Azure OpenAI) :8001
```

- **Zero Docker / Zero MinIO Dependency**: Runs natively and smoothly on local development environments without containers.
- **Local File Storage**: All extracted images, tables, generated PDFs, and FAISS vector indexes reside cleanly inside `./storage/`.

---

## 🚀 Key Features

1. **Multi-SOP Upload & Semantic Similarity Discovery**:
   - Upload up to 10 SOPs concurrently in "All Uploaded SOPs".
   - Generates document-level embeddings and groups documents into semantic clusters with exact pairwise cosine similarity and domain discovery.

2. **Intelligent SOP Harmonization & Simplification**:
   - Harmonize multiple overlapping or duplicate SOPs into a single unified Kenvue standard document.
   - Interactive simplification workflow with selectable recommendations (clarity, concise terminology, consistency).
   - Preserves complete immutable version history (`Harmonized SOP v1`, `v2`, etc.).

3. **Multimodal Extraction & Image Placement**:
   - **Text**: Hierarchical chunking (parent and child chunks).
   - **Images & Tables**: Extracted *as-is* with page references and automatically placed in newly generated PDFs.

4. **Kenvue Standard Scoring & Evaluation**:
   - Real-time scoring for Readability, Template Match, Kenvue Alignment, and Completeness.
   - Live animated visual progress bar during ingestion and harmonization.

---

## 🛠️ Quick Start

### One-Click Local Launcher
Run the turnkey launcher from terminal:
```bash
python3 run.py
```

This automatically:
- Initializes `./storage/` folders and checks Python & Node environments.
- Starts LLM microservice (:8001), API backend (:8000), and Frontend (:3000).
- Opens [http://localhost:3000](http://localhost:3000) directly in your default browser.

### Stop All Services
```bash
python3 run.py --stop
```
*(or press `Ctrl+C` in the running terminal)*

---

## 🔑 Default Credentials
- **Username**: `admin`
- **Password**: `admin`
*(or register any new user account directly on the login screen)*

## Docling-only ingestion and source-grounded optimization

**Docling is the required, default, and sole PDF/DOCX ingestion engine.**
The old standalone PyMuPDF and ZIP/XML extractors have been removed. Existing
internal function names in `pdf_processor.py` are compatibility wrappers that
call Docling; they do not retain an alternative parsing implementation.

Start the application normally:

```bash
python3 run.py
```

The launcher installs the required backend dependencies, provisions local Docling
layout/table models on first setup, and reuses them offline on later starts.
No extraction-engine flag is needed. The obsolete `SOP_EXTRACTION_ENGINE` setting
cannot switch ingestion back to a legacy parser. Failed/incomplete conversions
produce explicit errors and are not indexed through another extractor.

Docling supplies text, reading order, section hierarchy, structured table cells,
image/diagram crops, and source references to the existing pipeline. PDF page
numbers are physical source pages; DOCX references are logical document pages
because Word pagination is not available from Docling's DOCX backend. Original
uploads and existing stored results remain unchanged. Re-upload an old document
if you want its extraction regenerated with Docling.

Models default to `storage/docling-models/`. `DOCLING_ARTIFACTS_PATH` can point to
another local model directory. OCR is a separate setting and remains off unless
configured with `DOCLING_OCR=1` and existing local model/key files through
`DOCLING_OCR_DET_MODEL`, `DOCLING_OCR_CLS_MODEL`, `DOCLING_OCR_REC_MODEL`, and
`DOCLING_OCR_REC_KEYS`. Scanned documents without readable text or configured OCR
fail clearly; no legacy parser is used as fallback.

Single-SOP optimization reconciles generated passages against source evidence.
Unsupported rewrites are removed and source content is retained. Missing template
information stays explicitly unresolved. Generated PDFs are drafts with immutable
per-generation evidence, validation and section files. Author approval remains
required; model scores do not establish factual correctness.

Existing routes, LangGraph routing, Azure provider integration, hierarchical
chunking, FAISS FlatIP indexes and ReportLab output remain in place. No database
migration is required. PyMuPDF is listed in `requirements-test.txt` only for
synthetic fixtures and generated-PDF verification, not production ingestion.
See [DOCLING_MIGRATION.md](DOCLING_MIGRATION.md) for migration and verification.
# sop_spotimizer_latest
