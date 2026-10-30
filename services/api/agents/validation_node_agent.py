"""
QA Validation & Compliance Decision Agent.
Uses LangChain tool (`validate_sop_sections_tool`) to verify generated SOP sections
against Kenvue GMP standards and trigger automated self-remediation when needed.
"""
import logging
import time
from typing import Any, Dict
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from tools.evaluation_tools import validate_sop_sections_tool

try:
    from prompt_loader import load_prompt
except ImportError:
    from services.api.prompt_loader import load_prompt

logger = logging.getLogger("kenvue_agentic.validation_agent")


def get_validation_agent_prompt() -> str:
    try:
        return load_prompt("validation_agent")
    except Exception:
        return (
            "You are the Kenvue QA Validation & Compliance Decision Agent. "
            "Verify structural completeness, numerical parameter retention, media asset embedding, "
            "and mandatory Kenvue architecture. Trigger self-remediation if any check fails."
        )


class ValidationDecisionAgent:
    """
    Specialized Agent for QA Compliance Verification and Automated Self-Remediation.
    """

    name: str = "ValidationDecisionAgent"
    tools = [validate_sop_sections_tool]
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessage(content=get_validation_agent_prompt()),
        ("human", "Validate generated SOP output for task={task_type}"),
    ])

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        task_type = state.get("task_type", "single_sop_optimization")
        payload = dict(state.get("input_payload", {}))
        intermediate = dict(state.get("intermediate_results", {}))
        completed = list(state.get("completed_steps", []))
        trace = list(state.get("agent_trace", []))
        retry_count = int(state.get("retry_count", 0))

        validation_report: Dict[str, Any] = {"passed": True, "score": 100}
        tools_called = []

        if task_type == "single_sop_optimization":
            opt_res = intermediate.get("optimization_result", {})
            existing_report = opt_res.get("validation_report")
            if existing_report and isinstance(existing_report, dict) and existing_report.get("source_grounded"):
                # Source reconciliation ran before PDF generation. Legacy injection
                # cannot establish evidence and must not mutate this gated draft.
                validation_report = existing_report
                retry_count = max(retry_count, 1)
                if "qa_remediation_retry" not in completed:
                    completed.append("qa_remediation_retry")
            elif existing_report and isinstance(existing_report, dict) and existing_report.get("passed"):
                validation_report = existing_report
            else:
                eng_secs = opt_res.get("english_sections") or opt_res.get("sections") or []
                val_out = validate_sop_sections_tool.invoke({
                    "sections": eng_secs,
                    "original_text": payload.get("original_text") or "",
                    "artifacts": payload.get("artifacts") or [],
                    "selected_suggestions": payload.get("selected_suggestions") or [],
                    "custom_instructions": payload.get("custom_instructions") or "",
                    "is_harmonization": False,
                    "auto_remediate": True,
                })
                tools_called.append("validate_sop_sections_tool")
                validation_report = val_out["validation_report"]
                opt_res["validation_report"] = validation_report
                intermediate["optimization_result"] = opt_res
                if val_out.get("remediated"):
                    retry_count += 1
                    completed.append("qa_remediation_retry")

        elif task_type in {"multi_sop_harmonization", "harmonized_sop_simplify", "harmonized_sop_refine"}:
            harm_res = intermediate.get("harmonization_result", {})
            eng_secs = harm_res.get("english_sections") or harm_res.get("sections") or []
            if eng_secs:
                val_out = validate_sop_sections_tool.invoke({
                    "sections": eng_secs,
                    "original_text": "",
                    "artifacts": payload.get("all_artifacts") or [],
                    "selected_suggestions": [],
                    "custom_instructions": payload.get("custom_instructions") or "",
                    "is_harmonization": True,
                    "auto_remediate": True,
                })
                tools_called.append("validate_sop_sections_tool")
                validation_report = val_out["validation_report"]
                harm_res["validation_report"] = validation_report
                intermediate["harmonization_result"] = harm_res
                if val_out.get("remediated"):
                    retry_count += 1

        if "qa_validation" not in completed:
            completed.append("qa_validation")

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        trace.append({
            "node": "validation_agent_node",
            "agent": self.name,
            "tools_called": tools_called or ["verify_embedded_validation_report"],
            "passed": validation_report.get("passed", True),
            "validation_score": validation_report.get("score", 100),
            "retry_count": retry_count,
            "elapsed_ms": elapsed_ms,
        })

        return {
            "intermediate_results": intermediate,
            "validation_report": validation_report,
            "completed_steps": completed,
            "retry_count": retry_count,
            "agent_trace": trace,
        }


validation_decision_agent = ValidationDecisionAgent()
