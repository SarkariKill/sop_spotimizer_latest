import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import faiss
import httpx
import numpy as np

logger = logging.getLogger(__name__)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = (
    os.getcwd()
    if os.path.exists(os.path.join(os.getcwd(), "services"))
    else os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
)
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, ".env")
DEFAULT_INDEX_DIR = os.path.join(PROJECT_ROOT, "storage", "indexes")
INDEX_STORAGE_PATH = os.getenv("INDEX_STORAGE_PATH", DEFAULT_INDEX_DIR)
os.makedirs(INDEX_STORAGE_PATH, exist_ok=True)

# Default dimension for Azure text-embedding-3-small (1536)
DEFAULT_EMBEDDING_DIM = 1536


def _read_env_var(key_name: str, default: str = "") -> str:
    """Dynamically reads a variable from .env on disk so Admin UI updates apply immediately."""
    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        k, v = s.split("=", 1)
                        if k.strip() == key_name:
                            return v.strip().strip('"').strip("'")
        except Exception:
            pass
    return os.getenv(key_name, default).strip()


def _normalize_azure_endpoint(raw_endpoint: str) -> str:
    """Normalizes AZURE_OPENAI_ENDPOINT to base URL (https://<resource>.openai.azure.com)."""
    ep = (raw_endpoint or "").strip().rstrip("/")
    if not ep:
        return ""
    ep = re.sub(r"/openai(?:/.*)?$", "", ep, flags=re.IGNORECASE).rstrip("/")
    return ep


def get_azure_embedding_config() -> Dict[str, str]:
    """Returns current Azure OpenAI Embedding configuration from .env / environment."""
    endpoint = _normalize_azure_endpoint(_read_env_var("AZURE_OPENAI_ENDPOINT"))
    api_key = _read_env_var("AZURE_OPENAI_KEY") or _read_env_var("LLM_API_KEY")
    deployment = _read_env_var("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    api_version = _read_env_var("AZURE_OPENAI_API_VERSION", "2024-02-01") or "2024-02-01"
    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "deployment": deployment,
        "api_version": api_version,
    }


def get_index_paths(conversation_id):
    base = os.path.join(INDEX_STORAGE_PATH, f"faiss_{conversation_id}")
    return base + ".index", base + "_meta.json"


def clear_vector_store(conversation_id):
    _vector_stores.pop(conversation_id, None)
    for path in get_index_paths(conversation_id):
        if os.path.exists(path):
            os.remove(path)


# =====================================================================
# 1. HERE HIERARCHICAL CHUNKING HAPPENS
# Divides PDF text into Parent Chunks (macro context) and Child Chunks
# (fine search units). Parent chunks ensure the LLM receives complete
# surrounding instructions, while child chunks ensure precise retrieval.
# =====================================================================

def create_hierarchical_chunks(
    pages_data: List[Dict[str, Any]],
    parent_chunk_size: int = 1000,
    parent_chunk_overlap: int = 150,
    child_chunk_size: int = 250,
    child_chunk_overlap: int = 40,
    document_id: Optional[str] = None,
    filename: Optional[str] = None,
    artifacts_data: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    # --- HERE HIERARCHICAL & SEMANTIC CHUNKING HAPPENS ---
    Extracts section-aware hierarchical parent and child chunks from document pages,
    annotating each chunk with section numbers, titles, parent-child hierarchies,
    page ranges, and associated table/image artifact IDs without slicing tables mid-row.
    """
    parent_chunks: List[Dict[str, Any]] = []
    child_chunks: List[Dict[str, Any]] = []
    artifacts_data = artifacts_data or []

    child_global_idx = 0
    parent_global_idx = 0

    heading_regex = re.compile(r"^(?:#{1,4}\s*)?(\d{1,2}(?:\.\d{1,2})*|\b[IVXLCDM]+\.?)\s+([A-Za-z0-9\s\(\)\/\-\,\&]+)$")
    current_sec_id = "1.0"
    current_sec_title = "Document Overview"
    current_parent_sec_id = "1"

    def derive_parent_sec_id(sec_id: str) -> Optional[str]:
        if not sec_id:
            return None
        parts = sec_id.split(".")
        if len(parts) > 2:
            return ".".join(parts[:-1])
        elif len(parts) == 2 and parts[1] != "0":
            return f"{parts[0]}.0"
        elif len(parts) == 2:
            return parts[0]
        return None

    for page_item in pages_data:
        page_num = page_item["page"]
        text = page_item.get("text", "").strip()
        if not text:
            continue

        # Split page text into paragraphs
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not raw_paragraphs:
            raw_paragraphs = [text]

        # Scan paragraphs to construct section-aware parent chunks
        current_parent_items: List[str] = []
        current_parent_len = 0
        page_parents: List[Dict[str, Any]] = []

        for p in raw_paragraphs:
            first_line = p.split("\n")[0].strip()
            hm = heading_regex.match(first_line)
            if hm and len(first_line) < 70 and not any(ch in first_line for ch in [":", ";", "="]):
                # If section heading detected and we have pending text, flush current parent chunk
                if current_parent_items:
                    p_text = "\n\n".join(current_parent_items).strip()
                    page_parents.append({
                        "text": p_text,
                        "section_id": current_sec_id,
                        "section_title": current_sec_title,
                        "parent_section_id": current_parent_sec_id,
                    })
                    current_parent_items = []
                    current_parent_len = 0

                current_sec_id = hm.group(1).strip()
                current_sec_title = hm.group(2).strip()
                current_parent_sec_id = derive_parent_sec_id(current_sec_id)
            elif "revision history" in first_line.lower() and len(first_line) < 40:
                if current_parent_items:
                    p_text = "\n\n".join(current_parent_items).strip()
                    page_parents.append({
                        "text": p_text,
                        "section_id": current_sec_id,
                        "section_title": current_sec_title,
                        "parent_section_id": current_parent_sec_id,
                    })
                    current_parent_items = []
                    current_parent_len = 0

                current_sec_id = "10.0"
                current_sec_title = "Document Revision History"
                current_parent_sec_id = "10"

            # Check if paragraph is a table block
            is_table_block = "|" in p and ("---" in p or p.count("|") >= 4)

            if current_parent_len + len(p) + 2 > parent_chunk_size and current_parent_items:
                p_text = "\n\n".join(current_parent_items).strip()
                page_parents.append({
                    "text": p_text,
                    "section_id": current_sec_id,
                    "section_title": current_sec_title,
                    "parent_section_id": current_parent_sec_id,
                })
                # Overlap
                overlap_text = current_parent_items[-1] if current_parent_items else ""
                if len(overlap_text) > parent_chunk_overlap:
                    overlap_text = overlap_text[-parent_chunk_overlap:]
                current_parent_items = [overlap_text, p] if overlap_text else [p]
                current_parent_len = len(overlap_text) + len(p)
            else:
                current_parent_items.append(p)
                current_parent_len += len(p) + 2

        if current_parent_items:
            p_text = "\n\n".join(current_parent_items).strip()
            page_parents.append({
                "text": p_text,
                "section_id": current_sec_id,
                "section_title": current_sec_title,
                "parent_section_id": current_parent_sec_id,
            })

        # Match table and image artifacts associated with this page or section
        page_table_ids = [
            a["id"] for a in artifacts_data
            if a.get("artifact_type") == "table" and (
                a.get("page") == page_num
                or a.get("page_start", a.get("page")) <= page_num <= a.get("page_end", a.get("page"))
                or (a.get("section_id") and a.get("section_id") == current_sec_id)
            )
        ]
        page_image_ids = [
            a["id"] for a in artifacts_data
            if a.get("artifact_type") == "image" and a.get("page") == page_num
        ]

        # Step 2: Build Child Chunks for each Parent Chunk
        for parent_item in page_parents:
            parent_text = parent_item["text"]
            sec_id = parent_item["section_id"]
            sec_title = parent_item["section_title"]
            parent_sec_id = parent_item["parent_section_id"]

            has_tbl = "|" in parent_text and ("---" in parent_text or parent_text.count("|") >= 4)
            # Find specific table IDs referenced in text or on page
            matched_table_ids = [tid for tid in page_table_ids if tid in parent_text] or (page_table_ids if has_tbl else [])
            matched_image_ids = [iid for iid in page_image_ids if iid in parent_text] or page_image_ids

            parent_id = f"parent_{parent_global_idx}_{uuid.uuid4().hex[:6]}"
            parent_global_idx += 1

            parent_chunks.append({
                "parent_id": parent_id,
                "chunk_id": parent_id,
                "chunk_type": "parent",
                "chunk_text": parent_text,
                "page": page_num,
                "page_start": page_num,
                "page_end": page_num,
                "section_id": sec_id,
                "section_title": sec_title,
                "parent_section_id": parent_sec_id,
                "text": parent_text,
                "document_id": document_id,
                "filename": filename,
                "source_filename": filename,
                "table_ids": matched_table_ids,
                "image_ids": matched_image_ids,
                "has_table": has_tbl,
                "overlap_group_id": None,
            })

            # Subdivide Parent into Child Chunks (Micro-level search units: ~250 chars)
            # If parent text contains a table, keep table rows intact
            if has_tbl and "\n" in parent_text:
                lines = parent_text.split("\n")
                current_child_lines = []
                current_c_len = 0
                for line in lines:
                    line_len = len(line)
                    if current_c_len + line_len + 1 > child_chunk_size and current_child_lines:
                        child_slice = "\n".join(current_child_lines).strip()
                        if child_slice:
                            cid = f"child_{child_global_idx}_{uuid.uuid4().hex[:6]}"
                            child_chunks.append({
                                "chunk_id": cid,
                                "child_id": cid,
                                "parent_id": parent_id,
                                "document_id": document_id,
                                "filename": filename,
                                "source_filename": filename,
                                "page": page_num,
                                "page_start": page_num,
                                "page_end": page_num,
                                "section_id": sec_id,
                                "section_title": sec_title,
                                "parent_section_id": parent_sec_id,
                                "chunk_type": "table",
                                "text": child_slice,
                                "chunk_text": child_slice,
                                "parent_text": parent_text,
                                "index": child_global_idx,
                                "table_ids": matched_table_ids,
                                "image_ids": matched_image_ids,
                                "has_table": True,
                                "overlap_group_id": parent_id,
                            })
                            child_global_idx += 1
                        current_child_lines = [line]
                        current_c_len = line_len
                    else:
                        current_child_lines.append(line)
                        current_c_len += line_len + 1

                if current_child_lines:
                    child_slice = "\n".join(current_child_lines).strip()
                    if child_slice:
                        cid = f"child_{child_global_idx}_{uuid.uuid4().hex[:6]}"
                        child_chunks.append({
                            "chunk_id": cid,
                            "child_id": cid,
                            "parent_id": parent_id,
                            "document_id": document_id,
                            "filename": filename,
                            "source_filename": filename,
                            "page": page_num,
                            "page_start": page_num,
                            "page_end": page_num,
                            "section_id": sec_id,
                            "section_title": sec_title,
                            "parent_section_id": parent_sec_id,
                            "chunk_type": "table",
                            "text": child_slice,
                            "chunk_text": child_slice,
                            "parent_text": parent_text,
                            "index": child_global_idx,
                            "table_ids": matched_table_ids,
                            "image_ids": matched_image_ids,
                            "has_table": True,
                            "overlap_group_id": parent_id,
                        })
                        child_global_idx += 1
            else:
                # Standard paragraph / sentence slicing with clean word boundaries
                start = 0
                parent_len = len(parent_text)
                while start < parent_len:
                    end = min(start + child_chunk_size, parent_len)
                    if end < parent_len:
                        space_idx = parent_text.rfind(" ", start, end)
                        if space_idx != -1 and space_idx > start + (child_chunk_size // 2):
                            end = space_idx

                    child_slice = parent_text[start:end].strip()
                    if child_slice:
                        cid = f"child_{child_global_idx}_{uuid.uuid4().hex[:6]}"
                        child_chunks.append({
                            "chunk_id": cid,
                            "child_id": cid,
                            "parent_id": parent_id,
                            "document_id": document_id,
                            "filename": filename,
                            "source_filename": filename,
                            "page": page_num,
                            "page_start": page_num,
                            "page_end": page_num,
                            "section_id": sec_id,
                            "section_title": sec_title,
                            "parent_section_id": parent_sec_id,
                            "chunk_type": "section_or_subsection",
                            "text": child_slice,
                            "chunk_text": child_slice,
                            "parent_text": parent_text,
                            "index": child_global_idx,
                            "table_ids": matched_table_ids,
                            "image_ids": matched_image_ids,
                            "has_table": has_tbl,
                            "overlap_group_id": parent_id,
                        })
                        child_global_idx += 1

                    if end >= parent_len:
                        break
                    start = max(start + 1, end - child_chunk_overlap)

    # Add provenance without altering existing chunk text, IDs or index format.
    source_pages = {p["page"]: p for p in pages_data}
    for chunk in parent_chunks + child_chunks:
        source_page = source_pages.get(chunk.get("page"), {})
        chunk["extraction_engine"] = source_page.get("extraction_engine", "legacy")
        chunk["page_provenance"] = source_page.get("page_provenance", "unavailable")
        context_text = chunk.get("parent_text") or chunk.get("text", "")
        chunk["source_element_ids"] = [e["source_id"] for e in source_page.get("source_elements", [])
                                       if e["text"] in context_text or context_text in e["text"]]

    logger.info(
        "Hierarchical chunking complete for '%s': generated %d parent chunks and %d child chunks.",
        filename or "document",
        len(parent_chunks),
        len(child_chunks),
    )
    return parent_chunks, child_chunks


# =====================================================================
# 2. HERE AZURE TEXT-EMBEDDING-3 EMBEDDING HAPPENS
# Generates dense vector representations using Azure OpenAI Embeddings
# (AZURE_OPENAI_EMBEDDING_DEPLOYMENT) without Hugging Face / FastEmbed.
# =====================================================================

def _deterministic_fallback_embeddings(texts: List[str], dim: int = DEFAULT_EMBEDDING_DIM) -> np.ndarray:
    """Fallback generator producing deterministic semantic term vectors when Azure Embedding endpoint is unreachable."""
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for i, text in enumerate(texts):
        words = re.findall(r"\w+", text.lower())
        for w in words:
            h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if (h // dim) % 2 == 0 else -1.0
            vectors[i, idx] += sign
        norm = np.linalg.norm(vectors[i])
        if norm > 0:
            vectors[i] /= norm
    return vectors


def generate_embeddings(texts: List[str]) -> np.ndarray:
    """
    # --- HERE AZURE TEXT-EMBEDDING-3 EMBEDDING HAPPENS ---
    Generates L2-normalized vector embeddings for given texts using
    Azure OpenAI Text Embedding 3 (AZURE_OPENAI_EMBEDDING_DEPLOYMENT).
    """
    if not texts:
        return np.empty((0, DEFAULT_EMBEDDING_DIM), dtype=np.float32)

    cfg = get_azure_embedding_config()
    endpoint = cfg["endpoint"]
    api_key = cfg["api_key"]
    deployment = cfg["deployment"]
    api_version = cfg["api_version"]

    if endpoint and api_key and deployment:
        url = f"{endpoint}/openai/deployments/{deployment}/embeddings"
        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
        }
        params = {"api-version": api_version}
        batch_size = 64
        all_embeddings: List[List[float]] = []

        try:
            with httpx.Client(timeout=60.0) as client:
                for start_idx in range(0, len(texts), batch_size):
                    batch = [
                        t if (t and t.strip()) else " "
                        for t in texts[start_idx : start_idx + batch_size]
                    ]
                    response = None
                    for attempt in range(3):
                        try:
                            response = client.post(
                                url,
                                headers=headers,
                                params=params,
                                json={"input": batch},
                            )
                            if response.status_code == 200:
                                break
                            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                                time.sleep(1.0 * (attempt + 1))
                                continue
                            break
                        except httpx.RequestError as req_err:
                            if attempt < 2:
                                time.sleep(1.0 * (attempt + 1))
                                continue
                            raise req_err

                    if response is None or response.status_code != 200:
                        status_info = response.status_code if response is not None else "no_response"
                        err_body = (response.text[:300] if response is not None else "")
                        raise RuntimeError(
                            f"Azure OpenAI Embeddings returned HTTP {status_info}: {err_body}"
                        )

                    data = response.json().get("data", [])
                    data_sorted = sorted(data, key=lambda x: x.get("index", 0))
                    all_embeddings.extend([item["embedding"] for item in data_sorted])

            if len(all_embeddings) == len(texts) and len(all_embeddings) > 0:
                vectors = np.array(all_embeddings, dtype=np.float32)
                faiss.normalize_L2(vectors)
                return vectors
        except Exception as e:
            logger.warning(
                "Azure OpenAI Embedding request failed (%s); falling back to deterministic vectorizer.",
                e,
            )

    vectors = _deterministic_fallback_embeddings(texts, dim=DEFAULT_EMBEDDING_DIM)
    faiss.normalize_L2(vectors)
    return vectors


# =====================================================================
# 3. HERE FAISS VECTOR STORE HAPPENS
# Builds, saves, and loads FAISS Index for high-speed similarity search.
# =====================================================================

class FaissVectorStore:
    """
    FAISS FlatIP Vector Store manager for multi-SOP PDF chunks.
    Uses exact Inner Product (IndexFlatIP) cosine similarity search over
    L2-normalized Azure text-embedding-3 vectors to retrieve semantically
    relevant procedural, safety, and equipment chunks for RAG chat.
    """

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.index_file, self.meta_file = get_index_paths(conversation_id)
        self.index: Optional[Any] = None
        self.child_chunks: List[Dict[str, Any]] = []
        self._load_if_exists()

    def _load_if_exists(self):
        """Load existing FAISS FlatIP index from disk if present."""
        if os.path.exists(self.index_file) and os.path.exists(self.meta_file):
            try:
                self.index = faiss.read_index(self.index_file)
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    self.child_chunks = json.load(f)
                logger.info(
                    "Loaded FAISS FlatIP index for conversation %s (%d vectors, dim=%d, index_type=%s)",
                    self.conversation_id,
                    self.index.ntotal,
                    self.index.d,
                    type(self.index).__name__,
                )
            except Exception as e:
                logger.error("Failed loading FAISS FlatIP index for %s: %s", self.conversation_id, e)

    def build_and_save(self, child_chunks: List[Dict[str, Any]]):
        """
        # --- HERE FAISS FLATIP VECTOR STORE CREATION HAPPENS ---
        Builds FAISS IndexFlatIP (Exact Inner Product Cosine Similarity on
        normalized Azure text-embedding-3 embeddings) and persists to disk.
        Provides 100% exact retrieval without graph approximation.
        """
        if not child_chunks:
            logger.warning("No child chunks provided to build FAISS FlatIP index.")
            return

        texts = [c["text"] for c in child_chunks]
        
        # --- HERE AZURE TEXT-EMBEDDING-3 EMBEDDING HAPPENS ---
        vectors = generate_embeddings(texts)
        dimension = vectors.shape[1]

        # Use IndexFlatIP: exact cosine similarity on L2-normalized vectors
        index = faiss.IndexFlatIP(dimension)
        index.add(vectors)

        # Save to disk
        faiss.write_index(index, self.index_file)
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(child_chunks, f)

        self.index = index
        self.child_chunks = child_chunks
        logger.info(
            "Built and saved FAISS FlatIP index with %d vectors (dim=%d) to %s",
            index.ntotal,
            dimension,
            self.index_file,
        )

    def add_and_save(self, new_child_chunks: List[Dict[str, Any]]):
        """
        Incrementally adds new vectors into the existing FAISS FlatIP index
        and updates disk persistence. Automatically rebuilds the index if
        the embedding dimension changed.
        """
        if not new_child_chunks:
            return

        if self.index is None or not self.child_chunks:
            self.build_and_save(new_child_chunks)
            return

        new_texts = [c["text"] for c in new_child_chunks]
        new_vectors = generate_embeddings(new_texts)

        # If existing index was built with a different dimension (e.g. legacy 384-dim vs Azure 1536-dim), rebuild cleanly
        if self.index.d != new_vectors.shape[1]:
            logger.info(
                "FAISS index dimension changed (%d -> %d) for conversation %s; rebuilding full index.",
                self.index.d,
                new_vectors.shape[1],
                self.conversation_id,
            )
            combined_chunks = list(self.child_chunks) + list(new_child_chunks)
            self.build_and_save(combined_chunks)
            return

        # Add vectors to FlatIP index
        self.index.add(new_vectors)
        self.child_chunks.extend(new_child_chunks)

        # Save updated index to disk
        faiss.write_index(self.index, self.index_file)
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(self.child_chunks, f)

        logger.info(
            "Added %d vectors to FAISS FlatIP index for conversation %s (total: %d vectors)",
            len(new_child_chunks),
            self.conversation_id,
            self.index.ntotal,
        )

    # =================================================================
    # 4. HERE RETRIEVAL HAPPENS
    # Searches FAISS FlatIP index using query embedding, expands matched
    # child chunks to their parent chunks with document citation metadata.
    # =================================================================
    def search(self, query: str, top_k: int = 6) -> List[Dict[str, Any]]:
        """
        # --- HERE RETRIEVAL HAPPENS ---
        1. Embed user query using Azure Text-Embedding-3.
        2. Perform exact nearest-neighbor search via IndexFlatIP cosine dot products.
        3. Retrieve matched child chunks with originating document filename & page.
        4. Expand to Parent Chunks for rich context.
        """
        if not self.index or not self.child_chunks:
            return []

        # --- HERE EMBEDDING FOR QUERY HAPPENS ---
        query_vector = generate_embeddings([query])

        # Automatically upgrade legacy index if dimension mismatches current Azure embedding model
        if query_vector.shape[1] != self.index.d:
            logger.info(
                "Upgrading FAISS index dimension (%d -> %d) for conversation %s on search.",
                self.index.d,
                query_vector.shape[1],
                self.conversation_id,
            )
            self.build_and_save(self.child_chunks)

        k = min(top_k, self.index.ntotal)
        if k == 0:
            return []

        # Search top-k closest child chunks via exact FlatIP inner product
        distances, indices = self.index.search(query_vector, k)

        retrieved: List[Dict[str, Any]] = []
        seen_parents = set()

        for score, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.child_chunks):
                continue

            child = self.child_chunks[idx]
            parent_id = child.get("parent_id")

            # Avoid duplicate parent chunks in final context
            is_new_parent = parent_id not in seen_parents
            if is_new_parent:
                seen_parents.add(parent_id)

            retrieved.append({
                "score": float(score),
                "child_id": child.get("child_id"),
                "parent_id": parent_id,
                "child_text": child.get("text"),
                "parent_text": child.get("parent_text"),
                "page": child.get("page"),
                "filename": child.get("filename"),
                "document_id": child.get("document_id"),
                "is_primary": is_new_parent,
            })

        return retrieved


# In-memory vector store cache for active sessions
_vector_stores: Dict[str, FaissVectorStore] = {}


def get_vector_store(conversation_id: str) -> FaissVectorStore:
    """Get or create FAISS vector store instance for a conversation."""
    if conversation_id not in _vector_stores:
        _vector_stores[conversation_id] = FaissVectorStore(conversation_id)
    return _vector_stores[conversation_id]
