"""
LangGraph StateGraph Compiler & Orchestration Engine for the Kenvue Agentic SOP Platform.

Architecture:
  START -> supervisor_node
             ├──(conditional)──> document_agent_node ──────┐
             ├──(conditional)──> retrieval_agent_node ─────┤
             ├──(conditional)──> evaluation_agent_node ────┼──> supervisor_node
             ├──(conditional)──> optimization_agent_node ──┤
             ├──(conditional)──> validation_agent_node ────┤
             ├──(conditional)──> error_recovery_node ──────┘
             └──(conditional)──> final_response_node ──> END
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional
from langgraph.graph import StateGraph, START, END

from graph.state import SOPAgentState, create_initial_agent_state
from graph.nodes import (
    supervisor_node,
    document_agent_node,
    retrieval_agent_node,
    evaluation_agent_node,
    optimization_agent_node,
    validation_agent_node,
    error_recovery_node,
    final_response_node,
    route_from_supervisor,
)
from tools import ALL_AGENT_TOOLS

logger = logging.getLogger("kenvue_agentic.workflow")


def build_sop_agent_graph():
    """
    Constructs and compiles the LangGraph StateGraph for all SOP workflows.
    """
    builder = StateGraph(SOPAgentState)

    # 1. Register all specialized agent nodes
    builder.add_node("supervisor_node", supervisor_node)
    builder.add_node("document_agent_node", document_agent_node)
    builder.add_node("retrieval_agent_node", retrieval_agent_node)
    builder.add_node("evaluation_agent_node", evaluation_agent_node)
    builder.add_node("optimization_agent_node", optimization_agent_node)
    builder.add_node("validation_agent_node", validation_agent_node)
    builder.add_node("error_recovery_node", error_recovery_node)
    builder.add_node("final_response_node", final_response_node)

    # 2. Entry edge: START -> supervisor_node
    builder.add_edge(START, "supervisor_node")

    # 3. Conditional edges from supervisor_node to specialized agents
    builder.add_conditional_edges(
        "supervisor_node",
        route_from_supervisor,
        {
            "document_agent": "document_agent_node",
            "retrieval_agent": "retrieval_agent_node",
            "evaluation_agent": "evaluation_agent_node",
            "optimization_agent": "optimization_agent_node",
            "validation_agent": "validation_agent_node",
            "error_recovery": "error_recovery_node",
            "final_response": "final_response_node",
        },
    )

    # 4. Return edges from specialized agents back to supervisor_node for multi-step orchestration
    builder.add_edge("document_agent_node", "supervisor_node")
    builder.add_edge("retrieval_agent_node", "supervisor_node")
    builder.add_edge("evaluation_agent_node", "supervisor_node")
    builder.add_edge("optimization_agent_node", "supervisor_node")
    builder.add_edge("validation_agent_node", "supervisor_node")
    builder.add_edge("error_recovery_node", "supervisor_node")

    # 5. Terminal edge: final_response_node -> END
    builder.add_edge("final_response_node", END)

    return builder.compile()


# Compiled singleton LangGraph workflow (thread-safe for concurrent invocation)
sop_agent_graph = build_sop_agent_graph()


def execute_sop_workflow(
    task_type: str,
    conversation_id: str,
    username: str = "admin",
    input_payload: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> SOPAgentState:
    """
    Synchronously executes the compiled LangGraph `sop_agent_graph` workflow.
    Safe to call directly inside `ThreadPoolExecutor` worker threads.
    """
    initial_state = create_initial_agent_state(
        task_type=task_type,
        conversation_id=conversation_id,
        username=username,
        input_payload=input_payload,
        documents=documents,
    )
    return sop_agent_graph.invoke(initial_state)


async def aexecute_sop_workflow(
    task_type: str,
    conversation_id: str,
    username: str = "admin",
    input_payload: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> SOPAgentState:
    """
    Asynchronously executes the compiled LangGraph `sop_agent_graph` workflow
    in a worker thread so FastAPI's async event loop remains responsive.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        execute_sop_workflow,
        task_type,
        conversation_id,
        username,
        input_payload,
        documents,
    )


def get_graph_architecture_metadata() -> Dict[str, Any]:
    """
    Returns complete introspection metadata about the LangChain + LangGraph
    Agentic Architecture for observability and diagnostics (`GET /agent-graph/info`).
    """
    return {
        "architecture": "LangChain + LangGraph Multi-Agent Orchestration",
        "orchestrator": "SupervisorAgent (StateGraph conditional router)",
        "nodes": [
            "supervisor_node",
            "document_agent_node",
            "retrieval_agent_node",
            "evaluation_agent_node",
            "optimization_agent_node",
            "validation_agent_node",
            "error_recovery_node",
            "final_response_node",
        ],
        "agents": [
            {
                "name": "SupervisorAgent",
                "node": "supervisor_node",
                "responsibility": "Task intent classification, multi-step workflow routing, retry management, and trace logging.",
            },
            {
                "name": "DocumentAnalysisAgent",
                "node": "document_agent_node",
                "responsibility": "Docling-only PDF/DOCX text/table/image extraction, automatic source language detection, and NLLB-200 Canonical English translation.",
            },
            {
                "name": "RetrievalAgent",
                "node": "retrieval_agent_node",
                "responsibility": "Hierarchical parent/child chunking, FAISS FlatIP vector indexing, semantic search, and grounded RAG chat synthesis.",
            },
            {
                "name": "EvaluationAgent",
                "node": "evaluation_agent_node",
                "responsibility": "Kenvue 10-tier GMP scoring and multi-SOP cross-lingual similarity clustering.",
            },
            {
                "name": "OptimizationAndHarmonizationAgent",
                "node": "optimization_agent_node",
                "responsibility": "Single-SOP optimization, multi-SOP harmonization, simplification, and interactive refinement.",
            },
            {
                "name": "ValidationDecisionAgent",
                "node": "validation_agent_node",
                "responsibility": "Post-generation QA compliance verification and automated self-remediation loop.",
            },
        ],
        "registered_tools": [
            {
                "name": t.name,
                "description": (t.description or "").strip(),
            }
            for t in ALL_AGENT_TOOLS
        ],
        "supported_task_types": [
            "sop_single_ingestion",
            "sop_collection_post_ingest",
            "similarity_analysis",
            "rag_chat",
            "single_sop_optimization",
            "multi_sop_harmonization",
            "harmonized_sop_simplify",
            "harmonized_sop_refine",
            "manual_language_override",
        ],
    }
