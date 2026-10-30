"""
LangGraph Node Definitions for the Kenvue Agentic SOP Platform.
Each node wraps a specialized Agent (`SupervisorAgent`, `DocumentAnalysisAgent`,
`RetrievalAgent`, `EvaluationAgent`, `OptimizationAndHarmonizationAgent`,
`ValidationDecisionAgent`) plus Error Recovery and Final Response packaging.
"""
import logging
import time
from typing import Any, Dict

from agents import (
    supervisor_agent,
    document_analysis_agent,
    retrieval_agent,
    evaluation_agent,
    optimization_agent,
    validation_decision_agent,
)
from graph.state import SOPAgentState

logger = logging.getLogger("kenvue_agentic.graph_nodes")


def supervisor_node(state: SOPAgentState) -> Dict[str, Any]:
    """Supervisor / Orchestrator node that determines the next specialized agent."""
    return supervisor_agent.route(state)


def document_agent_node(state: SOPAgentState) -> Dict[str, Any]:
    """Document Analysis & Multilingual NLLB Translation node."""
    return document_analysis_agent.execute(state)


def retrieval_agent_node(state: SOPAgentState) -> Dict[str, Any]:
    """Hierarchical Chunking, FAISS FlatIP Indexing, Semantic Search, & RAG Chat node."""
    return retrieval_agent.execute(state)


def evaluation_agent_node(state: SOPAgentState) -> Dict[str, Any]:
    """Kenvue 10-Tier GMP Scoring & Multi-SOP Similarity Analysis node."""
    return evaluation_agent.execute(state)


def optimization_agent_node(state: SOPAgentState) -> Dict[str, Any]:
    """Single-SOP Optimization & Multi-SOP Harmonization/Simplification/Refinement node."""
    return optimization_agent.execute(state)


def validation_agent_node(state: SOPAgentState) -> Dict[str, Any]:
    """QA Validation, Compliance Verification, & Self-Remediation node."""
    return validation_decision_agent.execute(state)


def error_recovery_node(state: SOPAgentState) -> Dict[str, Any]:
    """
    Graceful Error Recovery node.
    Records structured error diagnostics and marks recovery complete so the graph
    can cleanly transition to `final_response_node`.
    """
    t0 = time.perf_counter()
    completed = list(state.get("completed_steps", []))
    errors = list(state.get("errors", []))
    trace = list(state.get("agent_trace", []))
    intermediate = dict(state.get("intermediate_results", {}))

    latest_err = errors[-1] if errors else {"error_type": "unknown_error", "message": "Unknown error"}
    logger.warning(
        "[ErrorRecoveryNode] Handling error '%s' from agent '%s': %s",
        latest_err.get("error_type"),
        latest_err.get("agent", "unknown"),
        latest_err.get("message"),
    )

    intermediate["error_recovered"] = True
    intermediate["latest_error"] = latest_err
    if "error_recovery" not in completed:
        completed.append("error_recovery")

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace.append({
        "node": "error_recovery_node",
        "agent": "ErrorRecoveryAgent",
        "error_type": latest_err.get("error_type"),
        "error_status": latest_err.get("error_status", 500),
        "elapsed_ms": elapsed_ms,
    })

    return {
        "intermediate_results": intermediate,
        "completed_steps": completed,
        "agent_trace": trace,
    }


def final_response_node(state: SOPAgentState) -> Dict[str, Any]:
    """
    Final Response Packaging node.
    Consolidates intermediate outputs, validation reports, decisions, and execution traces
    into `final_result`.
    """
    t0 = time.perf_counter()
    task_type = state.get("task_type", "")
    intermediate = dict(state.get("intermediate_results", {}))
    errors = list(state.get("errors", []))
    decisions = list(state.get("decisions", []))
    trace = list(state.get("agent_trace", []))
    validation_report = dict(state.get("validation_report", {}))

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace.append({
        "node": "final_response_node",
        "agent": "FinalResponseFormatter",
        "task_type": task_type,
        "status": "error" if errors else "success",
        "total_steps": len(trace) + 1,
        "elapsed_ms": elapsed_ms,
    })

    final_result = {
        "status": "error" if errors else "success",
        "task_type": task_type,
        "intermediate_results": intermediate,
        "validation_report": validation_report,
        "errors": errors,
        "decisions": decisions,
        "agent_trace": trace,
    }

    return {
        "final_result": final_result,
        "agent_trace": trace,
    }


def route_from_supervisor(state: SOPAgentState) -> str:
    """Conditional edge function used by LangGraph to branch from `supervisor_node`."""
    next_agent = state.get("next_agent", "final_response")
    valid_targets = {
        "document_agent",
        "retrieval_agent",
        "evaluation_agent",
        "optimization_agent",
        "validation_agent",
        "error_recovery",
        "final_response",
    }
    if next_agent not in valid_targets:
        return "final_response"
    return next_agent
