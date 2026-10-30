"""
Optimization, Harmonization, Simplification, & Refinement Agent.
Uses LangChain tools (`generate_optimized_sop_tool`, `harmonize_sops_tool`,
`simplify_harmonized_sop_tool`, `refine_harmonized_sop_tool`) to execute all
Canonical English SOP synthesis and NLLB-200 target language rendering.
"""
import logging
import time
from typing import Any, Dict
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from tools.generation_tools import (
    generate_optimized_sop_tool,
    harmonize_sops_tool,
    simplify_harmonized_sop_tool,
    refine_harmonized_sop_tool,
)

try:
    from prompt_loader import load_prompt
except ImportError:
    from services.api.prompt_loader import load_prompt

logger = logging.getLogger("kenvue_agentic.optimization_agent")


def get_optimization_agent_prompt() -> str:
    try:
        return load_prompt("harmonization_agent")
    except Exception:
        return (
            "You are the Kenvue SOP Optimization & Harmonization Agent. "
            "Operate on Canonical English representations, preserve 100% of safety limits, numerical tolerances, "
            "and extracted media artifacts, and localize outputs into the target language via NLLB-200."
        )


class OptimizationAndHarmonizationAgent:
    """
    Specialized Agent for Single-SOP Optimization, Multi-SOP Harmonization,
    Simplification, and Interactive Version Refinement.
    """

    name: str = "OptimizationAndHarmonizationAgent"
    tools = [
        generate_optimized_sop_tool,
        harmonize_sops_tool,
        simplify_harmonized_sop_tool,
        refine_harmonized_sop_tool,
    ]
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessage(content=get_optimization_agent_prompt()),
        ("human", "Execute generation task: {task_type} (output_language={output_language})"),
    ])

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        task_type = state.get("task_type", "single_sop_optimization")
        conversation_id = state.get("conversation_id", "")
        username = state.get("username", "admin")
        payload = dict(state.get("input_payload", {}))
        intermediate = dict(state.get("intermediate_results", {}))
        completed = list(state.get("completed_steps", []))
        errors = list(state.get("errors", []))
        trace = list(state.get("agent_trace", []))

        llm_cfg = payload.get("llm_config", {})
        llm_service_url = llm_cfg.get("llm_service_url", "http://localhost:8001")
        provider = llm_cfg.get("provider", "groq")
        model = llm_cfg.get("model", "openai/gpt-oss-120b")
        api_key = llm_cfg.get("api_key", "")

        try:
            # 1. Single-SOP Optimization
            if task_type == "single_sop_optimization":
                opt_res = generate_optimized_sop_tool.invoke({
                    "conversation_id": conversation_id,
                    "username": username,
                    "original_text": payload.get("original_text") or "",
                    "original_filename": payload.get("original_filename") or "SOP.pdf",
                    "selected_suggestions": payload.get("selected_suggestions") or [],
                    "custom_instructions": payload.get("custom_instructions") or "",
                    "artifacts": payload.get("artifacts") or [],
                    "llm_service_url": llm_service_url,
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                    "existing_sections": payload.get("existing_sections"),
                    "existing_title": payload.get("existing_title"),
                    "output_language": payload.get("output_language") or "English",
                    "previous_scores": payload.get("previous_scores"),
                    "document_id": payload.get("document_id") or payload.get("doc_id"),
                })
                intermediate["optimization_result"] = opt_res
                completed.append("sop_optimization")
                tool_name = "generate_optimized_sop_tool"
                out_lang = opt_res.get("output_language", payload.get("output_language") or "English")

            # 2. Multi-SOP Harmonization
            elif task_type == "multi_sop_harmonization":
                harm_res = harmonize_sops_tool.invoke({
                    "conversation_id": conversation_id,
                    "username": username,
                    "source_documents": payload.get("source_documents") or [],
                    "custom_instructions": payload.get("custom_instructions") or "",
                    "title_override": payload.get("title_override"),
                    "all_artifacts": payload.get("all_artifacts") or [],
                    "llm_service_url": llm_service_url,
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                    "output_language": payload.get("output_language") or "English",
                })
                intermediate["harmonization_result"] = harm_res
                completed.append("harmonization_generation")
                tool_name = "harmonize_sops_tool"
                out_lang = harm_res.get("output_language", payload.get("output_language") or "English")

            # 3. Harmonized SOP Simplification
            elif task_type == "harmonized_sop_simplify":
                simp_res = simplify_harmonized_sop_tool.invoke({
                    "current_version": payload.get("current_version") or {},
                    "selected_recommendation_ids": payload.get("selected_recommendation_ids") or [],
                    "custom_instructions": payload.get("custom_instructions") or "",
                    "conversation_id": conversation_id,
                    "username": username,
                    "all_artifacts": payload.get("all_artifacts") or [],
                    "output_language": payload.get("output_language") or "English",
                    "llm_service_url": llm_service_url,
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                })
                intermediate["harmonization_result"] = simp_res
                completed.append("harmonization_generation")
                tool_name = "simplify_harmonized_sop_tool"
                out_lang = simp_res.get("output_language", payload.get("output_language") or "English")

            # 4. Harmonized SOP Interactive Refinement
            else:
                ref_res = refine_harmonized_sop_tool.invoke({
                    "current_version": payload.get("current_version") or {},
                    "refinement_prompt": payload.get("refinement_prompt") or "",
                    "conversation_id": conversation_id,
                    "username": username,
                    "all_artifacts": payload.get("all_artifacts") or [],
                    "output_language": payload.get("output_language") or "English",
                    "llm_service_url": llm_service_url,
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                })
                intermediate["harmonization_result"] = ref_res
                completed.append("harmonization_generation")
                tool_name = "refine_harmonized_sop_tool"
                out_lang = ref_res.get("output_language", payload.get("output_language") or "English")

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            trace.append({
                "node": "optimization_agent_node",
                "agent": self.name,
                "tools_called": [tool_name],
                "output_language": out_lang,
                "elapsed_ms": elapsed_ms,
            })

        except Exception as exc:
            logger.exception("[%s] Task '%s' failed: %s", self.name, task_type, exc)
            errors.append({
                "agent": self.name,
                "error_type": "llm_unavailable" if getattr(exc, "status_code", 500) == 503 else f"{task_type}_failed",
                "error_status": getattr(exc, "status_code", 503),
                "message": str(exc),
            })

        return {
            "intermediate_results": intermediate,
            "completed_steps": completed,
            "errors": errors,
            "agent_trace": trace,
        }


optimization_agent = OptimizationAndHarmonizationAgent()
