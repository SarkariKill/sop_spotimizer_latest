"""
LangChain Tool Wrappers for SOP Evaluation & Scoring, Multi-SOP Semantic Similarity Clustering,
and QA Validation & Self-Remediation.
Wraps existing functions in `sop_evaluator.py`, `similarity_engine.py`, and `validation_agent.py`.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from sop_evaluator import evaluate_sop_with_llm, evaluate_sop_heuristics
from similarity_engine import similarity_engine
from validation_agent import validation_agent

logger = logging.getLogger("kenvue_agentic_tools.evaluation")


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


class EvaluateSopInput(BaseModel):
    sop_text: str = Field(..., description="Canonical English SOP text to audit against Kenvue 10-tier guidelines")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")
    compact_mode: bool = Field(
        default=False,
        description="Enable token-optimized compact rubric when evaluating multiple SOPs concurrently",
    )


class AnalyzeSimilarityInput(BaseModel):
    documents: List[Dict[str, Any]] = Field(..., description="List of SOP document dicts with Canonical English text")
    all_child_chunks: List[Dict[str, Any]] = Field(..., description="FAISS child chunks across the collection")


class ValidateSopSectionsInput(BaseModel):
    sections: List[Dict[str, Any]] = Field(..., description="Generated SOP sections ({'heading', 'content', ...}) to validate")
    original_text: str = Field(default="", description="Source SOP text for retention & parameter preservation checks")
    artifacts: List[Dict[str, Any]] = Field(default_factory=list, description="Extracted image and table artifacts")
    selected_suggestions: List[Dict[str, Any]] = Field(
        default_factory=list, description="Selected improvement suggestions to verify"
    )
    custom_instructions: str = Field(default="", description="Custom user instructions to verify")
    is_harmonization: bool = Field(default=False, description="True if validating a multi-SOP harmonized release")
    auto_remediate: bool = Field(default=True, description="Automatically remediate any failed validation checks")


@tool("evaluate_sop_tool", args_schema=EvaluateSopInput)
def evaluate_sop_tool(
    sop_text: str,
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
    compact_mode: bool = False,
) -> Dict[str, Any]:
    """
    Audits and scores an SOP on its Canonical English representation across Template Compliance,
    Readability, and Procedural Quality (0-100) using the Kenvue 10-Tier Audit Skill and deterministic heuristics.
    """
    logger.info("[Tool:evaluate_sop_tool] Scoring SOP (compact_mode=%s, text_len=%d)", compact_mode, len(sop_text))
    return _run_coro_sync(
        evaluate_sop_with_llm(
            sop_text=sop_text,
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
            compact_mode=compact_mode,
        )
    )


@tool("analyze_multi_sop_similarity_tool", args_schema=AnalyzeSimilarityInput)
def analyze_multi_sop_similarity_tool(
    documents: List[Dict[str, Any]],
    all_child_chunks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Performs pairwise semantic similarity, procedural overlap, parameter divergence detection,
    and connected-component clustering across multiple SOP documents.
    """
    logger.info(
        "[Tool:analyze_multi_sop_similarity_tool] Analyzing similarity across %d SOP(s) and %d chunk(s)",
        len(documents),
        len(all_child_chunks),
    )
    return similarity_engine.analyze_collection(documents, all_child_chunks)


@tool("validate_sop_sections_tool", args_schema=ValidateSopSectionsInput)
def validate_sop_sections_tool(
    sections: List[Dict[str, Any]],
    original_text: str = "",
    artifacts: Optional[List[Dict[str, Any]]] = None,
    selected_suggestions: Optional[List[Dict[str, Any]]] = None,
    custom_instructions: str = "",
    is_harmonization: bool = False,
    auto_remediate: bool = True,
) -> Dict[str, Any]:
    """
    Runs the Kenvue QA Validation & Compliance Verification checks on generated SOP sections.
    If auto_remediate=True and any check fails, runs deterministic self-remediation and re-verifies.
    """
    logger.info(
        "[Tool:validate_sop_sections_tool] Validating %d section(s) (is_harmonization=%s, auto_remediate=%s)",
        len(sections),
        is_harmonization,
        auto_remediate,
    )
    current_sections = [dict(s) for s in sections]
    doc_title = "Standard Operating Procedure"
    eval_res = validation_agent.validate_sections(
        sections=current_sections,
        selected_suggestions=selected_suggestions or [],
        custom_instructions=custom_instructions,
        doc_title=doc_title,
    )
    remediated = False
    if not eval_res.get("passed", True) and auto_remediate:
        logger.info("[Tool:validate_sop_sections_tool] Triggering self-remediation loop for failed checks")
        current_sections, doc_title = validation_agent.remediate_sections(
            sections=current_sections,
            missing_suggestions=eval_res.get("missing_suggestions", []),
            missing_custom=eval_res.get("missing_custom", []),
            doc_title=doc_title,
        )
        eval_res = validation_agent.validate_sections(
            sections=current_sections,
            selected_suggestions=selected_suggestions or [],
            custom_instructions=custom_instructions,
            doc_title=doc_title,
        )
        eval_res["self_remediated"] = True
        remediated = True

    return {
        "sections": current_sections,
        "validation_report": eval_res,
        "remediated": remediated,
        "passed": eval_res.get("passed", True),
    }

