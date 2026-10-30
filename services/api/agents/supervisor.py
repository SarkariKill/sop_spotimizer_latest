"""
Supervisor / Orchestrator Agent for the Kenvue Agentic SOP Platform.
Responsible for:
- Inspecting incoming task state and intent
- Selecting the next specialized agent node in the LangGraph workflow
- Handling conditional branching, QA validation/remediation retries, and error recovery
- Recording a structured, auditable decision trace in `state["decisions"]` and `state["agent_trace"]`
"""
import logging
import time
from typing import Any, Dict, List
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

try:
    from prompt_loader import load_prompt
except ImportError:
    from services.api.prompt_loader import load_prompt

logger = logging.getLogger("kenvue_agentic.supervisor")


def get_supervisor_prompt() -> str:
    try:
        return load_prompt("orchestrator_agent")
    except Exception:
        return (
            "You are the Supervisor / Orchestrator Agent for the Kenvue SOP Optimization & RAG Platform. "
            "Coordinate specialized agents across Ingestion, Retrieval, Evaluation, Optimization, and Validation."
        )


class SupervisorAgent:
    """
    Central Orchestrator Agent that governs state transitions across the LangGraph workflow.
    """

    name: str = "SupervisorAgent"
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessage(content=get_supervisor_prompt()),
        ("human", "Task Type: {task_type} | Completed Steps: {completed_steps} | Errors: {errors}"),
    ])

    def route(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates current graph state and determines `next_agent` with full reasoning trace.
        """
        t0 = time.perf_counter()
        task_type = state.get("task_type", "rag_chat")
        completed = list(state.get("completed_steps", []))
        errors = list(state.get("errors", []))
        decisions = list(state.get("decisions", []))
        trace = list(state.get("agent_trace", []))
        retry_count = int(state.get("retry_count", 0))

        next_agent = "final_response"
        reason = "All required workflow stages completed."

        # 1. Check if an error occurred: route to error_recovery once, then to final_response
        if errors:
            if "error_recovery" not in completed:
                next_agent = "error_recovery"
                reason = f"Detected error condition ({errors[-1].get('error_type', 'error')}); routing to ErrorRecoveryNode."
            else:
                next_agent = "final_response"
                reason = "Error recovery completed; routing to FinalResponseNode."

        # 2. Single-SOP Ingestion Pipeline (run per-SOP inside parallel worker threads)
        elif task_type == "sop_single_ingestion":
            if "document_extraction_and_translation" not in completed:
                next_agent = "document_agent"
                reason = "Extract PDF text/tables/images, detect source language, and translate to Canonical English via NLLB-200."
            elif "hierarchical_chunking" not in completed:
                next_agent = "retrieval_agent"
                reason = "Create hierarchical parent/child chunks from Canonical English SOP pages."
            elif "sop_evaluation" not in completed:
                next_agent = "evaluation_agent"
                reason = "Evaluate and score Canonical English SOP against Kenvue 10-tier GMP guidelines."
            else:
                next_agent = "final_response"
                reason = "Per-SOP extraction, translation, chunking, and scoring complete."

        # 3. Collection Indexing & Multi-SOP Similarity Pipeline
        elif task_type == "sop_collection_post_ingest":
            if "faiss_indexing" not in completed and state.get("input_payload", {}).get("child_chunks") is not None:
                next_agent = "retrieval_agent"
                reason = "Index all Canonical English child chunks into FAISS FlatIP vector store."
            elif (
                "similarity_analysis" not in completed
                and len(state.get("documents", [])) > 1
            ):
                next_agent = "evaluation_agent"
                reason = "Multiple SOPs detected; run cross-lingual semantic similarity and clustering analysis."
            else:
                next_agent = "final_response"
                reason = "Collection vector indexing and similarity clustering complete."

        # 4. Standalone Multi-SOP Similarity Analysis
        elif task_type == "similarity_analysis":
            if "similarity_analysis" not in completed:
                next_agent = "evaluation_agent"
                reason = "Compute pairwise semantic similarity, parameter divergences, and harmonization clusters."
            else:
                next_agent = "final_response"
                reason = "Similarity analysis complete."

        # 5. Grounded RAG Chat Pipeline
        elif task_type == "rag_chat":
            if "rag_retrieval_and_generation" not in completed:
                next_agent = "retrieval_agent"
                reason = "Retrieve top-k SOP context from FAISS FlatIP and synthesize grounded assistant response."
            else:
                next_agent = "final_response"
                reason = "RAG retrieval and response generation complete."

        # 6. Single-SOP Optimization Pipeline
        elif task_type == "single_sop_optimization":
            if "sop_optimization" not in completed:
                next_agent = "optimization_agent"
                reason = "Optimize SOP on Canonical English representation and render localized output in target language."
            elif "qa_validation" not in completed:
                next_agent = "validation_agent"
                reason = "Audit optimized SOP sections and verify compliance with Kenvue mandatory standards."
            elif (
                not state.get("validation_report", {}).get("passed", True)
                and retry_count < 1
                and "qa_remediation_retry" not in completed
            ):
                next_agent = "validation_agent"
                reason = "Validation flagged compliance gaps; triggering self-remediation retry loop."
            elif "post_optimization_reindex" not in completed:
                next_agent = "retrieval_agent"
                reason = "Re-index Canonical English optimized SOP sections into FAISS FlatIP vector store."
            else:
                next_agent = "final_response"
                reason = "Single-SOP optimization, QA validation, and FAISS re-indexing complete."

        # 7. Multi-SOP Harmonization, Simplification, and Refinement Pipelines
        elif task_type in {"multi_sop_harmonization", "harmonized_sop_simplify", "harmonized_sop_refine"}:
            if "harmonization_generation" not in completed:
                next_agent = "optimization_agent"
                reason = f"Execute {task_type} on Canonical English sections and localize to selected output language."
            elif "qa_validation" not in completed:
                next_agent = "validation_agent"
                reason = "Verify structural compliance and QA metrics of generated harmonized SOP version."
            else:
                next_agent = "final_response"
                reason = f"Workflow '{task_type}' and QA certification complete."

        # 8. Manual Language Override Pipeline
        elif task_type == "manual_language_override":
            if "manual_translation" not in completed:
                next_agent = "document_agent"
                reason = "Re-translate SOP into Canonical English using user-specified source language."
            else:
                next_agent = "final_response"
                reason = "Manual language override and Canonical English translation complete."

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        decision_entry = {
            "supervisor": self.name,
            "task_type": task_type,
            "selected_agent": next_agent,
            "reason": reason,
            "completed_steps": list(completed),
            "retry_count": retry_count,
            "elapsed_ms": elapsed_ms,
        }
        decisions.append(decision_entry)
        trace.append({
            "node": "supervisor_node",
            "agent": self.name,
            "action": f"route -> {next_agent}",
            "reason": reason,
            "elapsed_ms": elapsed_ms,
        })

        logger.info(
            "[SupervisorAgent] Task='%s' | Step=%d | Next='%s' | Reason: %s",
            task_type,
            len(decisions),
            next_agent,
            reason,
        )

        return {
            "next_agent": next_agent,
            "decisions": decisions,
            "agent_trace": trace,
        }


supervisor_agent = SupervisorAgent()
