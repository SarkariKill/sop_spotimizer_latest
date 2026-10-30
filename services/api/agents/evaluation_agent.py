"""
Evaluation & Multi-SOP Similarity Agent.
Uses LangChain tools (`evaluate_sop_tool`, `analyze_multi_sop_similarity_tool`)
to audit single SOPs against the Kenvue 10-Tier GMP Rubric and compute cross-lingual
semantic similarity, parameter divergences, and connected-component clusters across SOP collections.
"""
import logging
import time
from typing import Any, Dict, List
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from tools.evaluation_tools import (
    evaluate_sop_tool,
    analyze_multi_sop_similarity_tool,
)

try:
    from prompt_loader import load_prompt
except ImportError:
    from services.api.prompt_loader import load_prompt

logger = logging.getLogger("kenvue_agentic.evaluation_agent")


def get_evaluation_agent_prompt() -> str:
    try:
        return load_prompt("scoring_agent")
    except Exception:
        return (
            "You are the Kenvue GMP Audit & Multi-SOP Similarity Evaluation Agent. "
            "Score Canonical English SOPs across Template Compliance, Readability, and Quality, "
            "and detect cross-document overlaps and parameter divergences."
        )


def get_similarity_agent_prompt() -> str:
    try:
        return load_prompt("similarity_agent")
    except Exception:
        return (
            "You are the Kenvue SOP Comparison & Similarity Assessment Agent. "
            "Evaluate operational meaning over text matching, compute weighted section similarities, "
            "and detect parameter divergences."
        )


class EvaluationAgent:
    """
    Specialized Agent for Kenvue 10-Tier SOP Scoring and Multi-SOP Semantic Similarity Analysis.
    """

    name: str = "EvaluationAgent"
    tools = [
        evaluate_sop_tool,
        analyze_multi_sop_similarity_tool,
    ]
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessage(content=get_evaluation_agent_prompt()),
        ("human", "Evaluate SOP task: {task_type}"),
    ])
    similarity_prompt_template = ChatPromptTemplate.from_messages([
        SystemMessage(content=get_similarity_agent_prompt()),
        ("human", "Analyze similarity and cluster SOP collection: {task_type}"),
    ])

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        task_type = state.get("task_type", "sop_single_ingestion")
        payload = dict(state.get("input_payload", {}))
        intermediate = dict(state.get("intermediate_results", {}))
        documents = list(state.get("documents", []))
        completed = list(state.get("completed_steps", []))
        trace = list(state.get("agent_trace", []))

        errors = list(state.get("errors", []))

        # Case 1: Single-SOP Evaluation during upload ingestion
        if task_type == "sop_single_ingestion":
            llm_cfg = payload.get("llm_config", {})
            eng_canon_text = intermediate.get("english_canonical_text", "")
            compact_mode = bool(payload.get("compact_mode", False))

            try:
                evaluation = evaluate_sop_tool.invoke({
                    "sop_text": eng_canon_text,
                    "llm_service_url": llm_cfg.get("llm_service_url", "http://localhost:8001"),
                    "provider": llm_cfg.get("provider", "groq"),
                    "model": llm_cfg.get("model", "openai/gpt-oss-120b"),
                    "api_key": llm_cfg.get("api_key", ""),
                    "compact_mode": compact_mode,
                })
            except Exception as exc:
                logger.error("[%s] SOP evaluation failed: %s", self.name, exc)
                errors.append({
                    "agent": self.name,
                    "error_type": "llm_unavailable",
                    "error_status": getattr(exc, "status_code", 503),
                    "message": str(exc),
                    "filename": payload.get("filename", "SOP.pdf"),
                    "artifacts_data": intermediate.get("artifacts_data", []),
                })
                return {
                    "errors": errors,
                    "intermediate_results": intermediate,
                    "completed_steps": completed,
                    "agent_trace": trace,
                }
            intermediate["evaluation"] = evaluation
            completed.append("sop_evaluation")

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            trace.append({
                "node": "evaluation_agent_node",
                "agent": self.name,
                "tools_called": ["evaluate_sop_tool"],
                "average_score": evaluation.get("average_score"),
                "compact_mode": compact_mode,
                "elapsed_ms": elapsed_ms,
            })
            return {
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "agent_trace": trace,
            }

        # Case 2: Multi-SOP Semantic Similarity & Clustering Analysis
        all_child_chunks = payload.get("all_child_chunks") or payload.get("child_chunks") or []
        unique_detected_languages = payload.get("unique_detected_languages", [])
        detected_lang_names = [l["language"] for l in unique_detected_languages]

        sim_analysis = analyze_multi_sop_similarity_tool.invoke({
            "documents": documents,
            "all_child_chunks": all_child_chunks,
        })
        if isinstance(sim_analysis, dict) and unique_detected_languages:
            sim_analysis["detected_languages"] = unique_detected_languages
            sim_analysis["available_output_languages"] = detected_lang_names
            sim_analysis["internal_processing_language"] = "English"

        intermediate["similarity_analysis"] = sim_analysis
        completed.append("similarity_analysis")

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        trace.append({
            "node": "evaluation_agent_node",
            "agent": self.name,
            "tools_called": ["analyze_multi_sop_similarity_tool"],
            "documents_analyzed": len(documents),
            "clusters_found": len(sim_analysis.get("groups", [])) if isinstance(sim_analysis, dict) else 0,
            "elapsed_ms": elapsed_ms,
        })

        return {
            "intermediate_results": intermediate,
            "completed_steps": completed,
            "agent_trace": trace,
        }


evaluation_agent = EvaluationAgent()
