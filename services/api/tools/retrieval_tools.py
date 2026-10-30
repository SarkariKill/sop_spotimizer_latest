"""
LangChain Tool Wrappers for Hierarchical Chunking, FAISS FlatIP Vector Indexing,
Semantic Retrieval, and Kenvue Template Guideline Context Retrieval.
Wraps existing functions in `rag_engine.py` and `template_manager.py`.
"""
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from rag_engine import create_hierarchical_chunks, get_vector_store
from template_manager import template_manager

logger = logging.getLogger("kenvue_agentic_tools.retrieval")


class CreateHierarchicalChunksInput(BaseModel):
    pages_data: List[Dict[str, Any]] = Field(..., description="List of Canonical English page dicts ({'page', 'text'})")
    document_id: str = Field(..., description="Unique SOP document UUID")
    filename: str = Field(..., description="SOP PDF filename")
    artifacts_data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Extracted media artifacts for table/image chunk linking")


class FaissIndexChunksInput(BaseModel):
    conversation_id: str = Field(..., description="Conversation UUID")
    child_chunks: List[Dict[str, Any]] = Field(..., description="Child chunks to embed and index in FAISS FlatIP")
    incremental: bool = Field(default=True, description="True to append via add_and_save, False to rebuild via build_and_save")


class FaissSearchContextInput(BaseModel):
    conversation_id: str = Field(..., description="Conversation UUID")
    query: str = Field(..., description="Natural language search query")
    top_k: int = Field(default=6, description="Maximum number of nearest-neighbor chunks to retrieve")


class GuidelinesContextInput(BaseModel):
    query: str = Field(
        default="Standard Operating Procedure mandatory sections header metadata responsibilities quality compliance formatting rules",
        description="Semantic query for retrieving official Kenvue SOP template guidelines",
    )
    top_k: int = Field(default=6, description="Maximum guideline chunks to retrieve")


@tool("create_hierarchical_chunks_tool", args_schema=CreateHierarchicalChunksInput)
def create_hierarchical_chunks_tool(
    pages_data: List[Dict[str, Any]],
    document_id: str,
    filename: str,
    artifacts_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Splits Canonical English SOP pages into hierarchical Parent Chunks (2000 chars)
    and Child Chunks (450 chars) for high-precision FAISS FlatIP semantic retrieval.
    """
    logger.info(
        "[Tool:create_hierarchical_chunks_tool] Chunking '%s' (doc_id=%s, pages=%d)",
        filename,
        document_id,
        len(pages_data),
    )
    parent_chunks, child_chunks = create_hierarchical_chunks(
        pages_data=pages_data,
        document_id=document_id,
        filename=filename,
        artifacts_data=artifacts_data,
    )
    return {
        "parent_chunks": parent_chunks,
        "child_chunks": child_chunks,
        "parent_count": len(parent_chunks),
        "child_count": len(child_chunks),
    }


@tool("faiss_index_chunks_tool", args_schema=FaissIndexChunksInput)
def faiss_index_chunks_tool(
    conversation_id: str,
    child_chunks: List[Dict[str, Any]],
    incremental: bool = True,
) -> Dict[str, Any]:
    """
    Embeds Canonical English child chunks using Azure text-embedding-3
    and indexes them into the conversation's FAISS IndexFlatIP vector store.
    """
    logger.info(
        "[Tool:faiss_index_chunks_tool] Indexing %d chunk(s) into FAISS FlatIP for conversation '%s' (incremental=%s)",
        len(child_chunks),
        conversation_id,
        incremental,
    )
    vs = get_vector_store(conversation_id)
    if incremental:
        vs.add_and_save(child_chunks)
    else:
        vs.build_and_save(child_chunks)
    total_vectors = int(vs.index.ntotal) if vs.index is not None else len(vs.child_chunks or child_chunks)
    return {
        "conversation_id": conversation_id,
        "indexed_chunks": len(child_chunks),
        "total_vectors": total_vectors,
        "index_type": "FAISS IndexFlatIP (Exact Cosine Inner Product - Canonical English)",
    }


@tool("faiss_search_context_tool", args_schema=FaissSearchContextInput)
def faiss_search_context_tool(
    conversation_id: str,
    query: str,
    top_k: int = 6,
) -> Dict[str, Any]:
    """
    Performs semantic similarity search over the conversation's FAISS FlatIP vector store
    and returns deduplicated parent-context blocks and referenced page numbers.
    """
    logger.info(
        "[Tool:faiss_search_context_tool] Searching FAISS FlatIP for conversation='%s', top_k=%d",
        conversation_id,
        top_k,
    )
    vs = get_vector_store(conversation_id)
    retrieved_chunks: List[Dict[str, Any]] = []
    rag_context_blocks: List[str] = []

    if vs.index is not None and vs.index.ntotal > 0:
        retrieved_chunks = vs.search(query, top_k=top_k)
        if retrieved_chunks:
            seen_parents = set()
            for chunk in retrieved_chunks:
                p_id = chunk.get("parent_id")
                if p_id in seen_parents:
                    continue
                seen_parents.add(p_id)
                page = chunk.get("page", 1)
                doc_name = chunk.get("filename", "")
                parent_text = chunk.get("parent_text") or chunk.get("child_text", "")
                if doc_name:
                    rag_context_blocks.append(f"--- [Document: {doc_name} | Page {page}] ---\n{parent_text}")
                else:
                    rag_context_blocks.append(f"--- [SOP Document Excerpt (Page {page})] ---\n{parent_text}")

    referenced_pages = list({c["page"] for c in retrieved_chunks if c.get("page")})
    return {
        "retrieved_chunks": retrieved_chunks,
        "rag_context_blocks": rag_context_blocks,
        "referenced_pages": referenced_pages,
        "rag_applied": bool(rag_context_blocks),
    }


@tool("get_guidelines_context_tool", args_schema=GuidelinesContextInput)
def get_guidelines_context_tool(
    query: str = "Standard Operating Procedure mandatory sections header metadata responsibilities quality compliance formatting rules",
    top_k: int = 6,
) -> str:
    """
    Retrieves official Kenvue Corporate SOP Template structural and formatting guidelines
    from the admin template vector store.
    """
    logger.info("[Tool:get_guidelines_context_tool] Retrieving Kenvue template guidelines (top_k=%d)", top_k)
    return template_manager.get_guidelines_context(query=query, top_k=top_k)
