"""
LangGraph TypedDict State Schema for the Kenvue Agentic SOP Platform.
Tracks input requests, extracted documents, RAG context, intermediate outputs,
supervisor routing decisions, validation status, retry counters, errors,
and the final response.
"""
from typing import Any, Dict, List, Optional, TypedDict


class SOPAgentState(TypedDict, total=False):
    task_type: str
    conversation_id: str
    username: str
    input_payload: Dict[str, Any]
    documents: List[Dict[str, Any]]
    context: Dict[str, Any]
    intermediate_results: Dict[str, Any]
    completed_steps: List[str]
    next_agent: str
    decisions: List[Dict[str, Any]]
    agent_trace: List[Dict[str, Any]]
    validation_report: Dict[str, Any]
    retry_count: int
    errors: List[Dict[str, Any]]
    final_result: Dict[str, Any]


def create_initial_agent_state(
    task_type: str,
    conversation_id: str,
    username: str = "admin",
    input_payload: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> SOPAgentState:
    """Creates a clean initial SOPAgentState for LangGraph execution."""
    return {
        "task_type": task_type,
        "conversation_id": conversation_id,
        "username": username,
        "input_payload": input_payload or {},
        "documents": documents or [],
        "context": {},
        "intermediate_results": {},
        "completed_steps": [],
        "next_agent": "supervisor",
        "decisions": [],
        "agent_trace": [],
        "validation_report": {},
        "retry_count": 0,
        "errors": [],
        "final_result": {},
    }
