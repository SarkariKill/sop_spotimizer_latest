"""
Document Analysis & Multilingual Translation Agent.
Uses LangChain tools (`detect_sop_language_tool`, `translate_pages_to_english_tool`,
`translate_sop_to_english_tool`) and `invoke_extract_sop_pdf` to extract PDF content,
detect source language, and translate non-English SOPs into Canonical English via NLLB-200.
"""
import logging
import time
from typing import Any, Dict, List
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from tools.document_tools import (
    detect_sop_language_tool,
    translate_sop_to_english_tool,
    translate_pages_to_english_tool,
    translate_sop_sections_from_english_tool,
    invoke_extract_sop_pdf,
)

try:
    from prompt_loader import load_prompt
except ImportError:
    from services.api.prompt_loader import load_prompt

logger = logging.getLogger("kenvue_agentic.document_agent")


def get_document_agent_prompt() -> str:
    try:
        return load_prompt("document_agent")
    except Exception:
        return (
            "You are the Document Analysis & Multilingual NLLB Translation Agent. "
            "Extract text, tables, and vector/raster figures from SOP PDFs, detect the source language, "
            "and normalize non-English SOPs into Canonical English while preserving the original SOP."
        )


class DocumentAnalysisAgent:
    """
    Specialized Agent for PDF Extraction, Language Detection, and NLLB-200 Canonical English Translation.
    """

    name: str = "DocumentAnalysisAgent"
    tools = [
        detect_sop_language_tool,
        translate_sop_to_english_tool,
        translate_pages_to_english_tool,
        translate_sop_sections_from_english_tool,
    ]
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessage(content=get_document_agent_prompt()),
        ("human", "Process SOP document: {filename} (task={task_type})"),
    ])

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        task_type = state.get("task_type", "sop_single_ingestion")
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

        # Case A: Manual Language Override
        if task_type == "manual_language_override":
            raw_text = payload.get("raw_text", "")
            source_lang = payload.get("source_language", "English")
            try:
                trans_res = translate_sop_to_english_tool.invoke({
                    "text": raw_text,
                    "source_language": source_lang,
                    "llm_service_url": llm_service_url,
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                })
            except Exception as exc:
                logger.error("[%s] Manual language translation failed: %s", self.name, exc)
                errors.append({
                    "agent": self.name,
                    "error_type": "llm_unavailable",
                    "error_status": getattr(exc, "status_code", 503),
                    "message": str(exc),
                })
                return {
                    "errors": errors,
                    "intermediate_results": intermediate,
                    "completed_steps": completed,
                    "agent_trace": trace,
                }
            intermediate["english_canonical_text"] = trans_res["english_text"]
            intermediate["translation_metadata"] = trans_res["translation_metadata"]
            completed.append("manual_translation")
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            trace.append({
                "node": "document_agent_node",
                "agent": self.name,
                "tools_called": ["translate_sop_to_english_tool"],
                "source_language": source_lang,
                "elapsed_ms": elapsed_ms,
            })
            return {
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "agent_trace": trace,
            }

        # Case B: Standard Single-SOP Ingestion
        filename = payload.get("filename", "SOP.pdf")
        file_bytes = payload.get("file_bytes", b"")
        scoped_conv_prefix = payload.get("scoped_conv_prefix", "")

        try:
            pages_data, artifacts_data, stats = invoke_extract_sop_pdf(
                file_bytes=file_bytes,
                conversation_id=scoped_conv_prefix,
                filename=filename,
                document_id=payload.get("doc_id"),
            )
        except Exception as exc:
            logger.error("[%s] PDF extraction failed for '%s': %s", self.name, filename, exc)
            errors.append({
                "agent": self.name,
                "error_type": "extraction_failed",
                "error_status": getattr(exc, "status_code", 400),
                "message": str(exc),
                "filename": filename,
                "artifacts_data": getattr(exc, "artifacts_data", []),
            })
            return {
                "errors": errors,
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "agent_trace": trace,
            }

        raw_extracted_text = "\n\n".join([p["text"] for p in pages_data if p.get("text")])

        # Invoke LangChain @tool: detect_sop_language_tool
        lang_info = detect_sop_language_tool.invoke({
            "text": raw_extracted_text,
            "filename": filename,
        })

        if not lang_info.get("is_supported", True):
            err_msg = (
                lang_info.get("error")
                or f"Language detected in '{filename}' is not supported by the configured NLLB model."
            )
            errors.append({
                "agent": self.name,
                "error_type": "unsupported_language",
                "error_status": 400,
                "message": err_msg,
                "filename": filename,
                "artifacts_data": artifacts_data,
            })
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            trace.append({
                "node": "document_agent_node",
                "agent": self.name,
                "tools_called": ["docling_extract_document", "detect_sop_language_tool"],
                "filename": filename,
                "error": "unsupported_language",
                "elapsed_ms": elapsed_ms,
            })
            return {
                "errors": errors,
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "agent_trace": trace,
            }

        detected_lang = lang_info["detected_language"]
        nllb_code = lang_info["nllb_code"]
        lang_conf = lang_info.get("confidence", 0.95)

        # Invoke LangChain @tool: translate_pages_to_english_tool
        try:
            trans_res = translate_pages_to_english_tool.invoke({
                "pages_data": pages_data,
                "source_language": detected_lang,
                "llm_service_url": llm_service_url,
                "provider": provider,
                "model": model,
                "api_key": api_key,
            })
        except Exception as exc:
            logger.error("[%s] Canonical translation failed for '%s': %s", self.name, filename, exc)
            errors.append({
                "agent": self.name,
                "error_type": "llm_unavailable",
                "error_status": getattr(exc, "status_code", 503),
                "message": str(exc),
                "filename": filename,
                "artifacts_data": artifacts_data,
            })
            return {
                "errors": errors,
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "agent_trace": trace,
            }
        english_pages_data = trans_res["english_pages"]
        trans_meta = trans_res["translation_metadata"]
        english_canonical_text = "\n\n".join([p["text"] for p in english_pages_data if p.get("text")])

        intermediate.update({
            "pages_data": pages_data,
            "artifacts_data": artifacts_data,
            "stats": stats,
            "raw_extracted_text": raw_extracted_text,
            "lang_info": lang_info,
            "detected_language": detected_lang,
            "nllb_code": nllb_code,
            "language_confidence": lang_conf,
            "english_pages_data": english_pages_data,
            "english_canonical_text": english_canonical_text,
            "translation_metadata": trans_meta,
        })
        # Persist evidence beside source assets without a new database/schema.
        import json
        from minio_storage import minio_storage
        from source_grounding import inventory_from_pages, attach_structure
        inventory = inventory_from_pages(english_pages_data, payload.get("doc_id"), filename,
                                         artifacts_data, stats.get("extraction_status", "complete"))
        inventory["source_language"] = detected_lang
        inventory["extraction_warnings"] = stats.get("extraction_warnings", [])
        attach_structure(inventory, stats.get("structural_elements", []))
        for page in english_pages_data:
            page["source_elements"] = [e for e in inventory["elements"] if e["page"] == page["page"]]
        if detected_lang != "English":
            inventory["extraction_status"] = "translated_source_requires_review"
        if not minio_storage.upload_file_bytes(
            f"{scoped_conv_prefix}/extraction/{payload.get('doc_id')}.json",
            json.dumps(inventory, ensure_ascii=False).encode("utf-8"), "application/json"):
            errors.append({"agent": self.name, "error_type": "evidence_persistence_failed", "error_status": 500,
                           "message": "Could not persist source evidence inventory", "artifacts_data": artifacts_data})
            return {"errors": errors, "intermediate_results": intermediate,
                    "completed_steps": completed, "agent_trace": trace}
        completed.append("document_extraction_and_translation")

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        trace.append({
            "node": "document_agent_node",
            "agent": self.name,
            "tools_called": [
                "docling_extract_document",
                "detect_sop_language_tool",
                "translate_pages_to_english_tool",
            ],
            "filename": filename,
            "detected_language": detected_lang,
            "translation_status": trans_meta.get("translation_status"),
            "extraction_engine": stats.get("extraction_engine"),
            "extraction_status": stats.get("extraction_status"),
            "extraction_warnings": stats.get("extraction_warnings", []),
            "elapsed_ms": elapsed_ms,
        })

        logger.info(
            "[%s] Processed '%s' (lang=%s, pages=%d, status=%s) in %.1f ms",
            self.name,
            filename,
            detected_lang,
            stats.get("page_count", 0),
            trans_meta.get("translation_status"),
            elapsed_ms,
        )

        return {
            "intermediate_results": intermediate,
            "completed_steps": completed,
            "agent_trace": trace,
        }


document_analysis_agent = DocumentAnalysisAgent()
