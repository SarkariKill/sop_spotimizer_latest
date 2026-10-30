# Docling ingestion and source-grounded SOP optimization

> Historical report for the initial hybrid implementation. The later user-authorized Docling-only migration supersedes its optional-engine and native-fallback sections. See [DOCLING_MIGRATION.md](DOCLING_MIGRATION.md) for the current pipeline.

Completed 27 October 2026. This report supersedes the pre-change architecture review for the ingestion and single-SOP optimization paths described here.

## Audit and reproduced defects

The complete README and actual call paths were inspected before changes. Source code establishes FAISS **IndexFlatIP**, not HNSW, and an Azure OpenAI gateway. Neither was replaced.

**Ingestion:** `POST /conversations/{id}/upload-sop` → bounded existing worker pool → LangGraph document agent → `invoke_extract_sop_pdf` → extraction → language normalization → hierarchical chunking → evaluation → SQLite/artifacts → collection indexing/similarity. The existing contract is `(pages_data, artifacts_data, stats)`, with page dictionaries, structured table/image dictionaries, and parent/child chunk dictionaries. PDF extraction uses PyMuPDF; DOCX extraction actually uses ZIP/XML, not python-docx. There was no active OCR implementation. Tables, raster/vector figures, and native PDF page numbers already worked and were retained.

**Optimization:** existing optimize endpoint → supervisor → optimization agent → generation tool → `generate_optimized_sop` → validation → retrieval stage → persistence/download. The actual generation prompt is `prompts/single_sop_optimization.md`, loaded through `prompt_loader`. The optimization agent's descriptive class prompt is not the generator's operative prompt. The generator had no separate source-safe fallback prompt. Dynamic file loading/interpolation remained intact.

Before implementation, a source containing only “Inspect the seal.” reproduced all three of these defects:

- Template normalization inserted cleanroom requirements not in the source.
- It inserted generic Operator, Shift Supervisor, and QA duties.
- PDF rendering printed APPROVED, a fabricated document ID, and a fabricated version.

Other confirmed causes were concrete operating examples and invented-tolerance instructions in the optimization prompt; generic factual injection during remediation; source digests/context limits; previous generated text being treated as the factual baseline; and final template normalization introducing additional facts after validation. The graph's separate QA node could also retain a remediation report without retaining its corrected sections. Whole-document translation truncated input at 8,000 characters and distributed translated paragraphs across source page numbers without correspondence.

## Implementation decisions

### Selective hybrid ingestion

`document_ingestion.py` preserves the existing extraction tuple. Native extraction remains the default and continues to supply original binary assets and structured tables. `SOP_EXTRACTION_ENGINE=docling` opts into structural parsing. Conversion is serialized inside existing ingestion worker threads, and converters are reused.

For DOCX, real Docling conversion supplies headings, hierarchy, reading order, table structure, and figure references. Native text/media remain authoritative, and exact passage matches attach Docling section references to the evidence inventory. DOCX pages are explicitly labelled logical pages; they are not claimed to be rendered Word pages.

For PDF, the adapter supports Docling structure with native PyMuPDF assets only when an explicit local model directory is configured. OCR defaults off and requires separate explicit local model/key files when enabled. Missing dependencies/models, partial conversion, empty output, or lost native content produce a logged and persisted review-required fallback. Partial Docling text is never concatenated with native text. No-text input is rejected before indexing; partial asset references are carried to the existing rejection cleanup path. Extraction and asset-storage warnings are exposed rather than swallowed.

The supported versioned APIs were checked against [Docling 2.60.1 converter source](https://github.com/docling-project/docling/blob/v2.60.1/docling/document_converter.py) and its [declared dependencies](https://github.com/docling-project/docling/blob/v2.60.1/pyproject.toml). Compatibility was exercised on CPython 3.11.8, macOS 15.6.1 arm64, Pydantic 2.10.5, NumPy 1.26.4 and the existing Torch 2.3.1. Docling 2.60.1, docling-core 2.48.2, docling-ibm-models 3.9.1 and Transformers 4.49.0 form the optional profile. The initial import exposed an incompatible inherited Transformers 4.42.3; the selected profile corrects that dependency. Packages were installed only in a temporary virtual environment, not the application's Python installation.

### Source evidence and reconciliation

`source_grounding.py` creates stable evidence IDs with document identity, filename, source passage, page provenance, section relationships, reading order, extraction status, source hash and original asset records. The document agent persists this under the existing conversation storage tree. Chunk dictionaries receive additive engine/provenance/evidence-ID fields without changing their existing text, embedding model, index type or schema requirements.

The single-SOP generation path now:

1. Uses original canonical source, never prior generated prose as factual evidence. Explicit invalid document IDs return 404, and legacy section fallbacks are document-scoped.
2. Validates an existing evidence manifest against the current source hash/document ID. Older or stale manifests fall back to complete source text with provenance review required.
3. Batches complete serialized source elements. Oversized elements remain intact in the output and are explicitly reported; they are not truncated to fit a prompt.
4. Requests source-linked statements through the existing model/gateway and hot-loaded Markdown prompt.
5. Validates actual evidence IDs and entire associated passages. Only exact passages and a small documented spelling-repair allowlist are automatically accepted. Swapped units/values, removed negations, additional duties, fabricated IDs, broader paraphrases and extra prose fail this gate. This verifies contextual passage identity rather than checking whether a number occurs somewhere else or accepting a similarity score.
6. Allows one correction attempt per batch with exact findings/evidence. Remaining unverifiable output is discarded and the original passage is restored. Every source element remains represented, including omitted or repeated source instructions. Missing template sections receive explicit author-review disclosures, not generic operating requirements.
7. Runs existing style/evaluation checks without allowing the legacy requirement injector to mutate the reconciled single-SOP draft. Template violations, pending requests, unreadable assets and translation uncertainty remain review findings. Model scores cannot override the factual gate.
8. Renders a draft only after reconciliation. The renderer avoids legacy artifact placement that manufactures checklist obligations, deduplicates unchanged tables against their source artifacts, and reports assets it could not render.
9. Writes a unique immutable generation folder containing PDF, canonical/localized sections, evidence and validation JSON. Failed writes remove the newly saved generation files. Existing original and generated files are not overwritten.

The QA graph node preserves this report, including `passed=false` and human-review requirements, without reintroducing generic operational content. The retrieval stage retains the original source index for grounded drafts, preserving other documents and actual page citations instead of indexing placeholder sections as invented page numbers.

Translation now processes the complete source in bounded segments and translates each actual source page independently. Translations still require human verification; canonical checks are not asserted to establish localized semantic equivalence.

### Presentation and compatibility

Existing routes and response keys remain. `artifact_version_id` is additive. SQLite stores the latest document pointer and report as before; no database migration is required. The existing UI workflow is unchanged. Only optimization validation/completion labels were corrected so a failed report cannot display “100% certified.” PDFs no longer claim fabricated approval/document metadata. Scores remain evaluations, not approval evidence.

The Kenvue section names/order are reused from `ALL_CANONICAL_SECTIONS`: sections 1.0 through 9.0, followed by Document Revision History. No alternate section standard was invented. Existing harmonization, simplification and refinement engines were retained; the new content-reconciliation gate specifically covers single-SOP optimization.

## Files changed and reasons

| Files | Purpose |
| --- | --- |
| `document_ingestion.py` (new) | Optional Docling adapter, native coverage guard, engine/status/provenance, controlled fallback |
| `source_grounding.py` (new) | Evidence inventory, source mapping, bounded generation/reconciliation, review findings |
| `pdf_processor.py` | Observable extraction/storage warnings; malformed DOCX rejection |
| `tools/document_tools.py` | Feed the adapter through the existing binary extraction wrapper |
| `agents/document_agent.py` | Preserve/persist evidence, attach structural provenance, expose partial-asset cleanup information |
| `rag_engine.py` | Add source provenance to existing chunk metadata |
| `main.py` | Original-source authority, document isolation, evidence cleanup, additive version identifier |
| `sop_generator.py` | Grounded generation gate, truthful draft rendering, asset integrity and immutable generation files |
| `agents/validation_node_agent.py` | Retain the source gate; prevent post-render factual injection |
| `agents/retrieval_agent.py` | Preserve source citations/index for grounded drafts; retain other documents in the legacy rebuild path |
| `skill_manager.py` | Distinguish requested edits from evidence; stop demanding invented tolerances |
| `prompts/single_sop_optimization.md`, `prompts/validation_agent.md` | Align generation/validation authority and output contract with source checks |
| `requirements-docling.txt` (new) | Optional compatible dependency profile; base requirements unchanged |
| `frontend/src/main.jsx` | Correct validation-status and optimization-completion wording without changing flows |
| `tests/test_grounded_ingestion.py` (new) | Extraction, real Docling, provenance, rejection/remediation, parameter, asset, translation and version regressions |
| `tests/test_all_features_e2e.py` | Verify immutable document pointers and invalid-source rejection |
| `tests/__init__.py` (new) | Make existing cross-suite imports resolve the repository's tests |
| `README.md`, this report | Setup, scope, limitations and verification record |

## Verification

The final full run executed **93 tests: all passed, no skips**, in an isolated repository copy with temporary storage/configuration and the optional Docling environment. It covered upload guards, PDF/DOCX extraction, multi-page tables, images, nested sections, native chunk/index contracts, multilingual file isolation, source/page preservation, rejected unsupported statements, contextual signed values/units/tolerances, missing sections, spelling repair, bounded bad remediation, oversized source preservation, immutable artifacts, source identity, unreadable-asset reporting, scanned-document rejection/cleanup, Kenvue scoring, similarity, RAG, harmonization, simplification/refinement, downloads, persistence and deletion.

Real Docling DOCX conversion and the enabled hybrid adapter were executed against synthetic heading/table/image fixtures. Native PDF/table and DOCX regressions also passed. PDF/OCR local-model configuration guards were tested, but actual PDF model/OCR accuracy was not.

All **45 Python files** passed AST syntax parsing. The locked frontend dependencies were installed only in the temporary copy, and **`npm run build` passed**. A generated two-page synthetic PDF was text-checked and its first page visually inspected: the draft banner, missing-information disclosures, signed values/tolerances and structured table rendered correctly. No live Azure inference or real customer documents were used.

The first expanded run identified an existing test-package import problem and a test that assumed mutable fixed output filenames. `tests/__init__.py` fixes local helper resolution, and the file-isolation test now checks the actual immutable database pointers. Subsequent full runs passed. Test-only model responses and scores remain mocks; production scoring still uses the existing gateway.

## Installation and limits

- No mandatory new service, vector database, authentication change or schema migration was introduced.
- Default native ingestion works without Docling. Enable the optional profile using the commands/settings in the README after dependency validation in the deployment environment.
- The profile was tested on the runtime above. It does not establish support for every Python 3.10–3.14/OS combination or compatibility with unrelated packages in a shared Python installation. Prefer a dedicated application environment.
- Actual PDF Docling/OCR inference requires locally provisioned models and deployment validation. No model accuracy improvement is claimed from installation alone.
- Automatic semantic verification of arbitrary paraphrases is not solved. The intentionally conservative implementation accepts exact passages/small spelling repairs and restores source for other rewrites. Broader readability improvements, new requested requirements and uncertain section mappings require author review.
- Translation semantics and unreadable visual information require human review. Source coverage means coverage of extracted source evidence, not proof that OCR or an unseen diagram contains no additional instructions.
- Missing-source documents fail or carry provenance-review findings. High template scores do not establish factual correctness or approval. Existing harmonization/refinement factual policies are outside this single-SOP grounding change.
