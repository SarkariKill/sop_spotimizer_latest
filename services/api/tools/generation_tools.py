"""
LangChain Tool Wrappers for Single-SOP Optimization, Multi-SOP Harmonization,
Simplification, and Interactive Version Refinement.
Wraps existing functions in `sop_generator.py` and `harmonization_engine.py`.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from sop_generator import generate_optimized_sop
from harmonization_engine import harmonization_engine

logger = logging.getLogger("kenvue_agentic_tools.generation")


def _run_coro_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class GenerateOptimizedSopInput(BaseModel):
    conversation_id: str = Field(..., description="Conversation UUID")
    username: str = Field(default="admin", description="Username owning the SOP")
    original_text: str = Field(..., description="Canonical English SOP text to optimize")
    original_filename: str = Field(..., description="Original PDF filename")
    selected_suggestions: List[Dict[str, Any]] = Field(
        default_factory=list, description="Selected audit improvement suggestions"
    )
    custom_instructions: str = Field(default="", description="Custom user optimization instructions")
    artifacts: List[Dict[str, Any]] = Field(default_factory=list, description="Extracted image and table artifacts")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")
    existing_sections: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Prior canonical English sections for iterative refinement"
    )
    existing_title: Optional[str] = Field(default=None, description="Prior document title for iterative refinement")
    output_language: str = Field(default="English", description="Target output language for the final PDF & sections")
    previous_scores: Optional[Dict[str, Any]] = Field(default=None, description="Previous evaluation scores for before-and-after comparison")
    document_id: Optional[str] = Field(default=None, description="Document UUID to scope optimized storage artifacts")


class HarmonizeSopsInput(BaseModel):
    conversation_id: str = Field(..., description="Conversation UUID")
    username: str = Field(default="admin", description="Username")
    source_documents: List[Dict[str, Any]] = Field(..., description="List of 2+ selected SOP document dicts")
    custom_instructions: str = Field(default="", description="Custom harmonization instructions")
    title_override: Optional[str] = Field(default=None, description="Optional title override")
    all_artifacts: List[Dict[str, Any]] = Field(default_factory=list, description="All extracted media artifacts")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")
    output_language: str = Field(default="English", description="Target output language for the harmonized SOP")


class SimplifyHarmonizedSopInput(BaseModel):
    current_version: Dict[str, Any] = Field(..., description="Current harmonized SOP version dictionary")
    selected_recommendation_ids: List[str] = Field(..., description="List of simplification recommendation IDs")
    custom_instructions: str = Field(default="", description="Custom simplification instructions")
    conversation_id: str = Field(..., description="Conversation UUID")
    username: str = Field(default="admin", description="Username")
    all_artifacts: List[Dict[str, Any]] = Field(default_factory=list, description="All extracted media artifacts")
    output_language: str = Field(default="English", description="Target output language")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")


class RefineHarmonizedSopInput(BaseModel):
    current_version: Dict[str, Any] = Field(..., description="Current harmonized SOP version dictionary")
    refinement_prompt: str = Field(..., description="User's interactive refinement instruction")
    conversation_id: str = Field(..., description="Conversation UUID")
    username: str = Field(default="admin", description="Username")
    all_artifacts: List[Dict[str, Any]] = Field(default_factory=list, description="All extracted media artifacts")
    output_language: str = Field(default="English", description="Target output language")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")


@tool("generate_optimized_sop_tool", args_schema=GenerateOptimizedSopInput)
def generate_optimized_sop_tool(
    conversation_id: str,
    original_text: str,
    original_filename: str,
    username: str = "admin",
    selected_suggestions: Optional[List[Dict[str, Any]]] = None,
    custom_instructions: str = "",
    artifacts: Optional[List[Dict[str, Any]]] = None,
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
    existing_sections: Optional[List[Dict[str, Any]]] = None,
    existing_title: Optional[str] = None,
    output_language: str = "English",
    previous_scores: Optional[Dict[str, Any]] = None,
    document_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes single-SOP optimization in Canonical English, runs QA validation/remediation,
    translates into the target output_language via NLLB-200, and compiles the ReportLab PDF.
    """
    logger.info(
        "[Tool:generate_optimized_sop_tool] Optimizing '%s' (output_language='%s', document_id='%s')",
        original_filename,
        output_language,
        document_id,
    )
    return _run_coro_sync(
        generate_optimized_sop(
            conversation_id=conversation_id,
            username=username,
            original_text=original_text,
            original_filename=original_filename,
            selected_suggestions=selected_suggestions or [],
            custom_instructions=custom_instructions,
            artifacts=artifacts or [],
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
            existing_sections=existing_sections,
            existing_title=existing_title,
            output_language=output_language,
            previous_scores=previous_scores,
            document_id=document_id,
        )
    )


@tool("harmonize_sops_tool", args_schema=HarmonizeSopsInput)
def harmonize_sops_tool(
    conversation_id: str,
    source_documents: List[Dict[str, Any]],
    username: str = "admin",
    custom_instructions: str = "",
    title_override: Optional[str] = None,
    all_artifacts: Optional[List[Dict[str, Any]]] = None,
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
    output_language: str = "English",
) -> Dict[str, Any]:
    """
    Consolidates 2+ similar SOPs into a single harmonized Kenvue SOP in Canonical English,
    resolves parameter conflicts to conservative GMP limits, translates to output_language via NLLB-200,
    and generates the versioned ReportLab PDF.
    """
    logger.info(
        "[Tool:harmonize_sops_tool] Harmonizing %d SOP(s) (output_language='%s')",
        len(source_documents),
        output_language,
    )
    return _run_coro_sync(
        harmonization_engine.harmonize_sops(
            conversation_id=conversation_id,
            username=username,
            source_documents=source_documents,
            custom_instructions=custom_instructions,
            title_override=title_override,
            all_artifacts=all_artifacts or [],
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
            output_language=output_language,
        )
    )


@tool("simplify_harmonized_sop_tool", args_schema=SimplifyHarmonizedSopInput)
def simplify_harmonized_sop_tool(
    current_version: Dict[str, Any],
    selected_recommendation_ids: List[str],
    conversation_id: str,
    custom_instructions: str = "",
    username: str = "admin",
    all_artifacts: Optional[List[Dict[str, Any]]] = None,
    output_language: str = "English",
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
) -> Dict[str, Any]:
    """
    Applies selected simplification catalog recommendations to a harmonized SOP version
    and creates a new immutable version in the chosen output_language.
    """
    logger.info(
        "[Tool:simplify_harmonized_sop_tool] Simplifying version v%s (recs=%d, output_language='%s')",
        current_version.get("version_number"),
        len(selected_recommendation_ids),
        output_language,
    )
    return _run_coro_sync(
        harmonization_engine.simplify_sop(
            current_version=current_version,
            selected_recommendation_ids=selected_recommendation_ids,
            custom_instructions=custom_instructions,
            conversation_id=conversation_id,
            username=username,
            all_artifacts=all_artifacts or [],
            output_language=output_language,
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
        )
    )


@tool("refine_harmonized_sop_tool", args_schema=RefineHarmonizedSopInput)
def refine_harmonized_sop_tool(
    current_version: Dict[str, Any],
    refinement_prompt: str,
    conversation_id: str,
    username: str = "admin",
    all_artifacts: Optional[List[Dict[str, Any]]] = None,
    output_language: str = "English",
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
) -> Dict[str, Any]:
    """
    Applies interactive user refinement prompts to a harmonized SOP version
    and creates a new immutable version in the chosen output_language.
    """
    logger.info(
        "[Tool:refine_harmonized_sop_tool] Refining version v%s (output_language='%s')",
        current_version.get("version_number"),
        output_language,
    )
    return _run_coro_sync(
        harmonization_engine.refine_sop(
            current_version=current_version,
            refinement_prompt=refinement_prompt,
            conversation_id=conversation_id,
            username=username,
            all_artifacts=all_artifacts or [],
            output_language=output_language,
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
        )
    )
