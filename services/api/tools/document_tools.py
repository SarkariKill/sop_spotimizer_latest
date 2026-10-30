"""
LangChain Tool Wrappers for SOP Document Extraction, Language Detection, and NLLB-200 Translation.
Wraps Docling-only ingestion and existing translation functions
without altering their core business logic.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from document_ingestion import extract_document
from nllb_translator import (
    detect_sop_language,
    translate_sop_to_english,
    translate_pages_to_english,
    translate_sop_sections_from_english,
    get_unique_detected_languages,
)

logger = logging.getLogger("kenvue_agentic_tools.document")


def _run_coro_sync(coro):
    """Safely executes an async coroutine from either synchronous or threaded contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class ExtractSopPdfInput(BaseModel):
    conversation_id: str = Field(..., description="Scoped conversation storage prefix")
    filename: str = Field(..., description="Original PDF filename")


class DetectLanguageInput(BaseModel):
    text: str = Field(..., description="Extracted text from the SOP document")
    filename: str = Field(default="", description="Filename for tie-breaking heuristics")


class TranslateTextToEnglishInput(BaseModel):
    text: str = Field(..., description="Source SOP text in original language")
    source_language: str = Field(..., description="Detected source language name (e.g., 'Japanese', 'Chinese')")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")


class TranslatePagesToEnglishInput(BaseModel):
    pages_data: List[Dict[str, Any]] = Field(..., description="List of extracted page dicts with 'page' and 'text'")
    source_language: str = Field(..., description="Detected source language name")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")


class TranslateSectionsFromEnglishInput(BaseModel):
    sections: List[Dict[str, Any]] = Field(..., description="List of canonical English SOP sections ({'heading', 'content', ...})")
    target_language: str = Field(..., description="Desired target output language")
    llm_service_url: str = Field(default="http://localhost:8001", description="Local LLM microservice base URL")
    provider: str = Field(default="azure_openai", description="Azure OpenAI LLM provider")
    model: str = Field(default="openai/gpt-oss-120b", description="LLM model identifier")
    api_key: str = Field(default="", description="Admin-configured LLM API key")


@tool("detect_sop_language_tool", args_schema=DetectLanguageInput)
def detect_sop_language_tool(text: str, filename: str = "") -> Dict[str, Any]:
    """
    Detects the primary language of an uploaded SOP document and returns its NLLB-200
    language code, ISO code, confidence score, and support status.
    """
    logger.info("[Tool:detect_sop_language_tool] Invoked for filename='%s'", filename)
    return detect_sop_language(text=text, filename=filename)


@tool("translate_sop_to_english_tool", args_schema=TranslateTextToEnglishInput)
def translate_sop_to_english_tool(
    text: str,
    source_language: str,
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
) -> Dict[str, Any]:
    """
    Translates non-English SOP text into Canonical English using the NLLB-200 pipeline.
    Automatically skips translation if source_language is already English.
    """
    logger.info("[Tool:translate_sop_to_english_tool] Invoked for source_language='%s'", source_language)
    english_text, meta = _run_coro_sync(
        translate_sop_to_english(
            text=text,
            source_language=source_language,
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
        )
    )
    return {"english_text": english_text, "translation_metadata": meta}


@tool("translate_pages_to_english_tool", args_schema=TranslatePagesToEnglishInput)
def translate_pages_to_english_tool(
    pages_data: List[Dict[str, Any]],
    source_language: str,
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
) -> Dict[str, Any]:
    """
    Translates a list of extracted SOP pages into Canonical English using the batched NLLB-200 pipeline.
    Preserves page numbers and skips translation if source_language is already English.
    """
    logger.info(
        "[Tool:translate_pages_to_english_tool] Invoked for %d page(s), source_language='%s'",
        len(pages_data),
        source_language,
    )
    eng_pages, meta = _run_coro_sync(
        translate_pages_to_english(
            pages_data=pages_data,
            source_language=source_language,
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
        )
    )
    return {"english_pages": eng_pages, "translation_metadata": meta}


@tool("translate_sop_sections_from_english_tool", args_schema=TranslateSectionsFromEnglishInput)
def translate_sop_sections_from_english_tool(
    sections: List[Dict[str, Any]],
    target_language: str,
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
) -> Dict[str, Any]:
    """
    Translates canonical English SOP sections into the selected target output language via NLLB-200.
    """
    logger.info(
        "[Tool:translate_sop_sections_from_english_tool] Invoked for %d section(s) -> '%s'",
        len(sections),
        target_language,
    )
    translated_secs, meta = _run_coro_sync(
        translate_sop_sections_from_english(
            sections=sections,
            target_language=target_language,
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
        )
    )
    return {"sections": translated_secs, "translation_metadata": meta}


def invoke_extract_sop_pdf(
    file_bytes: bytes,
    conversation_id: str,
    filename: str,
    document_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Direct capability wrapper for binary PDF extraction (used by DocumentAnalysisAgent
    so raw PDF bytes do not need JSON serialization inside LLM tool messages).
    """
    logger.info("[Tool:docling_extract_document] Extracting document '%s' (%d bytes)", filename, len(file_bytes))
    return extract_document(
        file_bytes=file_bytes,
        conversation_id=conversation_id,
        filename=filename,
        document_id=document_id,
    )
