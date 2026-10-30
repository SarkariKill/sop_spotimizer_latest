# Codebase architecture review

Reviewed: 27 October 2026. Scope: repository architecture, source structure, core execution paths, persistence, frontend/API contracts, prompts, launcher, dependencies, and available tests. This is a source-based engineering assessment with targeted local verification, not a claim that every runtime scenario or every line has been independently verified. No application behavior was changed.

## Executive assessment

The product is a locally hosted SOP processing application with substantial document-processing functionality. Its strongest foundations are canonical English representations, structured table extraction, explicit workflow routing, deterministic audit rules, and separate source/output artifacts. Its main weaknesses are identity enforcement, preservation guarantees, consistency across SQLite/files/vector indexes, and large modules with intertwined responsibilities.

The architecture is suitable for continued local development. Multi-user deployment needs authentication and ownership enforcement first. Generated SOP quality needs source-retention checks independent of template compliance scores.

## System map

| Layer | Implementation | Responsibility |
| --- | --- | --- |
| UI | `frontend/src/main.jsx`, React 18, Vite | Login, chats, document selection, uploads, scorecards, optimization, harmonization, PDF previews, settings |
| HTTP API | `services/api/main.py`, FastAPI | Request validation, orchestration inputs, SQL persistence, artifact delivery |
| Workflow | `services/api/graph/`, `services/api/agents/` | Explicit task routing and specialized processing stages |
| Tool adapters | `services/api/tools/` | LangChain wrappers around extraction, retrieval, evaluation and generation functions |
| Document ingestion | `pdf_processor.py` | PyMuPDF PDF extraction; ZIP/XML DOCX extraction; image/table artifact storage |
| Translation | `nllb_translator.py` | Language detection and LLM-based translation with NLLB-labelled metadata |
| Retrieval | `rag_engine.py` | Hierarchical chunks, Azure embeddings, FAISS IndexFlatIP, parent-context expansion |
| Similarity | `similarity_engine.py` | Document similarities, overlap/conflicts, inferred operational groups |
| Generation | `sop_generator.py`, `harmonization_engine.py` | Optimization, section alignment, consolidation, simplification/refinement, PDF creation |
| Audit | `kenvue_guidelines.py`, `sop_evaluator.py`, `validation_agent.py` | Built-in template rules, heuristic/LLM scores, requested-change verification and remediation |
| Prompt governance | `prompt_loader.py`, `prompts/`, `skill_manager.py` | External prompts, mtime-based reload, generated optimization instructions |
| Persistence | `local_storage.py`, SQLite, FAISS files | Source files, canonical content, PDFs, artifacts, chat/history, retrieval indexes |
| LLM gateway | `services/llm/main.py` | Azure OpenAI chat and embedding endpoints, retries and chat concurrency limit |
| Startup | `run.py`, `run.sh` | Environment/dependency setup and three local services |

The actual gateway is Azure OpenAI. Groq/Gemini descriptions and defaults remain in several modules and the README. `minio_storage.py` is a compatibility alias for local storage. Embeddings in `rag_engine.py` call Azure directly, so the LLM gateway is not the sole provider integration boundary.

The supervisor routes through Python conditions, rather than asking an LLM to choose agents. Most agent classes coordinate ordinary functions/tools. Changing an orchestrator prompt does not change those routing conditions.

## Primary workflows

1. **Ingestion:** accept up to ten PDF/DOCX files per request; extract each in worker threads; detect language; produce canonical English text/pages; chunk and score; persist documents/artifacts; index the collection and compute similarity. PyMuPDF extraction uses a lock around its shared native-library work.
2. **Optimization:** select a document and baseline suggestions; compile requested changes; generate and remediate English sections; enforce template structure; score and localize; render/store PDF; validate through the graph and rebuild retrieval data; persist optimized fields.
3. **Harmonization:** select multiple documents; inventory and align sections; compare statements/tables/parameters; generate consolidated sections; flag divergent specifications; apply template rules; score/localize/render; save a version. Simplification and refinement derive additional versions.
4. **Chat:** load conversation history; retrieve child chunks and parent context; generate a grounded answer; persist messages and optionally generate a title.
5. **Language override:** retranslate stored source text and update the document record; invalidate similarity cache. Retrieval refresh is currently missing from this path.

## Persistence and consistency

SQLite contains `users`, `conversations`, `messages`, `settings`, `sop_documents`, `sop_artifacts`, `harmonized_sop_versions`, and `sop_similarity_cache`. Several complex objects are stored as JSON strings. Source/optimized data live on document records; harmonized outputs have separate version records.

SQLite WAL and busy timeouts help concurrent local requests. Initialization and column migrations happen during module import. The schema has no declared foreign keys and no uniqueness constraint on conversation/version number. Files, SQL records, and FAISS metadata/index files are written separately, so failure can leave inconsistent states. Vector stores are cached in a process-global dictionary without a per-conversation mutation lock or eviction policy.

## Findings, ordered by priority

### 1. Critical: server identity is not authenticated

`main.py:389` returns a username/role after password verification but issues no session or token. Subsequent handlers trust `X-User-Name`; settings administration at `main.py:718` checks the database role associated with that supplied name. A caller can claim `admin` without proving possession of the password. Multiple read/mutation routes accept only conversation/document IDs and do not check ownership; examples include messages at `main.py:436` and chat at `main.py:3006`.

Introduce server-verified sessions or signed tokens and a shared current-user dependency. Scope every conversation/document/artifact query to the verified owner. Add negative tests for forged admin headers and cross-user access. The seeded `admin/admin` credential and fast SHA-256 password hashing in `auth.py` also need replacement before shared deployment.

### 2. High: optimizing one document replaces retrieval for the conversation

`agents/retrieval_agent.py:156` indexes only the selected document's optimized chunks with `incremental=False`. `tools/retrieval_tools.py` forwards that to `build_and_save`, replacing the entire conversation index. Other uploaded documents remain in SQL/UI but disappear from retrieval.

Replace only the selected document's chunks, retaining other documents. Decide explicitly whether original and optimized versions are both searchable and attach version/type metadata.

### 3. High: multilingual normalization loses content and source-page fidelity

`nllb_translator.py:1228` limits translation input to the first 8,000 characters. `translate_pages_to_english` redistributes the translated text across original page numbers by paragraph counts, or repeats the full translation on every page. Consequently, later instructions can be omitted and citations can point to incorrect original pages.

Translate bounded source segments with stable document/page/block identifiers, preserve segment lineage, and verify coverage. Despite NLLB model metadata and descriptions, the active translation path calls the generic LLM gateway; it does not load or execute the named NLLB model.

### 4. High: QA remediation results are not propagated to output

`agents/validation_node_agent.py:74` and `:95` retain the tool's validation report but ignore its returned `sections`. The tool remediates a copy. The graph can therefore record a successful remediation while retaining older content and the already-generated PDF/scores.

Make validation return an authoritative document object; propagate changed sections, then regenerate localized sections, PDF and scores. The evaluation wrapper also accepts `original_text`, `artifacts` and `is_harmonization` without using them to verify retention. Template and keyword checks cannot establish that all source parameters or media survived.

### 5. High: embedding fallback can mix incompatible vector spaces

`rag_engine.py:392` falls back to hash-based word vectors when Azure is missing or fails. Index metadata does not record the embedding implementation/model. Index compatibility checks compare dimensions only. Same-sized Azure and fallback vectors can therefore be indexed or queried together despite having unrelated meanings.

Persist embedding provenance and enforce matching model/configuration for indexing and queries. Represent degraded retrieval explicitly; rebuild consistently when the embedding implementation changes. Exact FAISS search guarantees exact vector ranking, not semantic correctness.

### 6. High: unsafe HTML rendering in chat

`frontend/src/main.jsx:23` returns parsed Markdown without sanitizing it, and `:3481` inserts it with `dangerouslySetInnerHTML`. Citation badge construction also interpolates document names into HTML. Message/model/document-derived text can introduce executable browser content.

Sanitize rendered HTML with an allowlist, validate link protocols, and construct citation badges through React nodes or escaped text.

### 7. High: storage containment check accepts sibling paths

`local_storage.py:60` uses string `startswith` for directory containment. A normalized path under a sibling such as `storage-other` passes when the allowed directory is `storage`. A local check reproduced this resolver escape without writing outside the test directory.

Use resolved paths and path-component containment checks; reject symlink escapes as appropriate. This confirms a storage primitive defect, not that every public endpoint exposes arbitrary path input.

### 8. High: harmonization file history can be overwritten

`harmonization_engine.py:1039` starts every fresh harmonization at version 1 and builds the file path from that version and a shortened title. Repeating a harmonization with the same title/conversation can overwrite a PDF referenced by an earlier SQL row. Derived versions also need atomic numbering under concurrency.

Use immutable version IDs in artifact paths and transactionally allocate version numbers with a database uniqueness constraint.

### 9. Medium: invalid document IDs silently target another SOP

`main.py:1819` falls back to the latest conversation document when an explicitly supplied document ID is not found. A stale selection can therefore optimize the wrong SOP. Return 404 for an invalid explicit ID; reserve latest-document selection for requests that omit it.

### 10. Medium: language overrides leave derived data stale

`main.py:1402` updates canonical text and language metadata and clears similarity cache, but does not rebuild existing chunks/indexes or refresh scores. Chat and later comparisons can use older text. Treat this as a document revision and invalidate/recompute dependent artifacts.

### 11. Medium: operational and maintainability constraints

- Uploads limit file count but read entire files without a byte limit. Add size/page/resource bounds.
- Long operations stay inside HTTP requests. Gateway retries can outlive caller timeouts, and clients have no persistent job handle or resumability.
- Frontend progress advances using elapsed-time timers, not backend stage events; displayed stages can differ from actual work.
- `main.py` has 3,100 lines; `main.jsx` has 3,633; CSS has 3,772. Route, business, persistence and UI-state changes have broad regression surfaces.
- Process-global FAISS caching and non-atomic paired file writes need locking and recovery before multi-worker deployment.
- Several Python requirements are open-ended; no Python lockfile or CI configuration was found. The frontend does have a package lockfile.
- Built-in guideline text, prompts, generated skill instructions and remediation heuristics express overlapping rules. Changes need coordinated review to avoid contradictory behavior.
- Local `.env` and SQLite both store provider configuration, including the key. Keep secret handling and configuration precedence in a single component.

## Verification performed

| Check | Result |
| --- | --- |
| Python AST syntax parsing | All 41 Python files passed |
| Scoring/optimization rule suite | 12 passed |
| Structured tables and section harmonization suite | 7 passed |
| Prompt externalization suite | 6 passed |
| Storage path containment probe | Reproduced sibling-directory escape |
| Optimization adapter probe | Confirmed selected-document optimization requests a full conversation-index rebuild |
| QA adapter probe | Confirmed remediated sections are discarded while the passing report is retained |

Tests used temporary storage. The prompt hot-reload test creates and removes a temporary prompt file. No application source behavior was modified.

The current Python interpreter lacks `python-docx`, which three broader test modules import. Those suites were not run. Frontend dependencies are not installed in `frontend/node_modules`, so a fresh production build was not performed. Existing `dist` output does not establish current-source build correctness. Live Azure requests, real multilingual document fidelity, browser execution and production load behavior were not verified. Passing the selected tests does not cover the findings above.

## Recommended change strategy

1. Establish authenticated identity and ownership boundaries; sanitize HTML and correct storage containment.
2. Fix document-scoped retrieval replacement, embedding provenance, translation coverage and QA output propagation.
3. Make version artifact paths immutable and make derived-data invalidation explicit.
4. Add regression tests for those defects, using realistic multi-document/multilingual fixtures and failure injection.
5. Extract API routers, application services and repositories incrementally. Split frontend feature components and data-access hooks alongside the requested feature changes.
6. Add persistent background jobs and progress events when deployment/volume requirements justify them; retain SQLite/local storage for a single-host use case if those requirements remain modest.

For upcoming changes, preserve explicit document IDs, original/canonical/localized representations, source lineage, artifact ownership, version lineage and before/after evaluation semantics. A feature that touches translation, scoring, optimization or retrieval often needs coordinated updates across the API, workflow state, adapters, storage and frontend.
