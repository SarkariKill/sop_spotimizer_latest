"""
LangChain Tool Registry for the Kenvue Agentic SOP Platform.
"""
from typing import List
from langchain_core.tools import BaseTool

from .document_tools import (
    detect_sop_language_tool,
    translate_sop_to_english_tool,
    translate_pages_to_english_tool,
    translate_sop_sections_from_english_tool,
    invoke_extract_sop_pdf,
)
from .retrieval_tools import (
    create_hierarchical_chunks_tool,
    faiss_index_chunks_tool,
    faiss_search_context_tool,
    get_guidelines_context_tool,
)
from .evaluation_tools import (
    evaluate_sop_tool,
    analyze_multi_sop_similarity_tool,
    validate_sop_sections_tool,
)
from .generation_tools import (
    generate_optimized_sop_tool,
    harmonize_sops_tool,
    simplify_harmonized_sop_tool,
    refine_harmonized_sop_tool,
)

ALL_AGENT_TOOLS: List[BaseTool] = [
    detect_sop_language_tool,
    translate_sop_to_english_tool,
    translate_pages_to_english_tool,
    translate_sop_sections_from_english_tool,
    create_hierarchical_chunks_tool,
    faiss_index_chunks_tool,
    faiss_search_context_tool,
    get_guidelines_context_tool,
    evaluate_sop_tool,
    analyze_multi_sop_similarity_tool,
    validate_sop_sections_tool,
    generate_optimized_sop_tool,
    harmonize_sops_tool,
    simplify_harmonized_sop_tool,
    refine_harmonized_sop_tool,
]

__all__ = [
    "ALL_AGENT_TOOLS",
    "detect_sop_language_tool",
    "translate_sop_to_english_tool",
    "translate_pages_to_english_tool",
    "translate_sop_sections_from_english_tool",
    "invoke_extract_sop_pdf",
    "create_hierarchical_chunks_tool",
    "faiss_index_chunks_tool",
    "faiss_search_context_tool",
    "get_guidelines_context_tool",
    "evaluate_sop_tool",
    "analyze_multi_sop_similarity_tool",
    "validate_sop_sections_tool",
    "generate_optimized_sop_tool",
    "harmonize_sops_tool",
    "simplify_harmonized_sop_tool",
    "refine_harmonized_sop_tool",
]
