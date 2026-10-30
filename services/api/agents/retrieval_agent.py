"""
Retrieval & Vector Indexing Agent.
Uses LangChain tools (`create_hierarchical_chunks_tool`, `faiss_index_chunks_tool`,
`faiss_search_context_tool`, `get_guidelines_context_tool`) and `KenvueMicroserviceChatModel`
to manage hierarchical chunking, FAISS FlatIP vector indexing, semantic retrieval,
and grounded RAG chat generation.
"""
import logging
import re
import time
from typing import Any, Dict, List
import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from agents.llm_wrapper import KenvueMicroserviceChatModel
from tools.retrieval_tools import (
    create_hierarchical_chunks_tool,
    faiss_index_chunks_tool,
    faiss_search_context_tool,
    get_guidelines_context_tool,
)

try:
    from prompt_loader import load_prompt, format_prompt
except ImportError:
    from services.api.prompt_loader import load_prompt, format_prompt

logger = logging.getLogger("kenvue_agentic.retrieval_agent")


def get_retrieval_agent_prompt() -> str:
    try:
        return load_prompt("rag_chat_agent")
    except Exception:
        return "You are the FAISS FlatIP Retrieval & RAG Synthesis Agent for Standard Operating Procedures."


class RetrievalAgent:
    """
    Specialized Agent for Hierarchical Chunking, FAISS FlatIP Indexing, Semantic Search, and RAG Chat.
    """

    name: str = "RetrievalAgent"
    tools = [
        create_hierarchical_chunks_tool,
        faiss_index_chunks_tool,
        faiss_search_context_tool,
        get_guidelines_context_tool,
    ]
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessage(content=get_retrieval_agent_prompt()),
        ("human", "{query}"),
    ])

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        task_type = state.get("task_type", "rag_chat")
        conversation_id = state.get("conversation_id", "")
        payload = dict(state.get("input_payload", {}))
        intermediate = dict(state.get("intermediate_results", {}))
        context = dict(state.get("context", {}))
        completed = list(state.get("completed_steps", []))
        errors = list(state.get("errors", []))
        trace = list(state.get("agent_trace", []))

        # Case 1: Per-SOP Hierarchical Chunking during single-SOP ingestion
        if task_type == "sop_single_ingestion":
            english_pages = intermediate.get("english_pages_data", [])
            doc_id = payload.get("doc_id", "")
            filename = payload.get("filename", "SOP.pdf")

            chunk_res = create_hierarchical_chunks_tool.invoke({
                "pages_data": english_pages,
                "document_id": doc_id,
                "filename": filename,
                "artifacts_data": intermediate.get("artifacts_data") or [],
            })
            intermediate["parent_chunks"] = chunk_res["parent_chunks"]
            intermediate["child_chunks"] = chunk_res["child_chunks"]
            completed.append("hierarchical_chunking")

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            trace.append({
                "node": "retrieval_agent_node",
                "agent": self.name,
                "tools_called": ["create_hierarchical_chunks_tool"],
                "child_chunks_count": chunk_res["child_count"],
                "elapsed_ms": elapsed_ms,
            })
            return {
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "agent_trace": trace,
            }

        # Case 2: Collection FAISS FlatIP Indexing after parallel SOP upload
        if task_type == "sop_collection_post_ingest":
            child_chunks = payload.get("child_chunks", [])
            try:
                idx_res = faiss_index_chunks_tool.invoke({
                    "conversation_id": conversation_id,
                    "child_chunks": child_chunks,
                    "incremental": True,
                })
                intermediate["faiss_index_result"] = idx_res
                completed.append("faiss_indexing")
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                trace.append({
                    "node": "retrieval_agent_node",
                    "agent": self.name,
                    "tools_called": ["faiss_index_chunks_tool"],
                    "total_vectors": idx_res.get("total_vectors", 0),
                    "elapsed_ms": elapsed_ms,
                })
            except Exception as exc:
                logger.error("[%s] FAISS FlatIP indexing failed: %s", self.name, exc)
                errors.append({
                    "agent": self.name,
                    "error_type": "faiss_index_failed",
                    "error_status": 500,
                    "message": f"Failed creating FAISS FlatIP vector index: {exc}",
                })
            return {
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "errors": errors,
                "agent_trace": trace,
            }

        # Case 3: Post-Optimization FAISS FlatIP Re-indexing
        if task_type == "single_sop_optimization":
            opt_res = intermediate.get("optimization_result", {})
            if opt_res.get("validation_report", {}).get("source_grounded"):
                # Source text is still authoritative. Re-indexing draft headings
                # as page numbers fabricates citations and indexes placeholders.
                completed.append("post_optimization_reindex")
                trace.append({"node": "retrieval_agent_node", "agent": self.name,
                              "action": "retain_source_index", "reason": "Preserve original page provenance for grounded draft"})
                return {"intermediate_results": intermediate, "completed_steps": completed,
                        "errors": errors, "agent_trace": trace}
            eng_secs = opt_res.get("english_sections") or opt_res.get("sections") or []
            doc_id = payload.get("doc_id", "")
            filename = payload.get("filename", "SOP.pdf")

            opt_pages_data = [
                {"page": idx + 1, "text": f"{s.get('heading', '')}\n\n{s.get('content', '')}"}
                for idx, s in enumerate(eng_secs)
                if s.get("content")
            ]
            tools_called: List[str] = []
            reindexed_chunks = 0
            if opt_pages_data:
                try:
                    chunk_res = create_hierarchical_chunks_tool.invoke({
                        "pages_data": opt_pages_data,
                        "document_id": doc_id,
                        "filename": filename,
                    })
                    tools_called.append("create_hierarchical_chunks_tool")
                    from rag_engine import get_vector_store
                    vector_store = get_vector_store(conversation_id)
                    retained = [c for c in vector_store.child_chunks if c.get("document_id") != doc_id]
                    idx_res = faiss_index_chunks_tool.invoke({
                        "conversation_id": conversation_id,
                        "child_chunks": retained + chunk_res["child_chunks"],
                        "incremental": False,
                    })
                    tools_called.append("faiss_index_chunks_tool")
                    reindexed_chunks = idx_res.get("indexed_chunks", 0)
                    intermediate["reindex_result"] = idx_res
                except Exception as exc:
                    logger.warning("[%s] Non-fatal error re-indexing optimized SOP: %s", self.name, exc)

            completed.append("post_optimization_reindex")
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            trace.append({
                "node": "retrieval_agent_node",
                "agent": self.name,
                "tools_called": tools_called,
                "reindexed_chunks": reindexed_chunks,
                "elapsed_ms": elapsed_ms,
            })
            return {
                "intermediate_results": intermediate,
                "completed_steps": completed,
                "agent_trace": trace,
            }

        # Case 4: Grounded RAG Chat Retrieval + LangChain ChatModel Synthesis
        query = payload.get("query", "")
        history = payload.get("history", [])
        llm_cfg = payload.get("llm_config", {})

        search_res = faiss_search_context_tool.invoke({
            "conversation_id": conversation_id,
            "query": query,
            "top_k": 6,
        })
        rag_context_blocks = search_res["rag_context_blocks"]
        referenced_pages = search_res["referenced_pages"]
        rag_applied = search_res["rag_applied"]

        context["rag_context_blocks"] = rag_context_blocks
        context["referenced_pages"] = referenced_pages
        context["rag_applied"] = rag_applied

        lc_messages: List[BaseMessage] = []
        if rag_context_blocks:
            system_instruction = format_prompt(
                "rag_chat_agent",
                rag_context="\n\n".join(rag_context_blocks),
            )
            lc_messages.append(SystemMessage(content=system_instruction))

        for msg in history:
            role = msg.get("role", "user")
            content_str = msg.get("content", "")
            if role == "assistant":
                lc_messages.append(AIMessage(content=content_str))
            elif role == "system":
                lc_messages.append(SystemMessage(content=content_str))
            else:
                lc_messages.append(HumanMessage(content=content_str))

        chat_model = KenvueMicroserviceChatModel(
            llm_service_url=llm_cfg.get("llm_service_url", "http://localhost:8001"),
            provider=llm_cfg.get("provider", "groq"),
            model=llm_cfg.get("model", "openai/gpt-oss-120b"),
            api_key=llm_cfg.get("api_key", ""),
            timeout=90.0,
        ).bind_tools(self.tools)

        try:
            ai_msg = chat_model.invoke(lc_messages)
            answer = str(ai_msg.content)
            answer = re.sub(r"【(?:Document:\s*([^,】]+),\s*)?Page[\s\u202f]*(\d+)】", r"[Document: \1, Page \2]", answer)
            answer = re.sub(r"【Page[\s\u202f]*(\d+)】", r"[Page \1]", answer)
            answer = re.sub(r"[\u202f\u00a0\u200b]", " ", answer)
            intermediate["chat_response"] = {
                "role": "assistant",
                "content": answer,
                "rag_applied": rag_applied,
                "referenced_pages": referenced_pages,
            }
            completed.append("rag_retrieval_and_generation")
        except httpx.RequestError as exc:
            try:
                from sop_evaluator import format_llm_unavailable_message
            except ImportError:
                from services.api.sop_evaluator import format_llm_unavailable_message
            errors.append({
                "agent": self.name,
                "error_type": "llm_unavailable",
                "error_status": 503,
                "message": format_llm_unavailable_message(
                    provider=llm_cfg.get("provider", "groq"),
                    detail=str(exc),
                ),
            })
        except RuntimeError as exc:
            try:
                from sop_evaluator import format_llm_unavailable_message
            except ImportError:
                from services.api.sop_evaluator import format_llm_unavailable_message
            err_str = str(exc)
            status_code = 503
            detail = err_str
            if err_str.startswith("LLM_HTTP_"):
                parts = err_str.split(":", 1)
                try:
                    status_code = int(parts[0].replace("LLM_HTTP_", ""))
                except ValueError:
                    status_code = 503
                detail = parts[1] if len(parts) > 1 else err_str
            errors.append({
                "agent": self.name,
                "error_type": "llm_unavailable",
                "error_status": 503,
                "message": format_llm_unavailable_message(
                    provider=llm_cfg.get("provider", "groq"),
                    status_code=status_code,
                    detail=detail,
                ),
            })
        except Exception as exc:
            try:
                from sop_evaluator import format_llm_unavailable_message
            except ImportError:
                from services.api.sop_evaluator import format_llm_unavailable_message
            errors.append({
                "agent": self.name,
                "error_type": "llm_unavailable",
                "error_status": 503,
                "message": format_llm_unavailable_message(
                    provider=llm_cfg.get("provider", "groq"),
                    detail=str(exc),
                ),
            })

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        trace.append({
            "node": "retrieval_agent_node",
            "agent": self.name,
            "tools_called": ["faiss_search_context_tool", "KenvueMicroserviceChatModel.invoke"],
            "rag_applied": rag_applied,
            "referenced_pages": referenced_pages,
            "elapsed_ms": elapsed_ms,
        })

        return {
            "context": context,
            "intermediate_results": intermediate,
            "completed_steps": completed,
            "errors": errors,
            "agent_trace": trace,
        }


retrieval_agent = RetrievalAgent()
