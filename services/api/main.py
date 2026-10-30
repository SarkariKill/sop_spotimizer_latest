import asyncio
import concurrent.futures
import io
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from auth import hash_password, verify_password
from minio_storage import minio_storage
from nllb_translator import (
    NLLB_MODEL_ID,
    SUPPORTED_NLLB_LANGUAGES,
    detect_sop_language,
    get_unique_detected_languages,
    translate_pages_to_english,
    translate_sop_to_english,
)
from rag_engine import INDEX_STORAGE_PATH, create_hierarchical_chunks, get_vector_store, clear_vector_store
from similarity_engine import MultiSopSimilarityEngine
from harmonization_engine import HarmonizationEngine, SIMPLIFICATION_CATALOG
from sop_evaluator import evaluate_sop_with_llm
from sop_generator import generate_optimized_sop, parse_markdown_table_lines
from template_manager import template_manager
from graph import (
    execute_sop_workflow,
    aexecute_sop_workflow,
    get_graph_architecture_metadata,
)

logger = logging.getLogger(__name__)

similarity_engine = MultiSopSimilarityEngine()
harmonization_engine = HarmonizationEngine()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.getcwd() if os.path.exists(os.path.join(os.getcwd(), "services")) else os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "storage", "data", "chat.db")
DATABASE_PATH = os.getenv("DATABASE_PATH", DEFAULT_DB_PATH)
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://localhost:8001")

LEGACY_MODEL_MAP = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b": "openai/gpt-oss-120b",
}

app = FastAPI(title="Kenvue SOP Optimization & RAG API", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/agent-graph/info")
def get_agent_graph_info():
    """Returns introspection metadata for the LangChain + LangGraph Agentic Architecture."""
    return get_graph_architecture_metadata()


def db():
    c = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def now():
    return datetime.now(timezone.utc).isoformat()


def _build_safe_content_disposition(
    disposition: str,
    raw_filename: str,
    fallback_base: str = "SOP_Document",
) -> str:
    """
    Builds a Starlette/HTTP-compliant Content-Disposition header value that is
    guaranteed to be 100% latin-1 encodable (preventing UnicodeEncodeError 500 crashes
    when SOP titles or filenames contain Chinese, Japanese, Korean, Cyrillic, or Arabic),
    while also providing the RFC 5987 UTF-8 encoded filename* for modern browsers.
    """
    import urllib.parse

    disp = "attachment" if disposition.lower() == "attachment" else "inline"
    raw_clean = (raw_filename or fallback_base).strip()
    if not raw_clean.lower().endswith(".pdf"):
        raw_clean = f"{raw_clean}.pdf"

    # Strictly ASCII fallback filename for legacy 'filename="..."' parameter
    stem = re.sub(r"\.pdf$", "", raw_clean, flags=re.IGNORECASE)
    ascii_stem = re.sub(r"[^A-Za-z0-9\-_.]", "_", stem)
    ascii_stem = re.sub(r"_+", "_", ascii_stem).strip("_.")
    if not ascii_stem:
        ascii_stem = fallback_base
    ascii_filename = f"{ascii_stem[:80]}.pdf"

    # RFC 5987 UTF-8 percent-encoded filename* (pure ASCII characters)
    utf8_quoted = urllib.parse.quote(raw_clean, safe="-_.")
    header_val = f'{disp}; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_quoted}'
    # Final guarantee: ensure strict latin-1 encodability
    header_val.encode("latin-1")
    return header_val



def init_db():
    if os.path.dirname(DATABASE_PATH):
        os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL DEFAULT 'admin',
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sop_documents (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        username TEXT NOT NULL DEFAULT 'admin',
        filename TEXT NOT NULL,
        page_count INTEGER NOT NULL,
        original_language TEXT DEFAULT 'English',
        detected_language TEXT DEFAULT 'English',
        nllb_language_code TEXT DEFAULT 'eng_Latn',
        language_confidence REAL DEFAULT 1.0,
        translation_status TEXT DEFAULT 'skipped_already_english',
        translation_model TEXT DEFAULT 'facebook/nllb-200-distilled-600M',
        original_pdf_object_name TEXT,
        original_extracted_text TEXT,
        english_canonical_text TEXT,
        processing_status TEXT DEFAULT 'completed',
        output_language TEXT DEFAULT 'English',
        scores_json TEXT,
        optimized_scores_json TEXT,
        optimized_pdf_object_name TEXT,
        optimized_sections_json TEXT,
        optimized_english_sections_json TEXT,
        optimized_title TEXT,
        optimization_report_json TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sop_artifacts (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        artifact_type TEXT NOT NULL,
        object_name TEXT NOT NULL,
        caption TEXT NOT NULL,
        page INTEGER NOT NULL,
        table_markdown TEXT,
        width INTEGER,
        height INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS harmonized_sop_versions (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        username TEXT NOT NULL DEFAULT 'admin',
        version_number INTEGER NOT NULL,
        version_label TEXT NOT NULL,
        version_type TEXT NOT NULL,
        parent_version_id TEXT,
        source_document_ids_json TEXT NOT NULL,
        source_filenames_json TEXT NOT NULL,
        title TEXT NOT NULL,
        output_language TEXT DEFAULT 'English',
        detected_languages_json TEXT,
        markdown_content TEXT NOT NULL,
        sections_json TEXT NOT NULL,
        english_sections_json TEXT,
        scores_json TEXT NOT NULL,
        change_summary TEXT,
        applied_recommendations_json TEXT,
        user_prompt TEXT,
        pdf_object_name TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sop_similarity_cache (
        id TEXT PRIMARY KEY,
        conversation_id TEXT UNIQUE NOT NULL,
        analysis_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Safe column migrations for pre-existing databases
    try:
        conv_cols = [row[1] for row in c.execute("PRAGMA table_info(conversations)").fetchall()]
        if "username" not in conv_cols:
            c.execute("ALTER TABLE conversations ADD COLUMN username TEXT NOT NULL DEFAULT 'admin'")
        if "status" not in conv_cols:
            c.execute("ALTER TABLE conversations ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    except Exception as e:
        logger.warning("Conversation migration error: %s", e)

    try:
        sop_cols = [row[1] for row in c.execute("PRAGMA table_info(sop_documents)").fetchall()]
        sop_migrations = [
            ("username", "TEXT NOT NULL DEFAULT 'admin'"),
            ("original_language", "TEXT DEFAULT 'English'"),
            ("detected_language", "TEXT DEFAULT 'English'"),
            ("nllb_language_code", "TEXT DEFAULT 'eng_Latn'"),
            ("language_confidence", "REAL DEFAULT 1.0"),
            ("translation_status", "TEXT DEFAULT 'skipped_already_english'"),
            ("translation_model", "TEXT DEFAULT 'facebook/nllb-200-distilled-600M'"),
            ("original_pdf_object_name", "TEXT"),
            ("original_extracted_text", "TEXT"),
            ("english_canonical_text", "TEXT"),
            ("processing_status", "TEXT DEFAULT 'completed'"),
            ("output_language", "TEXT DEFAULT 'English'"),
            ("scores_json", "TEXT"),
            ("optimized_scores_json", "TEXT"),
            ("optimized_pdf_object_name", "TEXT"),
            ("optimized_sections_json", "TEXT"),
            ("optimized_english_sections_json", "TEXT"),
            ("optimized_title", "TEXT"),
            ("optimization_report_json", "TEXT"),
        ]
        for col_name, col_def in sop_migrations:
            if col_name not in sop_cols:
                c.execute(f"ALTER TABLE sop_documents ADD COLUMN {col_name} {col_def}")
    except Exception as e:
        logger.warning("SOP document migration error: %s", e)

    try:
        harm_cols = [row[1] for row in c.execute("PRAGMA table_info(harmonized_sop_versions)").fetchall()]
        harm_migrations = [
            ("output_language", "TEXT DEFAULT 'English'"),
            ("detected_languages_json", "TEXT"),
            ("english_sections_json", "TEXT"),
        ]
        for col_name, col_def in harm_migrations:
            if col_name not in harm_cols:
                c.execute(f"ALTER TABLE harmonized_sop_versions ADD COLUMN {col_name} {col_def}")
    except Exception as e:
        logger.warning("Harmonized versions migration error: %s", e)

    try:
        art_cols = [row[1] for row in c.execute("PRAGMA table_info(sop_artifacts)").fetchall()]
        art_migrations = [
            ("table_data_json", "TEXT"),
            ("table_name", "TEXT"),
            ("section_id", "TEXT"),
            ("section_title", "TEXT"),
        ]
        for col_name, col_def in art_migrations:
            if col_name not in art_cols:
                c.execute(f"ALTER TABLE sop_artifacts ADD COLUMN {col_name} {col_def}")
    except Exception as e:
        logger.warning("Artifacts table migration error: %s", e)

    # Seed default admin user: username=admin, password=admin
    admin_row = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not admin_row:
        c.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "admin", hash_password("admin"), "admin", now()),
        )
    c.commit()
    c.close()


init_db()


# -------------------------------------------------------------
# PYDANTIC REQUEST MODELS
# -------------------------------------------------------------
class AuthRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=3, max_length=100)


class MessageRequest(BaseModel):
    conversation_id: str
    content: str = Field(min_length=1, max_length=20000)


class ConversationCreate(BaseModel):
    title: str = "New Chat"


class SettingsRequest(BaseModel):
    provider: Literal["azure_openai"] = "azure_openai"
    azure_openai_endpoint: str = ""
    azure_openai_key: Optional[str] = None
    azure_openai_deployment_name: str = ""
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_api_version: str = "2024-02-01"


class OptimizeRequest(BaseModel):
    document_id: Optional[str] = None
    selected_suggestion_ids: List[str] = []
    custom_instructions: str = ""
    output_language: Optional[str] = None


class HarmonizeRequest(BaseModel):
    selected_document_ids: List[str]
    custom_instructions: Optional[str] = None
    title_override: Optional[str] = None
    output_language: Optional[str] = None


class SimplifyRequest(BaseModel):
    version_id: Optional[str] = None
    selected_recommendation_ids: List[str] = []
    custom_instructions: Optional[str] = None
    output_language: Optional[str] = None


class RefineRequest(BaseModel):
    version_id: Optional[str] = None
    refinement_prompt: str = Field(min_length=1, max_length=20000)
    output_language: Optional[str] = None


class ManualLanguageRequest(BaseModel):
    source_language: str
    output_language: Optional[str] = None


# =============================================================
# 1. AUTHENTICATION & USER MANAGEMENT
# =============================================================
@app.post("/auth/register")
def register(payload: AuthRequest):
    username = payload.username.strip().lower()
    c = db()
    existing = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        c.close()
        raise HTTPException(400, "Username already exists. Please pick another one or sign in.")

    uid = str(uuid.uuid4())
    pw_hash = hash_password(payload.password)
    role = "admin" if username == "admin" else "user"
    c.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)", (uid, username, pw_hash, role, now()))
    c.commit()
    c.close()
    return {"status": "ok", "username": username, "role": role}


@app.post("/auth/login")
def login(payload: AuthRequest):
    username = payload.username.strip().lower()
    c = db()
    user = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    c.close()
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password.")
    return {"status": "ok", "username": user["username"], "role": user["role"]}


# =============================================================
# 2. CONVERSATIONS (USER-ISOLATED)
# =============================================================
@app.get("/health")
def health():
    return {"status": "ok", "service": "api", "extraction_engine": "docling"}


@app.post("/conversations")
def create_conversation(payload: ConversationCreate, x_username: Optional[str] = Header(None, alias="X-User-Name")):
    username = (x_username or "admin").strip().lower()
    cid = str(uuid.uuid4())
    ts = now()
    c = db()
    c.execute(
        "INSERT INTO conversations (id, username, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (cid, username, payload.title, "active", ts, ts),
    )
    c.commit()
    c.close()
    return {"id": cid, "title": payload.title, "username": username}



@app.get("/conversations")
def list_conversations(x_username: Optional[str] = Header(None, alias="X-User-Name")):
    username = (x_username or "admin").strip().lower()
    c = db()
    rows = c.execute(
        "SELECT * FROM conversations WHERE username=? ORDER BY updated_at DESC",
        (username,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str):
    c = db()
    rows = c.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
        (conversation_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    # --- HERE PERMANENT SESSION DELETION HAPPENS ---
    Permanently deletes a chat session from history.
    Wipes:
    1. Database entries (messages, sop_documents, sop_artifacts, conversations).
    2. MinIO user folder assets for this conversation:
       - users/{username}/conversations/{conversation_id}/*
       - users/{username}/summaries/{conversation_id}_summary.txt
       - any specific stored artifacts or optimized PDFs.
    3. FAISS vector index files (faiss_{conversation_id}.index, faiss_{conversation_id}_meta.json).
    """
    username = (x_username or "admin").strip().lower()
    c = db()
    conv = c.execute(
        "SELECT * FROM conversations WHERE id=? AND username=?",
        (conversation_id, username),
    ).fetchone()
    if not conv:
        c.close()
        raise HTTPException(404, "Conversation not found or access denied")

    # Fetch artifacts & documents to ensure all MinIO files are explicitly removed
    artifacts = c.execute(
        "SELECT object_name FROM sop_artifacts WHERE conversation_id=?",
        (conversation_id,),
    ).fetchall()
    docs = c.execute(
        "SELECT optimized_pdf_object_name FROM sop_documents WHERE conversation_id=?",
        (conversation_id,),
    ).fetchall()

    # 1. Clean up individual MinIO artifacts if any
    for art in artifacts:
        if art["object_name"]:
            try:
                minio_storage.remove_file(art["object_name"])
            except Exception as e:
                logger.warning("Could not delete artifact %s: %s", art["object_name"], e)

    for doc in docs:
        if doc["optimized_pdf_object_name"]:
            try:
                minio_storage.remove_file(doc["optimized_pdf_object_name"])
            except Exception as e:
                logger.warning("Could not delete optimized pdf %s: %s", doc["optimized_pdf_object_name"], e)

    # 2. Recursively delete entire conversation folder prefix in MinIO
    conv_prefix = f"users/{username}/conversations/{conversation_id}/"
    minio_storage.remove_directory_prefix(conv_prefix)
    minio_storage.remove_directory_prefix(f"images/{conv_prefix}")
    minio_storage.remove_directory_prefix(f"tables/{conv_prefix}")

    # 3. Delete any archived summary in MinIO
    summary_object_name = f"users/{username}/summaries/{conversation_id}_summary.txt"
    try:
        minio_storage.remove_file(summary_object_name)
    except Exception as e:
        logger.warning("Could not delete summary file %s: %s", summary_object_name, e)

    # 4. Clean up FAISS vector index files
    clear_vector_store(conversation_id)

    # 5. Delete from SQLite database
    c.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
    c.execute("DELETE FROM sop_artifacts WHERE conversation_id=?", (conversation_id,))
    c.execute("DELETE FROM sop_documents WHERE conversation_id=?", (conversation_id,))
    c.execute("DELETE FROM harmonized_sop_versions WHERE conversation_id=?", (conversation_id,))
    c.execute("DELETE FROM sop_similarity_cache WHERE conversation_id=?", (conversation_id,))
    c.execute("DELETE FROM conversations WHERE id=? AND username=?", (conversation_id, username))
    c.commit()
    c.close()

    logger.info("Permanently deleted conversation %s and all associated assets for user '%s'", conversation_id, username)
    return {
        "status": "deleted",
        "conversation_id": conversation_id,
        "message": "Chat session and all associated files/indexes permanently deleted.",
    }


# =============================================================
# 3. ADMIN-ONLY LLM SETTINGS (.ENV PERSISTENCE) & TEMPLATE GUIDELINES
# =============================================================
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, ".env")


def read_env_file() -> Dict[str, str]:
    """Read key-value pairs directly from the project .env file."""
    env_map: Dict[str, str] = {}
    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        k, v = s.split("=", 1)
                        env_map[k.strip()] = v.strip().strip('"').strip("'")
        except Exception as e:
            logger.warning("Failed reading .env file: %s", e)
    return env_map


def update_env_file(updates: Dict[str, str]) -> None:
    """
    Update or insert keys in the .env file in-place, replacing previous values.
    Also updates os.environ in runtime so changes take effect immediately.
    """
    lines: List[str] = []
    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.warning("Failed reading .env for update: %s", e)

    remaining = dict(updates)
    new_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k_clean = k.strip()
            if k_clean in remaining:
                new_val = remaining.pop(k_clean)
                new_lines.append(f"{k_clean}={new_val}\n")
                os.environ[k_clean] = new_val
                continue
        new_lines.append(line)

    if remaining:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        for k_clean, new_val in remaining.items():
            new_lines.append(f"{k_clean}={new_val}\n")
            os.environ[k_clean] = new_val

    try:
        with open(ENV_FILE_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        logger.info("Updated .env file at %s with keys: %s", ENV_FILE_PATH, list(updates.keys()))
    except Exception as e:
        logger.error("Failed writing to .env file: %s", e)


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}••••••{key[-4:]}"


def get_global_llm_config() -> Dict[str, Any]:
    """
    Returns the Azure OpenAI configuration.
    Reads from .env file first (and syncs existing SQLite keys to .env if .env was empty).
    Variables managed:
      - AZURE_OPENAI_ENDPOINT
      - AZURE_OPENAI_KEY
      - AZURE_OPENAI_DEPLOYMENT_NAME
      - AZURE_OPENAI_EMBEDDING_DEPLOYMENT
      - AZURE_OPENAI_API_VERSION
    """
    env_vals = read_env_file()
    c = db()
    rows = c.execute("SELECT key, value FROM settings").fetchall()
    c.close()
    db_vals = {r["key"]: r["value"] for r in rows}

    # Sync any pre-existing Azure DB keys to .env once if .env is still blank
    initial_sync: Dict[str, str] = {}
    for env_key, db_key in [
        ("AZURE_OPENAI_ENDPOINT", "azure_openai_endpoint"),
        ("AZURE_OPENAI_KEY", "azure_openai_key"),
        ("AZURE_OPENAI_DEPLOYMENT_NAME", "azure_openai_deployment_name"),
        ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "azure_openai_embedding_deployment"),
        ("AZURE_OPENAI_API_VERSION", "azure_openai_api_version"),
    ]:
        if not env_vals.get(env_key) and not os.getenv(env_key) and db_vals.get(db_key):
            initial_sync[env_key] = db_vals[db_key].strip()

    if initial_sync:
        update_env_file(initial_sync)
        env_vals.update(initial_sync)

    azure_endpoint = (
        env_vals.get("AZURE_OPENAI_ENDPOINT")
        or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        or db_vals.get("azure_openai_endpoint", "")
    ).strip()

    azure_key = (
        env_vals.get("AZURE_OPENAI_KEY")
        or os.getenv("AZURE_OPENAI_KEY", "")
        or db_vals.get("azure_openai_key", "")
    ).strip()

    azure_deployment_name = (
        env_vals.get("AZURE_OPENAI_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")
        or db_vals.get("azure_openai_deployment_name", "")
    ).strip()

    azure_embedding_deployment = (
        env_vals.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
        or db_vals.get("azure_openai_embedding_deployment", "")
        or "text-embedding-3-small"
    ).strip()

    azure_api_version = (
        env_vals.get("AZURE_OPENAI_API_VERSION")
        or os.getenv("AZURE_OPENAI_API_VERSION", "")
        or db_vals.get("azure_openai_api_version", "")
        or "2024-02-01"
    ).strip()

    is_chat_ready = bool(azure_endpoint and azure_key and azure_deployment_name)
    is_fully_configured = bool(
        azure_endpoint and azure_key and azure_deployment_name and azure_embedding_deployment
    )

    return {
        "provider": "azure_openai",
        "model": azure_deployment_name or "gpt-4o-mini",
        "api_key": azure_key if is_chat_ready else "",
        "api_key_configured": is_chat_ready,
        "azure_openai_endpoint": azure_endpoint,
        "azure_openai_key": azure_key,
        "azure_openai_masked_key": _mask_key(azure_key),
        "azure_openai_deployment_name": azure_deployment_name,
        "azure_openai_embedding_deployment": azure_embedding_deployment,
        "azure_openai_api_version": azure_api_version,
        "azure_configured": is_fully_configured,
        "active_masked_key": _mask_key(azure_key),
    }


def _public_llm_settings(cfg):
    # Never return either raw credential to the browser.
    return {key: cfg[key] for key in (
        "provider", "model", "api_key_configured", "azure_configured",
        "azure_openai_endpoint", "azure_openai_masked_key", "azure_openai_deployment_name",
        "azure_openai_embedding_deployment", "azure_openai_api_version", "active_masked_key")}


@app.get("/settings")
def get_settings():
    cfg = get_global_llm_config()
    template_status = template_manager.get_template_status()

    return {**_public_llm_settings(cfg), "env_file_path": ENV_FILE_PATH,
            "template_status": template_status}


@app.post("/settings")
def save_settings(
    payload: SettingsRequest,
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    Admin-only endpoint:
    Saves the 5 Azure OpenAI & Azure Text-Embedding-3 configuration variables directly into .env and SQLite:
      - AZURE_OPENAI_ENDPOINT
      - AZURE_OPENAI_KEY
      - AZURE_OPENAI_DEPLOYMENT_NAME
      - AZURE_OPENAI_EMBEDDING_DEPLOYMENT
      - AZURE_OPENAI_API_VERSION
    """
    username = (x_username or "").strip().lower()
    c = db()
    user = c.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
    if not user or user["role"] != "admin":
        c.close()
        raise HTTPException(403, "Only Admin is authorized to configure LLM providers and API keys.")

    endpoint = (payload.azure_openai_endpoint or "").strip()
    deployment_name = (payload.azure_openai_deployment_name or "").strip()
    embedding_deployment = (payload.azure_openai_embedding_deployment or "text-embedding-3-small").strip()
    api_version = (payload.azure_openai_api_version or "2024-02-01").strip()
    clean_key = (payload.azure_openai_key or "").strip()

    if not endpoint:
        c.close()
        raise HTTPException(400, "AZURE_OPENAI_ENDPOINT is required.")
    if not deployment_name:
        c.close()
        raise HTTPException(400, "AZURE_OPENAI_DEPLOYMENT_NAME is required.")
    if not embedding_deployment:
        c.close()
        raise HTTPException(400, "AZURE_OPENAI_EMBEDDING_DEPLOYMENT is required.")

    # 1. Update SQLite settings
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('provider', 'azure_openai')")
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('model', ?)", (deployment_name,))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('azure_openai_endpoint', ?)", (endpoint,))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('azure_openai_deployment_name', ?)", (deployment_name,))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('azure_openai_embedding_deployment', ?)", (embedding_deployment,))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('azure_openai_api_version', ?)", (api_version,))
    if clean_key:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('azure_openai_key', ?)", (clean_key,))
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('api_key', ?)", (clean_key,))
    c.commit()
    c.close()

    # 2. Write directly to .env file
    env_updates: Dict[str, str] = {
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_DEPLOYMENT_NAME": deployment_name,
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": embedding_deployment,
        "AZURE_OPENAI_API_VERSION": api_version,
        "ACTIVE_LLM_PROVIDER": "azure_openai",
    }
    if clean_key:
        env_updates["AZURE_OPENAI_KEY"] = clean_key

    update_env_file(env_updates)

    cfg = get_global_llm_config()
    return {"status": "saved", **_public_llm_settings(cfg),
            "message": f"Saved Azure OpenAI configuration. Chat Deployment: {deployment_name} | Embedding Deployment: {embedding_deployment}"}


@app.post("/admin/upload-template")
async def upload_admin_template(file: UploadFile = File(...), x_username: Optional[str] = Header(None, alias="X-User-Name")):
    """
    Admin-only endpoint: upload the official Kenvue Template PDF.
    Old template embeddings are deleted, and fresh FAISS embeddings are built.
    """
    username = (x_username or "").strip().lower()
    c = db()
    user = c.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
    c.close()
    if not user or user["role"] != "admin":
        raise HTTPException(403, "Admin privileges required to upload standard Kenvue templates.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Template file must be a PDF document.")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(400, "Uploaded file is empty.")

    res = template_manager.upload_admin_template(
        file_bytes=file_bytes,
        filename=file.filename,
        uploaded_by=username,
    )
    return res


# =============================================================
# 4. SOP UPLOAD, LANGUAGE DETECTION, NLLB TRANSLATION & STORAGE
# =============================================================
@app.get("/languages/supported")
def get_supported_languages():
    """Returns all languages supported by the NLLB-200 multilingual SOP pipeline."""
    return {
        "translation_model": NLLB_MODEL_ID,
        "internal_processing_language": "English",
        "supported_languages": [
            {
                "language": lang_name,
                "nllb_code": info["nllb_code"],
                "iso_code": info["iso"],
                "native_name": info["native_name"],
                "flag": info["flag"],
            }
            for lang_name, info in SUPPORTED_NLLB_LANGUAGES.items()
        ],
    }


def _process_single_sop_in_thread(
    item_idx: int,
    total_files: int,
    filename: str,
    file_bytes: bytes,
    conversation_id: str,
    scoped_conv_prefix: str,
    username: str,
    provider: str,
    model: str,
    api_key: str,
    ts: str,
) -> Dict[str, Any]:
    """
    Worker function executed in a dedicated thread per uploaded SOP.
    Invokes the compiled LangGraph `sop_agent_graph` workflow (`task_type="sop_single_ingestion"`)
    across SupervisorAgent -> DocumentAnalysisAgent -> RetrievalAgent -> EvaluationAgent -> FinalResponse:
      Step 0: Preserve untouched original PDF in local storage
      Step 1 (DocumentAnalysisAgent): Extract PDF text/images/tables, detect language, NLLB-200 translate to Canonical English
      Step 2 (RetrievalAgent): Hierarchical Chunking on Canonical English representation
      Step 3 (EvaluationAgent): SOP Evaluation & Scoring (using token-optimized compact rubric for multi-SOP batches)
    """
    t0 = time.perf_counter()
    thread_name = threading.current_thread().name
    doc_id = str(uuid.uuid4())
    safe_fname = re.sub(r"[^\w\-_.]", "_", filename)
    original_pdf_object_name = f"{scoped_conv_prefix}/originals/{doc_id}_{safe_fname}"
    artifacts_data: List[Dict[str, Any]] = []

    logger.info(
        "[MULTITHREAD-SOP] Thread '%s' started LangGraph workflow for SOP %d/%d: '%s'",
        thread_name,
        item_idx + 1,
        total_files,
        filename,
    )

    try:
        c_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if filename.lower().endswith(".docx") else "application/pdf"
        minio_storage.upload_file_bytes(
            object_name=original_pdf_object_name,
            data=file_bytes,
            content_type=c_type,
            metadata={
                "conversation_id": conversation_id,
                "document_id": doc_id,
                "filename": filename,
                "type": "original_sop_document",
            },
        )

        # Execute LangGraph multi-agent workflow inside this worker thread
        graph_state = execute_sop_workflow(
            task_type="sop_single_ingestion",
            conversation_id=conversation_id,
            username=username,
            input_payload={
                "doc_id": doc_id,
                "filename": filename,
                "file_bytes": file_bytes,
                "scoped_conv_prefix": scoped_conv_prefix,
                "compact_mode": (total_files > 1),
                "llm_config": {
                    "llm_service_url": LLM_SERVICE_URL,
                    "provider": "azure_openai",
                    "model": model,
                    "api_key": api_key,
                },
            },
        )

        errors = graph_state.get("errors", [])
        intermediate = graph_state.get("intermediate_results", {})
        artifacts_data = intermediate.get("artifacts_data", [])

        if errors:
            err = errors[-1]
            err_type = err.get("error_type", "error")
            minio_storage.remove_file(original_pdf_object_name)
            minio_storage.remove_file(f"{scoped_conv_prefix}/extraction/{doc_id}.json")
            for art in err.get("artifacts_data", artifacts_data):
                if art.get("object_name"):
                    minio_storage.remove_file(art["object_name"])

            if err_type == "unsupported_language":
                err_msg = err.get("message", f"Language detected in '{filename}' is not supported.")
                logger.error("[NLLB-DETECTION] Unsupported language in '%s': %s", filename, err_msg)
                return {
                    "item_idx": item_idx,
                    "status": "unsupported_language",
                    "error_status": err.get("error_status", 400),
                    "error_message": err_msg,
                    "filename": filename,
                }
            return {
                "item_idx": item_idx,
                "status": err_type,
                "error_status": err.get("error_status", 503),
                "filename": filename,
                "error_message": err.get("message", "SOP processing failed"),
            }

        stats = intermediate["stats"]
        raw_extracted_text = intermediate["raw_extracted_text"]
        detected_lang = intermediate["detected_language"]
        nllb_code = intermediate["nllb_code"]
        lang_conf = intermediate["language_confidence"]
        english_canonical_text = intermediate["english_canonical_text"]
        trans_meta = intermediate["translation_metadata"]
        child_chunks = intermediate["child_chunks"]
        evaluation = intermediate["evaluation"]

        translation_status = trans_meta.get("translation_status", "completed")
        translation_model = trans_meta.get("translation_model", NLLB_MODEL_ID)

        # Save canonical English representation in storage alongside original PDF
        canonical_obj_name = f"{scoped_conv_prefix}/canonical_english/{doc_id}_english.txt"
        minio_storage.upload_file_bytes(
            object_name=canonical_obj_name,
            data=english_canonical_text.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            metadata={
                "conversation_id": conversation_id,
                "document_id": doc_id,
                "original_language": detected_lang,
                "translation_status": translation_status,
                "translation_model": translation_model,
            },
        )

        default_output_language = detected_lang
        processing_status = "completed" if stats.get("extraction_status", "complete") == "complete" else "review_required"
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        logger.info(
            "[MULTITHREAD-SOP] Thread '%s' finished SOP %d/%d '%s' (lang=%s, score=%s, chunks=%d) in %.1f ms",
            thread_name,
            item_idx + 1,
            total_files,
            filename,
            detected_lang,
            evaluation.get("average_score"),
            len(child_chunks),
            elapsed_ms,
        )

        lang_meta = SUPPORTED_NLLB_LANGUAGES.get(detected_lang, SUPPORTED_NLLB_LANGUAGES["English"])
        processed_doc = {
            "id": doc_id,
            "document_id": doc_id,
            "filename": filename,
            "page_count": stats["page_count"],
            "original_language": detected_lang,
            "detected_language": detected_lang,
            "nllb_language_code": nllb_code,
            "language_confidence": lang_conf,
            "language_flag": lang_meta["flag"],
            "language_native_name": lang_meta["native_name"],
            "translation_status": translation_status,
            "translation_model": translation_model,
            "internal_processing_language": "English",
            "output_language": default_output_language,
            "processing_status": processing_status,
            "extraction_engine": stats.get("extraction_engine"),
            "extraction_warnings": stats.get("extraction_warnings", []),
            "original_pdf_url": f"/conversations/{conversation_id}/sop/{doc_id}/original-pdf",
            "original_extracted_text": raw_extracted_text,
            "english_canonical_text": english_canonical_text,
            "evaluation": evaluation,
            "scores": evaluation,
            "images_extracted": stats["images_extracted"],
            "tables_extracted": stats["tables_extracted"],
            "worker_thread": thread_name,
            "processing_time_ms": elapsed_ms,
            "agent_trace": graph_state.get("agent_trace", []),
        }

        db_doc_tuple = (
            doc_id,
            conversation_id,
            username,
            filename,
            stats["page_count"],
            detected_lang,
            detected_lang,
            nllb_code,
            lang_conf,
            translation_status,
            translation_model,
            original_pdf_object_name,
            raw_extracted_text,
            english_canonical_text,
            processing_status,
            default_output_language,
            json.dumps(evaluation),
            ts,
        )

        return {
            "item_idx": item_idx,
            "status": "ok",
            "doc_id": doc_id,
            "original_pdf_object_name": original_pdf_object_name,
            "canonical_obj_name": canonical_obj_name,
            "artifacts_data": artifacts_data,
            "child_chunks": child_chunks,
            "processed_doc": processed_doc,
            "db_doc_tuple": db_doc_tuple,
            "thread_name": thread_name,
            "processing_time_ms": elapsed_ms,
            "agent_trace": graph_state.get("agent_trace", []),
        }
    except Exception as exc:
        logger.error("[MULTITHREAD-SOP] Unexpected error in thread '%s' for '%s': %s", thread_name, filename, exc)
        minio_storage.remove_file(original_pdf_object_name)
        minio_storage.remove_file(f"{scoped_conv_prefix}/extraction/{doc_id}.json")
        for art in artifacts_data:
            if art.get("object_name"):
                minio_storage.remove_file(art["object_name"])
        return {
            "item_idx": item_idx,
            "status": "error",
            "error_status": getattr(exc, "status_code", 503),
            "filename": filename,
            "error_message": str(exc),
        }


@app.post("/conversations/{conversation_id}/upload-sop")
async def upload_sop(
    conversation_id: str,
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    Multithreaded Multilingual Multi-SOP Upload, NLLB Translation & Evaluation (At Max 10 SOPs at a time):
    Spawns a dedicated worker thread for each uploaded SOP via ThreadPoolExecutor so that:
    1. Each worker thread runs the LangGraph `sop_single_ingestion` workflow concurrently
       (DocumentAnalysisAgent -> RetrievalAgent -> EvaluationAgent).
    2. Compact token-optimized audit rubrics and SOP digests reduce LLM token usage by >60%
       while delivering much faster multi-SOP turnaround.
    3. All Canonical English chunks are then indexed into FAISS FlatIP vector store and cross-lingual similarity
       analysis is computed via the LangGraph `sop_collection_post_ingest` workflow.
    """
    batch_t0 = time.perf_counter()
    username = (x_username or "admin").strip().lower()
    c = db()
    conv_row = c.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    c.close()
    if not conv_row:
        raise HTTPException(404, "Conversation not found")
    conv = dict(conv_row)

    # Consolidate files from either 'files' or 'file' parameters
    upload_list: List[UploadFile] = []
    if files:
        upload_list.extend([f for f in files if f.filename])
    if file and file.filename and not any(f.filename == file.filename for f in upload_list):
        upload_list.append(file)

    if not upload_list:
        raise HTTPException(400, "Please provide at least one SOP document (PDF or DOCX).")

    if len(upload_list) > 10:
        raise HTTPException(400, f"You can upload a maximum of 10 SOP documents at a time (selected: {len(upload_list)}).")

    for f in upload_list:
        fname_lower = f.filename.lower()
        if not (fname_lower.endswith(".pdf") or fname_lower.endswith(".docx")):
            raise HTTPException(400, f"File '{f.filename}' is not a supported format. Only PDF and DOCX files are supported.")

    # Read file bytes upfront before dispatching to worker threads
    upload_items: List[tuple[int, str, bytes]] = []
    for f in upload_list:
        file_bytes = await f.read()
        if len(file_bytes) > 0:
            upload_items.append((len(upload_items), f.filename, file_bytes))

    if not upload_items:
        raise HTTPException(400, "Could not extract or process any of the uploaded SOP files.")

    llm_cfg = get_global_llm_config()
    provider = llm_cfg["provider"]
    model = llm_cfg["model"]
    api_key = llm_cfg["api_key"]

    scoped_conv_prefix = f"users/{username}/conversations/{conversation_id}"
    ts = now()
    total_files = len(upload_items)
    max_workers = max(1, min(total_files, 10))

    logger.info(
        "[MULTITHREAD-SOP] Dispatching %d SOP(s) across %d parallel worker thread(s) for conversation %s",
        total_files,
        max_workers,
        conversation_id,
    )

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="SOPWorker",
    ) as executor:
        worker_futures = [
            loop.run_in_executor(
                executor,
                _process_single_sop_in_thread,
                item_idx,
                total_files,
                fname,
                fbytes,
                conversation_id,
                scoped_conv_prefix,
                username,
                provider,
                model,
                api_key,
                ts,
            )
            for item_idx, fname, fbytes in upload_items
        ]
        thread_results = await asyncio.gather(*worker_futures)

    # Sort results by original upload order
    thread_results = sorted(thread_results, key=lambda r: r.get("item_idx", 0))

    # Check if any worker thread failed (e.g. LLM service unavailable or unsupported language)
    failed_res = next((r for r in thread_results if r.get("status") != "ok"), None)
    if failed_res:
        # Clean up any files written by sibling threads in this rejected batch
        for r in thread_results:
            if r.get("status") == "ok":
                if r.get("original_pdf_object_name"):
                    minio_storage.remove_file(r["original_pdf_object_name"])
                minio_storage.remove_file(f"{scoped_conv_prefix}/extraction/{r['doc_id']}.json")
                if r.get("canonical_obj_name"):
                    minio_storage.remove_file(r["canonical_obj_name"])
                for art in r.get("artifacts_data", []):
                    if art.get("object_name"):
                        minio_storage.remove_file(art["object_name"])
        raise HTTPException(
            failed_res.get("error_status", 503),
            failed_res.get("error_message", "LLM Service Unavailable: Unable to process and score SOP."),
        )

    all_child_chunks: List[Dict[str, Any]] = []
    processed_docs: List[Dict[str, Any]] = []

    c = db()
    try:
        # Persist artifacts and SOP document records from all completed threads into SQLite
        for res in thread_results:
            if res.get("status") != "ok":
                continue
            doc_id = res["doc_id"]
            for art in res["artifacts_data"]:
                c.execute(
                    """INSERT INTO sop_artifacts 
                       (id, conversation_id, document_id, artifact_type, object_name, caption, page, table_markdown, width, height, created_at, table_data_json, table_name, section_id, section_title)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        art["id"],
                        conversation_id,
                        doc_id,
                        art["artifact_type"],
                        art["object_name"],
                        art["caption"],
                        art["page"],
                        art.get("table_markdown"),
                        art.get("width", 0),
                        art.get("height", 0),
                        ts,
                        json.dumps(art.get("table_data")) if art.get("table_data") else None,
                        art.get("table_name"),
                        art.get("section_id"),
                        art.get("section_title"),
                    ),
                )
            c.execute(
                """INSERT INTO sop_documents (
                       id, conversation_id, username, filename, page_count,
                       original_language, detected_language, nllb_language_code, language_confidence,
                       translation_status, translation_model, original_pdf_object_name,
                       original_extracted_text, english_canonical_text, processing_status,
                       output_language, scores_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                res["db_doc_tuple"],
            )
            all_child_chunks.extend(res["child_chunks"])
            processed_docs.append(res["processed_doc"])

        if not processed_docs:
            c.close()
            raise HTTPException(400, "Could not extract or process any of the uploaded SOP files (PDF or DOCX).")

        # Deduplicate unique detected languages across all uploaded SOPs in the conversation
        all_conv_docs_rows = c.execute(
            "SELECT * FROM sop_documents WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC",
            (conversation_id,),
        ).fetchall()
        all_conv_docs = [dict(r) for r in all_conv_docs_rows]
        unique_detected_languages = get_unique_detected_languages(all_conv_docs)
        detected_lang_names = [l["language"] for l in unique_detected_languages]

        sim_docs = []
        for cd in all_conv_docs:
            sim_docs.append({
                "id": cd["id"],
                "document_id": cd["id"],
                "filename": cd["filename"],
                "detected_language": cd.get("detected_language") or "English",
                "original_language": cd.get("original_language") or "English",
                "original_text": cd.get("english_canonical_text") or cd.get("original_extracted_text") or "",
            })

        # Step 5: Execute LangGraph `sop_collection_post_ingest` workflow for FAISS FlatIP indexing & Multi-SOP Similarity
        post_ingest_state = await aexecute_sop_workflow(
            task_type="sop_collection_post_ingest",
            conversation_id=conversation_id,
            username=username,
            input_payload={
                "child_chunks": all_child_chunks,
                "all_child_chunks": get_vector_store(conversation_id).child_chunks or all_child_chunks,
                "unique_detected_languages": unique_detected_languages,
            },
            documents=sim_docs,
        )
        post_errors = post_ingest_state.get("errors", [])
        if post_errors:
            c.close()
            err = post_errors[-1]
            raise HTTPException(err.get("error_status", 500), err.get("message", "Failed indexing chunks"))

        post_inter = post_ingest_state.get("intermediate_results", {})
        faiss_res = post_inter.get("faiss_index_result", {})
        total_vectors = faiss_res.get("total_vectors", len(all_child_chunks))
        sim_analysis = post_inter.get("similarity_analysis")

        if sim_analysis is not None:
            c.execute(
                "INSERT OR REPLACE INTO sop_similarity_cache (id, conversation_id, analysis_json, updated_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), conversation_id, json.dumps(sim_analysis), ts),
            )

        # Step 6: Compute aggregated evaluation metrics across all uploaded SOPs
        avg_score = round(sum(d["evaluation"]["average_score"] for d in processed_docs) / len(processed_docs))
        tmpl_score = round(sum(d["evaluation"]["template_score"] for d in processed_docs) / len(processed_docs))
        read_score = round(sum(d["evaluation"]["readability_score"] for d in processed_docs) / len(processed_docs))
        qual_score = round(sum(d["evaluation"]["quality_score"] for d in processed_docs) / len(processed_docs))

        # Deduplicate improvement suggestions across the batch
        all_suggestions = []
        seen_sug_titles = set()
        for d in processed_docs:
            for sug in d["evaluation"].get("suggestions", []):
                if sug.get("title") not in seen_sug_titles:
                    seen_sug_titles.add(sug.get("title"))
                    all_suggestions.append(sug)

        aggregated_evaluation = {
            "average_score": avg_score,
            "template_score": tmpl_score,
            "readability_score": read_score,
            "quality_score": qual_score,
            "summary": (
                f"Multilingual Multi-SOP Collection Assessment ({len(processed_docs)} Documents processed in parallel across {len(processed_docs)} threads, "
                f"Detected Languages: {', '.join(detected_lang_names)} -> Normalized to Canonical English via NLLB-200). "
                f"All procedural vectors indexed in FAISS FlatIP vector store ({total_vectors} English chunks indexed)."
                if len(processed_docs) > 1
                else processed_docs[0]["evaluation"].get("summary", "")
            ),
            "suggestions": all_suggestions[:6],
        }

        # Step 7: Auto-update conversation title
        if conv["title"] == "New Chat":
            if len(processed_docs) == 1:
                clean_name = re.sub(r"\.(pdf|docx)$", "", processed_docs[0]["filename"], flags=re.IGNORECASE).replace("_", " ").replace("-", " ").strip()
                new_title = f"SOP: {clean_name[:28]}"
            else:
                names_summary = ", ".join([re.sub(r"\.(pdf|docx)$", "", d["filename"], flags=re.IGNORECASE)[:12] for d in processed_docs[:3]])
                if len(processed_docs) > 3:
                    names_summary += f" +{len(processed_docs) - 3}"
                new_title = f"SOP Batch ({len(processed_docs)}): {names_summary}"
            c.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (new_title, ts, conversation_id))
        else:
            new_title = conv["title"]

        c.commit()
    finally:
        c.close()

    total_batch_ms = round((time.perf_counter() - batch_t0) * 1000, 1)
    primary_doc = processed_docs[0]
    return {
        "status": "success",
        "has_sop": True,
        "document_count": len(processed_docs),
        "documents": processed_docs,
        "document_id": primary_doc["document_id"],
        "filename": primary_doc["filename"],
        "filenames": [d["filename"] for d in processed_docs],
        "page_count": sum(d["page_count"] for d in processed_docs),
        "conversation_title": new_title,
        "detected_languages": unique_detected_languages,
        "available_output_languages": detected_lang_names,
        "internal_processing_language": "English",
        "translation_model": NLLB_MODEL_ID,
        "evaluation": aggregated_evaluation if len(processed_docs) > 1 else primary_doc["evaluation"],
        "collection_scores": aggregated_evaluation,
        "index_type": "FAISS IndexFlatIP (Exact Cosine Inner Product - Canonical English)",
        "total_vectors": total_vectors,
        "similarity_analysis": sim_analysis,
        "multithreaded_processing": True,
        "parallel_threads_used": len(processed_docs),
        "total_processing_time_ms": total_batch_ms,
        "agent_trace": post_ingest_state.get("agent_trace", []),
    }


@app.get("/conversations/{conversation_id}/sop/{document_id}/original-pdf")
def get_original_sop_pdf(conversation_id: str, document_id: str, download: bool = False):
    """Serves the untouched original uploaded SOP document (PDF or DOCX) in its original language."""
    c = db()
    doc = c.execute(
        "SELECT filename, original_pdf_object_name FROM sop_documents WHERE id=? AND conversation_id=?",
        (document_id, conversation_id),
    ).fetchone()
    c.close()
    if not doc or not doc["original_pdf_object_name"]:
        raise HTTPException(404, "Original uploaded SOP document not found.")

    data, _ = minio_storage.get_file_bytes(doc["original_pdf_object_name"])
    if not data:
        raise HTTPException(404, "Original SOP file not found in local storage.")

    is_docx = (doc["filename"] or "").lower().endswith(".docx")
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if is_docx
        else "application/pdf"
    )
    disp = "attachment" if (download or is_docx) else "inline"
    header_val = _build_safe_content_disposition(
        disp,
        f"Original_{doc['filename']}",
        fallback_base="Original_SOP",
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": header_val},
    )


@app.post("/conversations/{conversation_id}/sop/{document_id}/set-language")
async def set_document_language_override(
    conversation_id: str,
    document_id: str,
    payload: ManualLanguageRequest,
):
    """
    Allows the user to manually override or retry source language detection / NLLB translation
    or update the desired output language for a specific SOP document via the LangGraph workflow.
    """
    c = db()
    doc = c.execute(
        "SELECT * FROM sop_documents WHERE id=? AND conversation_id=?",
        (document_id, conversation_id),
    ).fetchone()
    if not doc:
        c.close()
        raise HTTPException(404, "SOP document not found.")

    doc_dict = dict(doc)
    source_lang = (payload.source_language or doc_dict.get("detected_language") or "English").strip()
    if source_lang not in SUPPORTED_NLLB_LANGUAGES:
        c.close()
        raise HTTPException(
            400,
            f"Language '{source_lang}' is not supported by the configured NLLB model ({NLLB_MODEL_ID}). "
            f"Supported languages: {', '.join(SUPPORTED_NLLB_LANGUAGES.keys())}",
        )

    output_lang = (payload.output_language or source_lang).strip()
    lang_meta = SUPPORTED_NLLB_LANGUAGES[source_lang]
    nllb_code = lang_meta["nllb_code"]

    raw_text = doc_dict.get("original_extracted_text") or doc_dict.get("english_canonical_text") or ""
    llm_cfg = get_global_llm_config()

    graph_state = await aexecute_sop_workflow(
        task_type="manual_language_override",
        conversation_id=conversation_id,
        input_payload={
            "raw_text": raw_text,
            "source_language": source_lang,
            "llm_config": {
                "llm_service_url": LLM_SERVICE_URL,
                "provider": llm_cfg["provider"],
                "model": llm_cfg["model"],
                "api_key": llm_cfg["api_key"],
            },
        },
    )
    if graph_state.get("errors"):
        c.close()
        err = graph_state["errors"][-1]
        raise HTTPException(err.get("error_status", 503), err.get("message", "LLM Service Unavailable"))

    inter = graph_state.get("intermediate_results", {})
    english_text = inter.get("english_canonical_text", raw_text)
    trans_meta = inter.get("translation_metadata", {})

    c.execute(
        """UPDATE sop_documents
           SET original_language=?, detected_language=?, nllb_language_code=?,
               translation_status=?, english_canonical_text=?, output_language=?
           WHERE id=? AND conversation_id=?""",
        (
            source_lang,
            source_lang,
            nllb_code,
            trans_meta.get("translation_status", "completed"),
            english_text,
            output_lang,
            document_id,
            conversation_id,
        ),
    )
    c.execute("DELETE FROM sop_similarity_cache WHERE conversation_id=?", (conversation_id,))
    c.commit()
    c.close()

    return {
        "status": "updated",
        "document_id": document_id,
        "detected_language": source_lang,
        "original_language": source_lang,
        "nllb_language_code": nllb_code,
        "output_language": output_lang,
        "translation_status": trans_meta.get("translation_status", "completed"),
        "translation_model": NLLB_MODEL_ID,
        "agent_trace": graph_state.get("agent_trace", []),
    }


def _enrich_harmonized_version_dict(d: dict, conversation_id: str) -> dict:
    """Standardizes all version attributes, action_type, URLs, output_language, and 6-dimension scores for harmonized SOP versions."""
    if "source_document_ids_json" in d and isinstance(d.get("source_document_ids_json"), str):
        d["source_document_ids"] = json.loads(d["source_document_ids_json"]) if d["source_document_ids_json"] else []
    elif "source_document_ids" not in d:
        d["source_document_ids"] = []

    if "source_filenames_json" in d and isinstance(d.get("source_filenames_json"), str):
        d["source_filenames"] = json.loads(d["source_filenames_json"]) if d["source_filenames_json"] else []
    elif "source_filenames" not in d:
        d["source_filenames"] = []

    if "sections_json" in d and isinstance(d.get("sections_json"), str):
        d["sections"] = json.loads(d["sections_json"]) if d["sections_json"] else []
    elif "sections" not in d:
        d["sections"] = []

    if "english_sections_json" in d and isinstance(d.get("english_sections_json"), str):
        d["english_sections"] = json.loads(d["english_sections_json"]) if d["english_sections_json"] else []
    elif "english_sections" not in d:
        d["english_sections"] = d.get("sections", [])

    if "detected_languages_json" in d and isinstance(d.get("detected_languages_json"), str):
        d["detected_languages"] = json.loads(d["detected_languages_json"]) if d["detected_languages_json"] else []
    elif "detected_languages" not in d:
        d["detected_languages"] = []

    if not d.get("output_language"):
        d["output_language"] = "English"

    if "scores_json" in d and isinstance(d.get("scores_json"), str):
        d["scores"] = json.loads(d["scores_json"]) if d["scores_json"] else {}
    elif "scores" not in d:
        d["scores"] = {}

    if "applied_recommendations_json" in d and isinstance(d.get("applied_recommendations_json"), str):
        d["applied_recommendations"] = json.loads(d["applied_recommendations_json"]) if d["applied_recommendations_json"] else []
    elif "applied_recommendations" not in d:
        d["applied_recommendations"] = []

    sc = d.get("scores") or {}
    ov = sc.get("overall_score") or sc.get("average_score") or d.get("overall_score") or 0
    sc["overall_score"] = ov
    sc["average_score"] = ov
    d["scores"] = sc

    d["overall_score"] = ov
    d["template_score"] = sc.get("template_score") or d.get("template_score", 0)
    d["readability_score"] = sc.get("readability_score") or d.get("readability_score", 0)
    d["quality_score"] = sc.get("quality_score") or d.get("quality_score", 0)
    d["kenvue_alignment_score"] = sc.get("alignment_score") or sc.get("kenvue_alignment_score") or d.get("kenvue_alignment_score", 0)
    d["completeness_score"] = sc.get("completeness_score") or d.get("completeness_score", 0)

    vt = d.get("version_type", "")
    if "harm" in vt or d.get("version_number") == 1:
        d["action_type"] = "harmonize"
    elif "simp" in vt:
        d["action_type"] = "simplify"
    elif "refin" in vt:
        d["action_type"] = "refine"
    else:
        d["action_type"] = "harmonize" if d.get("version_number") == 1 else "refine"

    d["preview_url"] = f"/conversations/{conversation_id}/harmonized-sop/versions/{d['id']}/preview"
    d["download_url"] = f"/conversations/{conversation_id}/harmonized-sop/versions/{d['id']}/download"
    return d


@app.get("/conversations/{conversation_id}/sop")
def get_conversation_sop(conversation_id: str):
    c = db()
    all_docs = c.execute(
        "SELECT * FROM sop_documents WHERE conversation_id=? ORDER BY created_at ASC",
        (conversation_id,),
    ).fetchall()

    if not all_docs:
        c.close()
        return {
            "has_sop": False,
            "document": None,
            "documents": [],
            "document_count": 0,
            "detected_languages": [],
            "available_output_languages": [],
            "artifacts_count": 0,
            "harmonized_versions_count": 0,
            "harmonized_versions": [],
        }

    artifacts = c.execute(
        "SELECT * FROM sop_artifacts WHERE conversation_id=? ORDER BY page ASC",
        (conversation_id,),
    ).fetchall()

    # Load all harmonized versions
    harm_rows = c.execute(
        "SELECT * FROM harmonized_sop_versions WHERE conversation_id=? ORDER BY version_number ASC",
        (conversation_id,),
    ).fetchall()

    harm_versions = [_enrich_harmonized_version_dict(dict(hr), conversation_id) for hr in harm_rows]

    parsed_docs = []
    for d_row in all_docs:
        d_dict = dict(d_row)
        det_lang = d_dict.get("detected_language") or d_dict.get("original_language") or "English"
        lang_meta = SUPPORTED_NLLB_LANGUAGES.get(det_lang, SUPPORTED_NLLB_LANGUAGES["English"])
        d_dict["detected_language"] = det_lang
        d_dict["original_language"] = d_dict.get("original_language") or det_lang
        d_dict["nllb_language_code"] = d_dict.get("nllb_language_code") or lang_meta["nllb_code"]
        d_dict["language_flag"] = lang_meta["flag"]
        d_dict["language_native_name"] = lang_meta["native_name"]
        d_dict["translation_status"] = d_dict.get("translation_status") or ("skipped_already_english" if det_lang == "English" else "completed")
        d_dict["translation_model"] = d_dict.get("translation_model") or NLLB_MODEL_ID
        d_dict["internal_processing_language"] = "English"
        d_dict["output_language"] = d_dict.get("output_language") or det_lang
        d_dict["processing_status"] = d_dict.get("processing_status") or "completed"
        d_dict["original_pdf_url"] = f"/conversations/{conversation_id}/sop/{d_dict['id']}/original-pdf"
        d_dict["scores"] = json.loads(d_dict["scores_json"]) if d_dict.get("scores_json") else None
        d_dict["optimized_scores"] = json.loads(d_dict["optimized_scores_json"]) if d_dict.get("optimized_scores_json") else None
        d_dict["optimized_sections"] = json.loads(d_dict["optimized_sections_json"]) if d_dict.get("optimized_sections_json") else None
        d_dict["optimized_english_sections"] = json.loads(d_dict["optimized_english_sections_json"]) if d_dict.get("optimized_english_sections_json") else None
        d_dict["optimized_title"] = d_dict.get("optimized_title")
        has_opt = bool(d_dict.get("optimized_pdf_object_name"))
        d_dict["has_optimized_sop"] = has_opt
        d_dict["pdf_download_url"] = (
            f"/conversations/{conversation_id}/optimized-sop/download?document_id={d_dict['id']}"
            if has_opt
            else None
        )
        d_dict["pdf_preview_url"] = (
            f"/conversations/{conversation_id}/optimized-sop/preview?document_id={d_dict['id']}"
            if has_opt
            else None
        )
        d_dict["skill_url"] = (
            f"/conversations/{conversation_id}/optimization-skill?document_id={d_dict['id']}"
            if has_opt
            else None
        )
        d_dict["optimization_report"] = (
            json.loads(d_dict["optimization_report_json"])
            if d_dict.get("optimization_report_json")
            else None
        )
        parsed_docs.append(d_dict)

    unique_detected_languages = get_unique_detected_languages(parsed_docs)
    detected_lang_names = [l["language"] for l in unique_detected_languages]

    # Similarity analysis cache or live computation
    sim_analysis = None
    if len(parsed_docs) > 1:
        cached_sim = c.execute(
            "SELECT analysis_json FROM sop_similarity_cache WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        if cached_sim and cached_sim["analysis_json"]:
            try:
                sim_analysis = json.loads(cached_sim["analysis_json"])
            except Exception:
                pass

        if not sim_analysis:
            meta_path = get_vector_store(conversation_id).meta_file
            all_child_chunks = []
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        all_child_chunks = json.load(f)
                except Exception:
                    pass

            doc_texts_map = {}
            for cc in all_child_chunks:
                did = cc.get("document_id")
                pid = cc.get("parent_id")
                if did not in doc_texts_map:
                    doc_texts_map[did] = {}
                doc_texts_map[did][pid] = cc.get("parent_text", "")

            sim_docs = []
            for d in parsed_docs:
                did = d["id"]
                p_texts = list(doc_texts_map.get(did, {}).values())
                sim_docs.append({
                    "id": did,
                    "document_id": did,
                    "filename": d["filename"],
                    "detected_language": d["detected_language"],
                    "original_language": d["original_language"],
                    "original_text": d.get("english_canonical_text") or "\n\n".join(p_texts),
                })

            sim_analysis = similarity_engine.analyze_collection(sim_docs, all_child_chunks)
            c.execute(
                "INSERT OR REPLACE INTO sop_similarity_cache (id, conversation_id, analysis_json, updated_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), conversation_id, json.dumps(sim_analysis), now()),
            )
            c.commit()

        if isinstance(sim_analysis, dict):
            sim_analysis["detected_languages"] = unique_detected_languages
            sim_analysis["available_output_languages"] = detected_lang_names
            sim_analysis["internal_processing_language"] = "English"

    c.close()

    # Primary document is the latest
    primary_doc = parsed_docs[-1]

    # Calculate collection composite scores if multiple documents exist
    if len(parsed_docs) > 1:
        avg_s = round(sum(d["scores"]["average_score"] for d in parsed_docs if d["scores"]) / len(parsed_docs))
        tmpl_s = round(sum(d["scores"]["template_score"] for d in parsed_docs if d["scores"]) / len(parsed_docs))
        read_s = round(sum(d["scores"]["readability_score"] for d in parsed_docs if d["scores"]) / len(parsed_docs))
        qual_s = round(sum(d["scores"]["quality_score"] for d in parsed_docs if d["scores"]) / len(parsed_docs))
        collection_scores = {
            "average_score": avg_s,
            "template_score": tmpl_s,
            "readability_score": read_s,
            "quality_score": qual_s,
            "summary": (
                f"Multilingual Multi-SOP Collection ({len(parsed_docs)} Documents | Languages: {', '.join(detected_lang_names)}). "
                f"All procedural vectors normalized to Canonical English via NLLB-200 and indexed in FAISS FlatIP vector store."
            ),
            "suggestions": primary_doc["scores"].get("suggestions", []) if primary_doc["scores"] else [],
        }
    else:
        collection_scores = primary_doc["scores"]

    return {
        "has_sop": True,
        "document": primary_doc,
        "documents": parsed_docs,
        "document_count": len(parsed_docs),
        "detected_languages": unique_detected_languages,
        "available_output_languages": detected_lang_names,
        "internal_processing_language": "English",
        "translation_model": NLLB_MODEL_ID,
        "collection_scores": collection_scores,
        "artifacts_count": len(artifacts),
        "images_count": len([a for a in artifacts if a["artifact_type"] == "image"]),
        "tables_count": len([a for a in artifacts if a["artifact_type"] == "table"]),
        "has_optimized_sop": any(bool(d.get("optimized_pdf_object_name")) for d in parsed_docs),
        "index_type": "FAISS IndexFlatIP (Exact Cosine Inner Product - Canonical English)",
        "similarity_analysis": sim_analysis,
        "harmonized_versions_count": len(harm_versions),
        "latest_harmonized_version": harm_versions[-1] if harm_versions else None,
        "harmonized_versions": harm_versions,
    }


@app.get("/conversations/{conversation_id}/artifacts")
def get_conversation_artifacts(conversation_id: str):
    c = db()
    rows = c.execute(
        "SELECT * FROM sop_artifacts WHERE conversation_id=? ORDER BY page ASC, created_at ASC",
        (conversation_id,),
    ).fetchall()
    c.close()

    result = []
    for r in rows:
        d = dict(r)
        d["preview_url"] = f"/artifacts/{d['id']}/file"
        if d.get("table_data_json"):
            try:
                td = json.loads(d["table_data_json"])
                d["table_data"] = td
                d["headers"] = td.get("headers", [])
                d["rows"] = td.get("rows", [])
                d["num_rows"] = td.get("num_rows", len(d["rows"]))
                d["num_cols"] = td.get("num_cols", len(d["headers"]))
            except Exception:
                pass
        elif d.get("table_markdown"):
            parsed = parse_markdown_table_lines(d["table_markdown"].split("\n"))
            if parsed:
                d["headers"] = parsed.get("header", [])
                d["rows"] = parsed.get("rows", [])
                d["num_rows"] = len(d["rows"])
                d["num_cols"] = len(d["headers"])
                d["table_data"] = {
                    "headers": d["headers"],
                    "rows": d["rows"],
                    "num_rows": d["num_rows"],
                    "num_cols": d["num_cols"],
                }
        result.append(d)
    return result


@app.get("/artifacts/{artifact_id}/file")
def get_artifact_file(artifact_id: str):
    c = db()
    row = c.execute("SELECT object_name, artifact_type FROM sop_artifacts WHERE id=?", (artifact_id,)).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Artifact not found")

    data, content_type = minio_storage.get_file_bytes(row["object_name"])
    if not data:
        raise HTTPException(404, "Artifact file not found in MinIO")

    return Response(content=data, media_type=content_type)


# =============================================================
# 5. SOP OPTIMIZATION & REPORTLAB GENERATION
# =============================================================
@app.post("/conversations/{conversation_id}/optimize-sop")
async def optimize_sop(
    conversation_id: str,
    payload: OptimizeRequest,
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    Applies the selected checkbox improvements + custom user instructions.
    Operates internally on the Canonical English representation of the SOP,
    then generates the final optimized SOP in the selected output_language
    (defaulting to the SOP's original detected language for single SOPs).
    """
    username = (x_username or "admin").strip().lower()
    c = db()
    if payload.document_id:
        doc = c.execute(
            "SELECT * FROM sop_documents WHERE id=? AND conversation_id=?",
            (payload.document_id, conversation_id),
        ).fetchone()
        if not doc:
            c.close()
            raise HTTPException(404, "Selected source SOP document not found in this conversation.")
    else:
        doc = c.execute(
            "SELECT * FROM sop_documents WHERE conversation_id=? ORDER BY created_at DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    if not doc:
        c.close()
        raise HTTPException(404, "No SOP document found for this conversation.")

    doc_dict = dict(doc)
    detected_lang = doc_dict.get("detected_language") or doc_dict.get("original_language") or "English"
    # Default output language for a single SOP is its original detected language unless overridden
    target_output_language = (
        payload.output_language
        or doc_dict.get("output_language")
        or detected_lang
        or "English"
    ).strip()

    artifacts_rows = c.execute(
        "SELECT * FROM sop_artifacts WHERE conversation_id=? AND (document_id=? OR document_id IS NULL) ORDER BY page ASC",
        (conversation_id, doc["id"]),
    ).fetchall()
    artifacts = [dict(r) for r in artifacts_rows]

    # Check for existing canonical English optimized sections to support iterative refinement ("Further Optimize")
    prior_sections = None
    if doc_dict.get("optimized_english_sections_json"):
        try:
            prior_sections = json.loads(doc_dict["optimized_english_sections_json"])
        except Exception:
            pass
    if not prior_sections and doc_dict.get("optimized_sections_json"):
        try:
            prior_sections = json.loads(doc_dict["optimized_sections_json"])
        except Exception:
            pass
    if not prior_sections:
        eng_obj_name = f"users/{username}/conversations/{conversation_id}/optimized_english_sections_{doc['id']}.json"
        prior_data, _ = minio_storage.get_file_bytes(eng_obj_name)
        if not prior_data:
            sections_obj_name = f"users/{username}/conversations/{conversation_id}/optimized_sections_{doc['id']}.json"
            prior_data, _ = minio_storage.get_file_bytes(sections_obj_name)
        if prior_data:
            try:
                prior_sections = json.loads(prior_data.decode("utf-8"))
            except Exception:
                pass

    is_iterative = bool(prior_sections and isinstance(prior_sections, list) and len(prior_sections) >= 3)

    # Always use Canonical English representation for internal AI optimization
    original_text = doc_dict.get("english_canonical_text") or doc_dict.get("original_extracted_text") or ""
    if not original_text.strip():
        c.close()
        raise HTTPException(422, "Original source evidence is unavailable; re-upload the SOP before optimization.")

    # Resolve baseline scores and available suggestions
    if is_iterative and doc_dict.get("optimized_scores_json"):
        try:
            baseline_scores = json.loads(doc_dict["optimized_scores_json"])
        except Exception:
            baseline_scores = json.loads(doc_dict["scores_json"]) if doc_dict.get("scores_json") else {}
    else:
        baseline_scores = json.loads(doc_dict["scores_json"]) if doc_dict.get("scores_json") else {}

    available_suggs = baseline_scores.get("suggestions", [])
    selected_suggs = [s for s in available_suggs if s.get("id") in payload.selected_suggestion_ids]
    if not selected_suggs and payload.selected_suggestion_ids:
        selected_suggs = [{"title": sid, "description": sid} for sid in payload.selected_suggestion_ids]

    prior_title = baseline_scores.get("english_title") or doc_dict.get("optimized_title")
    if not prior_title and prior_sections:
        for s in prior_sections:
            c_text = s.get("content", "")
            m_dt = re.search(r"Document Title:\s*([^\n\r]+)", c_text, re.IGNORECASE)
            if m_dt:
                prior_title = m_dt.group(1).strip()
                break
            m_p1 = re.search(r"(?:The purpose of this (?:procedure|Standard Operating Procedure)\s*\(([^)]+)\)|本標準作業手順書\s*\(([^)]+)\))", c_text)
            if m_p1:
                cand = (m_p1.group(1) or m_p1.group(2) or "").strip()
                if cand:
                    prior_title = cand
                    break
    if not prior_title:
        conv_row = c.execute("SELECT title FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if conv_row and conv_row["title"] and conv_row["title"].startswith("SOP: "):
            prior_title = conv_row["title"].replace("SOP: ", "").strip()

    c.close()
    llm_cfg = get_global_llm_config()
    provider = llm_cfg["provider"]
    model = llm_cfg["model"]
    api_key = llm_cfg["api_key"]

    # Execute LangGraph single_sop_optimization workflow:
    # Supervisor -> OptimizationAndHarmonizationAgent -> ValidationDecisionAgent -> RetrievalAgent (FAISS re-index) -> FinalResponse
    opt_graph_state = await aexecute_sop_workflow(
        task_type="single_sop_optimization",
        conversation_id=conversation_id,
        username=username,
        input_payload={
            "doc_id": doc["id"],
            "document_id": doc["id"],
            "filename": doc["filename"],
            "original_text": original_text,
            "original_filename": doc["filename"],
            "selected_suggestions": selected_suggs,
            "custom_instructions": payload.custom_instructions,
            "artifacts": artifacts,
            "existing_sections": prior_sections if is_iterative else None,
            "existing_title": prior_title if is_iterative else None,
            "output_language": target_output_language,
            "previous_scores": baseline_scores,
            "llm_config": {
                "llm_service_url": LLM_SERVICE_URL,
                "provider": "azure_openai",
                "model": model,
                "api_key": api_key,
            },
        },
    )

    opt_errors = opt_graph_state.get("errors", [])
    if opt_errors:
        err = opt_errors[-1]
        raise HTTPException(err.get("error_status", 500), err.get("message", "Optimization failed"))

    opt_result = opt_graph_state.get("intermediate_results", {}).get("optimization_result", {})

    c = db()
    new_doc_title = opt_result.get("document_title")
    final_output_lang = opt_result.get("output_language", target_output_language)
    if new_doc_title:
        c.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            (f"SOP: {new_doc_title}", now(), conversation_id),
        )

    # Build comprehensive audit report dict for persistent cross-tab switching
    opt_report = {
        "artifact_version_id": opt_result.get("artifact_version_id"),
        "document_title": new_doc_title,
        "title": new_doc_title,
        "optimized_title": new_doc_title,
        "original_language": doc_dict.get("original_language") or detected_lang,
        "detected_language": detected_lang,
        "internal_processing_language": "English",
        "output_language": final_output_lang,
        "translation_metadata": opt_result.get("translation_metadata"),
        "is_iterative": is_iterative,
        "previous_scores": baseline_scores,
        "updated_scores": opt_result.get("updated_scores"),
        "before_and_after_comparison": opt_result.get("before_and_after_comparison"),
        "score_difference": opt_result.get("score_difference", 0),
        "resolved_violations": opt_result.get("resolved_violations", []),
        "newly_introduced_violations": opt_result.get("newly_introduced_violations", []),
        "validation_report": opt_result.get("validation_report"),
        "summary": opt_result.get("summary", ""),
        "skill_object_name": opt_result.get("skill_object_name"),
    }

    # Save updated scores, optimized PDF object name, localized sections JSON, canonical English sections JSON, output_language, title, and report
    c.execute(
        """UPDATE sop_documents 
           SET optimized_scores_json=?, optimized_pdf_object_name=?, optimized_sections_json=?,
               optimized_english_sections_json=?, optimized_title=?, output_language=?,
               optimization_report_json=?
           WHERE id=?""",
        (
            json.dumps(opt_result["updated_scores"]),
            opt_result["object_name"],
            json.dumps(opt_result.get("sections", [])),
            json.dumps(opt_result.get("english_sections", opt_result.get("sections", []))),
            new_doc_title,
            final_output_lang,
            json.dumps(opt_report),
            doc["id"],
        ),
    )
    c.commit()
    c.close()

    return {
        "status": "success",
        "artifact_version_id": opt_result.get("artifact_version_id"),
        "document_id": doc["id"],
        "document_title": new_doc_title,
        "title": new_doc_title,
        "optimized_title": new_doc_title,
        "original_language": doc_dict.get("original_language") or detected_lang,
        "detected_language": detected_lang,
        "internal_processing_language": "English",
        "output_language": final_output_lang,
        "translation_metadata": opt_result.get("translation_metadata"),
        "is_iterative": is_iterative,
        "previous_scores": baseline_scores,
        "updated_scores": opt_result["updated_scores"],
        "before_and_after_comparison": opt_result.get("before_and_after_comparison"),
        "score_difference": opt_result.get("score_difference", 0),
        "resolved_violations": opt_result.get("resolved_violations", []),
        "newly_introduced_violations": opt_result.get("newly_introduced_violations", []),
        "validation_report": opt_result.get("validation_report"),
        "pdf_download_url": f"/conversations/{conversation_id}/optimized-sop/download?document_id={doc['id']}",
        "pdf_preview_url": f"/conversations/{conversation_id}/optimized-sop/preview?document_id={doc['id']}",
        "skill_url": f"/conversations/{conversation_id}/optimization-skill?document_id={doc['id']}",
        "skill_object_name": opt_result.get("skill_object_name"),
        "summary": opt_result["summary"],
        "agent_trace": opt_graph_state.get("agent_trace", []),
    }


@app.get("/conversations/{conversation_id}/optimized-sop/download")
def download_optimized_sop(conversation_id: str, document_id: Optional[str] = None):
    c = db()
    if document_id:
        doc = c.execute(
            "SELECT id, optimized_pdf_object_name, filename FROM sop_documents WHERE conversation_id=? AND id=? AND optimized_pdf_object_name IS NOT NULL",
            (conversation_id, document_id),
        ).fetchone()
    else:
        doc = c.execute(
            "SELECT id, optimized_pdf_object_name, filename FROM sop_documents WHERE conversation_id=? AND optimized_pdf_object_name IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    c.close()
    if not doc or not doc["optimized_pdf_object_name"]:
        raise HTTPException(404, "No optimized SOP PDF generated yet.")

    data, content_type = minio_storage.get_file_bytes(doc["optimized_pdf_object_name"])
    if not data:
        # Check fallback
        fallback_obj = f"users/admin/conversations/{conversation_id}/optimized_sop.pdf"
        data, content_type = minio_storage.get_file_bytes(fallback_obj)
        if not data:
            raise HTTPException(404, "Optimized PDF not found in storage.")

    header_val = _build_safe_content_disposition(
        "attachment",
        f"Optimized_{doc['filename']}",
        fallback_base="Optimized_SOP",
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": header_val},
    )


@app.get("/conversations/{conversation_id}/optimized-sop/preview")
def preview_optimized_sop(conversation_id: str, document_id: Optional[str] = None):
    c = db()
    if document_id:
        doc = c.execute(
            "SELECT id, optimized_pdf_object_name, filename FROM sop_documents WHERE conversation_id=? AND id=? AND optimized_pdf_object_name IS NOT NULL",
            (conversation_id, document_id),
        ).fetchone()
    else:
        doc = c.execute(
            "SELECT id, optimized_pdf_object_name, filename FROM sop_documents WHERE conversation_id=? AND optimized_pdf_object_name IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    c.close()
    if not doc or not doc["optimized_pdf_object_name"]:
        raise HTTPException(404, "No optimized SOP PDF generated yet.")

    data, content_type = minio_storage.get_file_bytes(doc["optimized_pdf_object_name"])
    if not data:
        # Check fallback
        fallback_obj = f"users/admin/conversations/{conversation_id}/optimized_sop.pdf"
        data, content_type = minio_storage.get_file_bytes(fallback_obj)
        if not data:
            raise HTTPException(404, "Optimized PDF not found in storage.")

    header_val = _build_safe_content_disposition(
        "inline",
        f"Optimized_{doc['filename'] if 'filename' in doc.keys() and doc['filename'] else 'SOP.pdf'}",
        fallback_base="Optimized_SOP",
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": header_val},
    )


@app.get("/conversations/{conversation_id}/sop/{document_id}/optimized-pdf")
def get_document_optimized_pdf(conversation_id: str, document_id: str):
    """Direct route to preview a specific SOP's optimized PDF."""
    return preview_optimized_sop(conversation_id=conversation_id, document_id=document_id)


@app.get("/conversations/{conversation_id}/sop/{document_id}/optimized-pdf/download")
def download_document_optimized_pdf(conversation_id: str, document_id: str):
    """Direct route to download a specific SOP's optimized PDF."""
    return download_optimized_sop(conversation_id=conversation_id, document_id=document_id)


@app.get("/conversations/{conversation_id}/optimization-skill")
def get_conversation_optimization_skill(
    conversation_id: str,
    document_id: Optional[str] = None,
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    Returns the dynamically compiled Optimization Directive & Skill Recipe
    for this chat session (or specific document) from storage.
    """
    username = (x_username or "admin").strip().lower()
    data = None
    if document_id:
        safe_id = re.sub(r"[^\w\-]", "_", str(document_id))
        doc_skill_obj = f"users/{username}/conversations/{conversation_id}/optimization_skill_{safe_id}.md"
        data, _ = minio_storage.get_file_bytes(doc_skill_obj)
    if not data:
        skill_object = f"users/{username}/conversations/{conversation_id}/optimization_skill.md"
        data, _ = minio_storage.get_file_bytes(skill_object)
    if not data:
        raise HTTPException(404, "Optimization skill file not found in storage for this session.")

    return Response(content=data, media_type="text/markdown; charset=utf-8")


@app.get("/skills/audit")
def get_master_audit_skill():
    """Returns the Master Kenvue SOP Audit & Scoring Skill markdown."""
    from skill_manager import skill_manager
    content = skill_manager.get_audit_skill()
    return {"skill": "kenvue_audit_skill.md", "content": content}


# =============================================================
# 5B. MULTI-SOP SIMILARITY, HARMONIZATION, & SIMPLIFICATION WORKFLOW
# =============================================================
@app.get("/conversations/{conversation_id}/similarity-analysis")
def get_similarity_analysis(conversation_id: str):
    """
    Performs or retrieves multi-SOP pairwise similarity, procedural overlap,
    parameter conflict analysis, and similarity clustering for uploaded SOPs
    using their Canonical English representations. Also returns the deduplicated
    list of unique detected source languages for output language selection.
    """
    c = db()
    all_docs_rows = c.execute(
        "SELECT * FROM sop_documents WHERE conversation_id=? ORDER BY created_at ASC",
        (conversation_id,),
    ).fetchall()
    all_docs = [dict(d) for d in all_docs_rows]
    unique_detected_languages = get_unique_detected_languages(all_docs)
    detected_lang_names = [l["language"] for l in unique_detected_languages]

    if len(all_docs) < 2:
        c.close()
        return {
            "has_similarity_analysis": False,
            "document_count": len(all_docs),
            "detected_languages": unique_detected_languages,
            "available_output_languages": detected_lang_names,
            "internal_processing_language": "English",
            "analysis": {
                "groups": [],
                "pairwise_matrix": [],
                "executive_summary": "Single SOP uploaded. Upload additional SOPs to enable multi-document similarity analysis and harmonization.",
                "has_duplicates_or_overlaps": False,
                "recommended_harmonize_ids": [],
                "detected_languages": unique_detected_languages,
                "available_output_languages": detected_lang_names,
            },
        }

    # Check cache first
    cached = c.execute(
        "SELECT analysis_json FROM sop_similarity_cache WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    if cached and cached["analysis_json"]:
        c.close()
        try:
            analysis_data = json.loads(cached["analysis_json"])
            if isinstance(analysis_data, dict):
                analysis_data["detected_languages"] = unique_detected_languages
                analysis_data["available_output_languages"] = detected_lang_names
                analysis_data["internal_processing_language"] = "English"
            res = {
                "has_similarity_analysis": True,
                "document_count": len(all_docs),
                "detected_languages": unique_detected_languages,
                "available_output_languages": detected_lang_names,
                "internal_processing_language": "English",
                "analysis": analysis_data,
            }
            if isinstance(analysis_data, dict):
                res.update(analysis_data)
            return res
        except Exception:
            pass

    # Read child chunks from FAISS metadata
    meta_path = get_vector_store(conversation_id).meta_file
    all_child_chunks = []
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                all_child_chunks = json.load(f)
        except Exception as e:
            logger.warning("Could not read meta chunks: %s", e)

    doc_texts_map = {}
    for cc in all_child_chunks:
        did = cc.get("document_id")
        pid = cc.get("parent_id")
        if did not in doc_texts_map:
            doc_texts_map[did] = {}
        doc_texts_map[did][pid] = cc.get("parent_text", "")

    sim_docs = []
    for d in all_docs:
        did = d["id"]
        p_texts = list(doc_texts_map.get(did, {}).values())
        sim_docs.append({
            "id": did,
            "document_id": did,
            "filename": d["filename"],
            "detected_language": d.get("detected_language") or "English",
            "original_language": d.get("original_language") or "English",
            "original_text": d.get("english_canonical_text") or "\n\n".join(p_texts),
        })

    sim_state = execute_sop_workflow(
        task_type="similarity_analysis",
        conversation_id=conversation_id,
        input_payload={
            "all_child_chunks": all_child_chunks,
            "unique_detected_languages": unique_detected_languages,
        },
        documents=sim_docs,
    )
    analysis_result = sim_state.get("intermediate_results", {}).get("similarity_analysis", {})
    if isinstance(analysis_result, dict):
        analysis_result["detected_languages"] = unique_detected_languages
        analysis_result["available_output_languages"] = detected_lang_names
        analysis_result["internal_processing_language"] = "English"

    c = db()
    c.execute(
        "INSERT OR REPLACE INTO sop_similarity_cache (id, conversation_id, analysis_json, updated_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), conversation_id, json.dumps(analysis_result), now()),
    )
    c.commit()
    c.close()

    res = {
        "has_similarity_analysis": True,
        "document_count": len(all_docs),
        "detected_languages": unique_detected_languages,
        "available_output_languages": detected_lang_names,
        "internal_processing_language": "English",
        "analysis": analysis_result,
        "agent_trace": sim_state.get("agent_trace", []),
    }
    if isinstance(analysis_result, dict):
        res.update(analysis_result)
    return res


@app.post("/conversations/{conversation_id}/harmonize-sops")
async def harmonize_sops(
    conversation_id: str,
    payload: HarmonizeRequest,
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    Intelligently consolidates selected similar SOPs into a single standardized Kenvue SOP
    via the LangGraph `multi_sop_harmonization` workflow:
    - Operates internally on the Canonical English representation of all selected SOPs
    - Resolves procedural divergences to conservative GMP tolerances
    - Eliminates redundant steps while preserving unique rules and media assets
    - Generates the final Harmonized SOP in the user-selected output_language via NLLB-200
    - Stores harmonized SOP v1 permanently in SQLite and storage with full lineage.
    """
    username = (x_username or "admin").strip().lower()
    if not payload.selected_document_ids or len(payload.selected_document_ids) < 2:
        raise HTTPException(400, "Please select at least 2 SOP documents to harmonize.")

    c = db()
    all_docs = c.execute(
        "SELECT * FROM sop_documents WHERE conversation_id=?",
        (conversation_id,),
    ).fetchall()

    selected_docs = [
        dict(d) for d in all_docs
        if d["id"] in payload.selected_document_ids or d["filename"] in payload.selected_document_ids
    ]

    if len(selected_docs) < 2:
        c.close()
        raise HTTPException(400, "Could not find at least 2 matching SOP documents to harmonize.")

    unique_detected_languages = get_unique_detected_languages(selected_docs)
    target_output_language = (
        payload.output_language
        or (unique_detected_languages[0]["language"] if unique_detected_languages else "English")
    ).strip()

    meta_path = get_vector_store(conversation_id).meta_file
    all_child_chunks = []
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                all_child_chunks = json.load(f)
        except Exception as e:
            logger.warning("Could not load chunks: %s", e)

    doc_texts_map = {}
    for cc in all_child_chunks:
        did = cc.get("document_id")
        pid = cc.get("parent_id")
        if did not in doc_texts_map:
            doc_texts_map[did] = {}
        doc_texts_map[did][pid] = cc.get("parent_text", "")

    source_documents = []
    for d in selected_docs:
        did = d["id"]
        p_texts = list(doc_texts_map.get(did, {}).values())
        canonical_eng = d.get("english_canonical_text") or "\n\n".join(p_texts)
        source_documents.append({
            "id": did,
            "document_id": did,
            "filename": d["filename"],
            "original_language": d.get("original_language") or d.get("detected_language") or "English",
            "detected_language": d.get("detected_language") or d.get("original_language") or "English",
            "nllb_language_code": d.get("nllb_language_code") or "eng_Latn",
            "english_canonical_text": canonical_eng,
            "original_text": canonical_eng,
            "scores": json.loads(d["scores_json"]) if d.get("scores_json") else None,
        })

    # Fetch artifacts for selected documents
    doc_ids = [d["id"] for d in selected_docs]
    placeholders = ",".join(["?"] * len(doc_ids))
    artifacts_rows = c.execute(
        f"SELECT * FROM sop_artifacts WHERE conversation_id=? AND document_id IN ({placeholders}) ORDER BY page ASC",
        (conversation_id, *doc_ids),
    ).fetchall()
    all_artifacts = [dict(r) for r in artifacts_rows]

    # Resolve global Admin LLM configuration
    c.close()
    llm_cfg = get_global_llm_config()
    provider = llm_cfg["provider"]
    model = llm_cfg["model"]
    api_key = llm_cfg["api_key"]

    harm_graph_state = await aexecute_sop_workflow(
        task_type="multi_sop_harmonization",
        conversation_id=conversation_id,
        username=username,
        input_payload={
            "source_documents": source_documents,
            "custom_instructions": payload.custom_instructions,
            "title_override": payload.title_override,
            "all_artifacts": all_artifacts,
            "output_language": target_output_language,
            "llm_config": {
                "llm_service_url": LLM_SERVICE_URL,
                "provider": "azure_openai",
                "model": model,
                "api_key": api_key,
            },
        },
    )

    harm_errors = harm_graph_state.get("errors", [])
    if harm_errors:
        err = harm_errors[-1]
        err_msg = err.get("message") or "Harmonization process failed"
        raise HTTPException(err.get("error_status", 503), err_msg)

    harm_result = harm_graph_state.get("intermediate_results", {}).get("harmonization_result", {})

    c = db()
    existing_versions = c.execute(
        "SELECT COALESCE(MAX(version_number), COUNT(*)) as max_v FROM harmonized_sop_versions WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    v_num = (existing_versions["max_v"] or 0) + 1
    final_lang = harm_result.get("output_language", target_output_language)
    harm_result["version_number"] = v_num
    harm_result["version_label"] = f"Harmonized SOP v{v_num} (Initial Harmonized Release - {final_lang})"

    # Persist version immutably with output_language, detected_languages_json, and english_sections_json
    c.execute(
        """INSERT INTO harmonized_sop_versions (
            id, conversation_id, username, version_number, version_label, version_type,
            parent_version_id, source_document_ids_json, source_filenames_json,
            title, output_language, detected_languages_json, markdown_content,
            sections_json, english_sections_json, scores_json, change_summary,
            applied_recommendations_json, user_prompt, pdf_object_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            harm_result["id"],
            conversation_id,
            username,
            harm_result["version_number"],
            harm_result["version_label"],
            harm_result["version_type"],
            harm_result["parent_version_id"],
            json.dumps(harm_result["source_document_ids"]),
            json.dumps(harm_result["source_filenames"]),
            harm_result["title"],
            final_lang,
            json.dumps(harm_result.get("detected_languages", unique_detected_languages)),
            harm_result["markdown_content"],
            json.dumps(harm_result["sections"]),
            json.dumps(harm_result.get("english_sections", harm_result["sections"])),
            json.dumps(harm_result["scores"]),
            harm_result["change_summary"],
            json.dumps(harm_result.get("applied_recommendations", [])),
            harm_result.get("user_prompt", ""),
            harm_result["pdf_object_name"],
            now(),
        ),
    )
    c.commit()
    c.close()

    enriched = _enrich_harmonized_version_dict(harm_result, conversation_id)
    enriched["agent_trace"] = harm_graph_state.get("agent_trace", [])
    return enriched


@app.get("/conversations/{conversation_id}/harmonized-sop/versions")
def get_harmonized_versions(conversation_id: str):
    """Returns complete version history and lineage of all harmonized SOPs for this session."""
    c = db()
    rows = c.execute(
        "SELECT * FROM harmonized_sop_versions WHERE conversation_id=? ORDER BY version_number ASC",
        (conversation_id,),
    ).fetchall()
    c.close()

    return [_enrich_harmonized_version_dict(dict(r), conversation_id) for r in rows]


@app.get("/conversations/{conversation_id}/harmonized-sop/versions/{version_id}")
def get_harmonized_version_by_id(conversation_id: str, version_id: str):
    """Retrieves full details for a specific harmonized SOP version."""
    c = db()
    row = c.execute(
        "SELECT * FROM harmonized_sop_versions WHERE id=? AND conversation_id=?",
        (version_id, conversation_id),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Harmonized SOP version not found")

    return _enrich_harmonized_version_dict(dict(row), conversation_id)


@app.get("/conversations/{conversation_id}/harmonized-sop/simplification-suggestions")
def get_simplification_suggestions(conversation_id: str):
    """Returns available simplification recommendations catalog with descriptions and benefits."""
    return {"catalog": SIMPLIFICATION_CATALOG}


@app.post("/conversations/{conversation_id}/harmonized-sop/simplify")
async def simplify_harmonized_sop(
    conversation_id: str,
    payload: SimplifyRequest,
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    Applies user-selected simplification recommendations on the Canonical English
    representation and generates a NEW version in the selected output_language
    (e.g., Harmonized SOP v2) via the LangGraph `harmonized_sop_simplify` workflow.
    NEVER overwrites previous versions!
    """
    username = (x_username or "admin").strip().lower()
    c = db()
    if payload.version_id:
        v_row = c.execute(
            "SELECT * FROM harmonized_sop_versions WHERE id=? AND conversation_id=?",
            (payload.version_id, conversation_id),
        ).fetchone()
    else:
        v_row = c.execute(
            "SELECT * FROM harmonized_sop_versions WHERE conversation_id=? ORDER BY version_number DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()

    if not v_row:
        c.close()
        raise HTTPException(404, "No harmonized SOP version found to simplify.")

    max_v_row = c.execute(
        "SELECT COALESCE(MAX(version_number), COUNT(*)) as max_v FROM harmonized_sop_versions WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    next_version_number = (max_v_row["max_v"] or 0) + 1

    v_dict = dict(v_row)
    current_version = {
        "id": v_dict["id"],
        "conversation_id": v_dict["conversation_id"],
        "version_number": v_dict["version_number"],
        "next_version_number": next_version_number,
        "version_label": v_dict["version_label"],
        "source_document_ids": json.loads(v_dict["source_document_ids_json"]),
        "source_filenames": json.loads(v_dict["source_filenames_json"]),
        "title": v_dict["title"],
        "output_language": v_dict.get("output_language") or "English",
        "detected_languages": json.loads(v_dict["detected_languages_json"]) if v_dict.get("detected_languages_json") else [],
        "sections": json.loads(v_dict["sections_json"]),
        "english_sections": json.loads(v_dict["english_sections_json"]) if v_dict.get("english_sections_json") else json.loads(v_dict["sections_json"]),
        "scores": json.loads(v_dict["scores_json"]),
        "pdf_object_name": v_dict["pdf_object_name"],
    }

    artifacts_rows = c.execute(
        "SELECT * FROM sop_artifacts WHERE conversation_id=? ORDER BY page ASC",
        (conversation_id,),
    ).fetchall()
    all_artifacts = [dict(r) for r in artifacts_rows]
    c.close()

    llm_cfg = get_global_llm_config()
    rec_ids = payload.selected_recommendation_ids
    if not rec_ids:
        rec_ids = [r["id"] for r in SIMPLIFICATION_CATALOG]

    simp_state = await aexecute_sop_workflow(
        task_type="harmonized_sop_simplify",
        conversation_id=conversation_id,
        username=username,
        input_payload={
            "current_version": current_version,
            "selected_recommendation_ids": rec_ids,
            "custom_instructions": payload.custom_instructions,
            "all_artifacts": all_artifacts,
            "output_language": payload.output_language or current_version["output_language"],
            "llm_config": {
                "llm_service_url": LLM_SERVICE_URL,
                "provider": llm_cfg["provider"],
                "model": llm_cfg["model"],
                "api_key": llm_cfg["api_key"],
            },
        },
    )
    simp_errors = simp_state.get("errors", [])
    if simp_errors:
        err = simp_errors[-1]
        raise HTTPException(err.get("error_status", 500), err.get("message", "Simplification failed"))

    new_v = simp_state.get("intermediate_results", {}).get("harmonization_result", {})

    c = db()
    c.execute(
        """INSERT INTO harmonized_sop_versions (
            id, conversation_id, username, version_number, version_label, version_type,
            parent_version_id, source_document_ids_json, source_filenames_json,
            title, output_language, detected_languages_json, markdown_content,
            sections_json, english_sections_json, scores_json, change_summary,
            applied_recommendations_json, user_prompt, pdf_object_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_v["id"],
            conversation_id,
            username,
            new_v["version_number"],
            new_v["version_label"],
            new_v["version_type"],
            new_v["parent_version_id"],
            json.dumps(new_v["source_document_ids"]),
            json.dumps(new_v["source_filenames"]),
            new_v["title"],
            new_v.get("output_language", "English"),
            json.dumps(new_v.get("detected_languages", [])),
            new_v["markdown_content"],
            json.dumps(new_v["sections"]),
            json.dumps(new_v.get("english_sections", new_v["sections"])),
            json.dumps(new_v["scores"]),
            new_v["change_summary"],
            json.dumps(new_v["applied_recommendations"]),
            new_v["user_prompt"],
            new_v["pdf_object_name"],
            now(),
        ),
    )
    c.commit()
    c.close()

    enriched = _enrich_harmonized_version_dict(new_v, conversation_id)
    enriched["agent_trace"] = simp_state.get("agent_trace", [])
    return enriched


@app.post("/conversations/{conversation_id}/harmonized-sop/refine")
async def refine_harmonized_sop(
    conversation_id: str,
    payload: RefineRequest,
    x_username: Optional[str] = Header(None, alias="X-User-Name"),
):
    """
    Applies user's interactive refinement prompt on the Canonical English representation
    and creates a NEW harmonized SOP version in the selected output_language (e.g., v3)
    via the LangGraph `harmonized_sop_refine` workflow. Preserves lineage and history!
    """
    username = (x_username or "admin").strip().lower()
    c = db()
    if payload.version_id:
        v_row = c.execute(
            "SELECT * FROM harmonized_sop_versions WHERE id=? AND conversation_id=?",
            (payload.version_id, conversation_id),
        ).fetchone()
    else:
        v_row = c.execute(
            "SELECT * FROM harmonized_sop_versions WHERE conversation_id=? ORDER BY version_number DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()

    if not v_row:
        c.close()
        raise HTTPException(404, "No harmonized SOP version found to refine.")

    max_v_row = c.execute(
        "SELECT COALESCE(MAX(version_number), COUNT(*)) as max_v FROM harmonized_sop_versions WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    next_version_number = (max_v_row["max_v"] or 0) + 1

    v_dict = dict(v_row)
    current_version = {
        "id": v_dict["id"],
        "conversation_id": v_dict["conversation_id"],
        "version_number": v_dict["version_number"],
        "next_version_number": next_version_number,
        "version_label": v_dict["version_label"],
        "source_document_ids": json.loads(v_dict["source_document_ids_json"]),
        "source_filenames": json.loads(v_dict["source_filenames_json"]),
        "title": v_dict["title"],
        "output_language": v_dict.get("output_language") or "English",
        "detected_languages": json.loads(v_dict["detected_languages_json"]) if v_dict.get("detected_languages_json") else [],
        "sections": json.loads(v_dict["sections_json"]),
        "english_sections": json.loads(v_dict["english_sections_json"]) if v_dict.get("english_sections_json") else json.loads(v_dict["sections_json"]),
        "scores": json.loads(v_dict["scores_json"]),
        "pdf_object_name": v_dict["pdf_object_name"],
    }

    artifacts_rows = c.execute(
        "SELECT * FROM sop_artifacts WHERE conversation_id=? ORDER BY page ASC",
        (conversation_id,),
    ).fetchall()
    all_artifacts = [dict(r) for r in artifacts_rows]
    c.close()

    llm_cfg = get_global_llm_config()
    ref_state = await aexecute_sop_workflow(
        task_type="harmonized_sop_refine",
        conversation_id=conversation_id,
        username=username,
        input_payload={
            "current_version": current_version,
            "refinement_prompt": payload.refinement_prompt,
            "all_artifacts": all_artifacts,
            "output_language": payload.output_language or current_version["output_language"],
            "llm_config": {
                "llm_service_url": LLM_SERVICE_URL,
                "provider": llm_cfg["provider"],
                "model": llm_cfg["model"],
                "api_key": llm_cfg["api_key"],
            },
        },
    )
    ref_errors = ref_state.get("errors", [])
    if ref_errors:
        err = ref_errors[-1]
        raise HTTPException(err.get("error_status", 500), err.get("message", "Refinement failed"))

    new_v = ref_state.get("intermediate_results", {}).get("harmonization_result", {})

    c = db()
    c.execute(
        """INSERT INTO harmonized_sop_versions (
            id, conversation_id, username, version_number, version_label, version_type,
            parent_version_id, source_document_ids_json, source_filenames_json,
            title, output_language, detected_languages_json, markdown_content,
            sections_json, english_sections_json, scores_json, change_summary,
            applied_recommendations_json, user_prompt, pdf_object_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_v["id"],
            conversation_id,
            username,
            new_v["version_number"],
            new_v["version_label"],
            new_v["version_type"],
            new_v["parent_version_id"],
            json.dumps(new_v["source_document_ids"]),
            json.dumps(new_v["source_filenames"]),
            new_v["title"],
            new_v.get("output_language", "English"),
            json.dumps(new_v.get("detected_languages", [])),
            new_v["markdown_content"],
            json.dumps(new_v["sections"]),
            json.dumps(new_v.get("english_sections", new_v["sections"])),
            json.dumps(new_v["scores"]),
            new_v["change_summary"],
            json.dumps(new_v["applied_recommendations"]),
            new_v["user_prompt"],
            new_v["pdf_object_name"],
            now(),
        ),
    )
    c.commit()
    c.close()

    enriched = _enrich_harmonized_version_dict(new_v, conversation_id)
    enriched["agent_trace"] = ref_state.get("agent_trace", [])
    return enriched


@app.get("/conversations/{conversation_id}/harmonized-sop/versions/{version_id}/preview")
def preview_harmonized_version_pdf(conversation_id: str, version_id: str):
    """Previews the PDF for a specific harmonized version."""
    c = db()
    row = c.execute(
        "SELECT * FROM harmonized_sop_versions WHERE id=? AND conversation_id=?",
        (version_id, conversation_id),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Harmonized SOP version not found")

    pdf_data, content_type = minio_storage.get_file_bytes(row["pdf_object_name"])
    if not pdf_data:
        raise HTTPException(404, "PDF file not found in storage")

    fname = f"Harmonized_SOP_v{row['version_number']}_{row['title'] or 'SOP'}.pdf"
    header_val = _build_safe_content_disposition(
        "inline",
        fname,
        fallback_base=f"Harmonized_SOP_v{row['version_number']}",
    )
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": header_val},
    )


@app.get("/conversations/{conversation_id}/harmonized-sop/versions/{version_id}/download")
def download_harmonized_version_pdf(conversation_id: str, version_id: str):
    """Downloads the PDF for a specific harmonized version."""
    c = db()
    row = c.execute(
        "SELECT * FROM harmonized_sop_versions WHERE id=? AND conversation_id=?",
        (version_id, conversation_id),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Harmonized SOP version not found")

    pdf_data, content_type = minio_storage.get_file_bytes(row["pdf_object_name"])
    if not pdf_data:
        raise HTTPException(404, "PDF file not found in storage")

    fname = f"Harmonized_SOP_v{row['version_number']}_{row['title'] or 'SOP'}.pdf"
    header_val = _build_safe_content_disposition(
        "attachment",
        fname,
        fallback_base=f"Harmonized_SOP_v{row['version_number']}",
    )
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": header_val},
    )


# =============================================================
# 6. END CHAT & LIFECYCLE CLEANUP
# =============================================================
@app.post("/conversations/{conversation_id}/end-chat")
async def end_chat(conversation_id: str, x_username: Optional[str] = Header(None, alias="X-User-Name")):
    """
    Concludes the session while strictly preserving all version lineage:
    1. Archives comprehensive summary of chat, SOPs, and Harmonized Version history to MinIO.
    2. Retains all generated Harmonized SOP PDFs and SQLite version records permanently.
    3. Cleans up temporary intermediate image/table crops and vector index files.
    """
    username = (x_username or "admin").strip().lower()
    c = db()
    conv = c.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not conv:
        c.close()
        raise HTTPException(404, "Conversation not found")

    messages = c.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
        (conversation_id,),
    ).fetchall()

    all_docs = c.execute(
        "SELECT * FROM sop_documents WHERE conversation_id=? ORDER BY created_at ASC",
        (conversation_id,),
    ).fetchall()

    harm_versions = c.execute(
        "SELECT * FROM harmonized_sop_versions WHERE conversation_id=? ORDER BY version_number ASC",
        (conversation_id,),
    ).fetchall()

    artifacts = c.execute(
        "SELECT object_name FROM sop_artifacts WHERE conversation_id=?",
        (conversation_id,),
    ).fetchall()

    # Step 1: Generate comprehensive summary with full lineage
    summary_text = (
        f"KENVUE SOP OPTIMIZATION SESSION SUMMARY\n"
        f"=======================================\n"
        f"User: {username}\n"
        f"Conversation ID: {conversation_id}\n"
        f"Title: {conv['title']}\n"
        f"Date: {now()}\n"
        f"Total SOPs Uploaded: {len(all_docs)}\n"
    )
    for i, d in enumerate(all_docs):
        d_scores = json.loads(d["scores_json"]) if d["scores_json"] else {}
        opt_s = json.loads(d["optimized_scores_json"]) if d["optimized_scores_json"] else None
        summary_text += f"\n[SOP {i+1}]: {d['filename']} (Pages: {d['page_count']})\n"
        summary_text += f"  Initial Scores: Template: {d_scores.get('template_score')}, Readability: {d_scores.get('readability_score')}, Quality: {d_scores.get('quality_score')}, Avg: {d_scores.get('average_score')}%\n"
        if opt_s:
            summary_text += f"  Optimized Scores: Template: {opt_s.get('template_score')}, Readability: {opt_s.get('readability_score')}, Quality: {opt_s.get('quality_score')}, Avg: {opt_s.get('average_score')}%\n"

    if harm_versions:
        summary_text += f"\n--- HARMONIZED SOP VERSION HISTORY & LINEAGE ---\n"
        summary_text += f"Total Harmonized Versions Generated: {len(harm_versions)}\n"
        for hv in harm_versions:
            v_scores = json.loads(hv["scores_json"]) if hv["scores_json"] else {}
            v_sources = json.loads(hv["source_filenames_json"]) if hv["source_filenames_json"] else []
            v_recs = json.loads(hv["applied_recommendations_json"]) if hv["applied_recommendations_json"] else []
            summary_text += (
                f"\nVersion {hv['version_number']}: {hv['version_label']}\n"
                f"  Type: {hv['version_type']}\n"
                f"  Parent Version ID: {hv['parent_version_id'] or 'None (Root Initial Harmonization)'}\n"
                f"  Source SOPs: {', '.join(v_sources)}\n"
                f"  PDF Object: {hv['pdf_object_name']}\n"
                f"  Scores: Overall: {v_scores.get('average_score')}%, Template: {v_scores.get('template_score')}%, Readability: {v_scores.get('readability_score')}%, Quality: {v_scores.get('quality_score')}%\n"
                f"  Change Summary: {hv['change_summary']}\n"
            )
            if v_recs:
                summary_text += f"  Applied Simplifications: {', '.join(v_recs)}\n"
            if hv["user_prompt"]:
                summary_text += f"  User Prompt: {hv['user_prompt']}\n"
        summary_text += "\nLINEAGE STATUS: All Harmonized SOP Versions & Original PDFs Permanently Retained in MinIO & SQLite.\n"

    summary_text += f"\nTotal Messages Exchanged: {len(messages)}\n\n--- CONVERSATION TRANSCRIPT ---\n"
    for m in messages:
        summary_text += f"[{m['role'].upper()}]: {m['content']}\n\n"

    # Step 2: Upload session summary to MinIO under users/{username}/summaries/
    summary_object_name = f"users/{username}/summaries/{conversation_id}_summary.txt"
    minio_storage.upload_file_bytes(
        object_name=summary_object_name,
        data=summary_text.encode("utf-8"),
        content_type="text/plain",
        metadata={"username": username, "conversation_id": conversation_id, "type": "chat_summary"},
    )

    # Step 3: Cleanup intermediate extracted images and table crops from MinIO
    for art in artifacts:
        try:
            minio_storage.remove_file(art["object_name"])
        except Exception as e:
            logger.warning("Could not delete artifact %s: %s", art["object_name"], e)

    # Step 4: Cleanup FAISS vector index files from disk
    clear_vector_store(conversation_id)

    # Step 5: Clean up temporary artifacts records from SQLite & mark conversation ended
    c.execute("DELETE FROM sop_artifacts WHERE conversation_id=?", (conversation_id,))
    c.execute("UPDATE conversations SET status='ended', updated_at=? WHERE id=?", (now(), conversation_id))
    c.commit()
    c.close()

    logger.info("Ended conversation %s. Lineage preserved in MinIO (%s); intermediate vectors and media purged.", conversation_id, summary_object_name)

    return {
        "status": "ended",
        "summary_object_name": summary_object_name,
        "summary_url": f"/conversations/{conversation_id}/summary",
        "message": f"Session concluded. Summary with complete version lineage saved to MinIO ({summary_object_name}). Intermediate media and vector embeddings have been cleaned up.",
    }


@app.get("/conversations/{conversation_id}/summary")
def get_conversation_summary(conversation_id: str, x_username: Optional[str] = Header(None, alias="X-User-Name")):
    """Retrieves the archived session summary text and version lineage from MinIO."""
    username = (x_username or "admin").strip().lower()
    summary_object_name = f"users/{username}/summaries/{conversation_id}_summary.txt"
    data, ctype = minio_storage.get_file_bytes(summary_object_name)
    if not data:
        raise HTTPException(404, "Summary not found for this conversation.")
    return Response(content=data, media_type="text/plain; charset=utf-8")


# =============================================================
# 7. CHAT WITH RAG & 1-LINE CHATGPT-STYLE HISTORY SUMMARIES
# =============================================================
async def generate_chat_title_summary(provider: str, model: str, api_key: str, message_text: str) -> str:
    prompt = (
        "You are a helpful naming assistant like ChatGPT. "
        "Summarize the following user request into a concise 3 to 5 word title for the chat history sidebar. "
        "Do NOT include punctuation, quotes, or markdown. Output ONLY the short title.\n\n"
        f"User message: {message_text}\n"
        "Title:"
    )

    body = {
        "provider": "azure_openai",
        "model": model,
        "api_key": api_key,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{LLM_SERVICE_URL}/generate", json=body)
        if res.status_code == 200:
            raw_title = res.json().get("content", "").strip()
            clean = re.sub(r'["\'\*\#]', "", raw_title).split("\n")[0].strip()
            if clean.lower().startswith("title:"):
                clean = clean[6:].strip()
            if len(clean) >= 3 and len(clean) <= 40:
                return clean
    except Exception:
        pass

    words = message_text.strip().split()
    fallback_title = " ".join(words[:5])
    if len(words) > 5:
        fallback_title += "..."
    return fallback_title[:32].capitalize()


@app.post("/chat")
async def chat(payload: MessageRequest):
    c = db()
    conv = c.execute("SELECT * FROM conversations WHERE id=?", (payload.conversation_id,)).fetchone()
    if not conv:
        c.close()
        raise HTTPException(404, "Conversation not found")

    history = c.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
        (payload.conversation_id,),
    ).fetchall()
    c.close()

    llm_cfg = get_global_llm_config()
    provider = llm_cfg["provider"]
    model = llm_cfg["model"]
    api_key = llm_cfg["api_key"]

    if not api_key or not api_key.strip():
        from sop_evaluator import format_llm_unavailable_message
        raise HTTPException(
            503,
            format_llm_unavailable_message(provider, 400, "API key is not configured"),
        )

    history_dicts = [{"role": r["role"], "content": r["content"]} for r in history]
    history_dicts.append({"role": "user", "content": payload.content})

    # Execute LangGraph rag_chat workflow:
    # SupervisorAgent -> RetrievalAgent (faiss_search_context_tool + KenvueMicroserviceChatModel) -> FinalResponse
    chat_graph_state = await aexecute_sop_workflow(
        task_type="rag_chat",
        conversation_id=payload.conversation_id,
        input_payload={
            "query": payload.content,
            "history": history_dicts,
            "llm_config": {
                "llm_service_url": LLM_SERVICE_URL,
                "provider": "azure_openai",
                "model": model,
                "api_key": api_key,
            },
        },
    )

    chat_errors = chat_graph_state.get("errors", [])
    if chat_errors:
        err = chat_errors[-1]
        raise HTTPException(err.get("error_status", 503), err.get("message", "LLM service unavailable"))

    chat_res = chat_graph_state.get("intermediate_results", {}).get("chat_response", {})
    answer = chat_res.get("content", "")
    rag_applied = bool(chat_res.get("rag_applied", False))
    referenced_pages = chat_res.get("referenced_pages", [])

    # ChatGPT-style title summary
    updated_title = conv["title"]
    if conv["title"] == "New Chat":
        try:
            summary_title = await generate_chat_title_summary(
                provider=provider,
                model=model,
                api_key=api_key,
                message_text=payload.content,
            )
            if summary_title and summary_title != "New Chat":
                updated_title = summary_title
                c = db()
                c.execute("UPDATE conversations SET title=? WHERE id=?", (updated_title, payload.conversation_id))
                c.commit()
                c.close()
        except Exception:
            pass

    c = db()
    c.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), payload.conversation_id, "user", payload.content, now()),
    )
    c.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), payload.conversation_id, "assistant", answer, now()),
    )
    c.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), payload.conversation_id))
    c.commit()
    c.close()

    return {
        "role": "assistant",
        "content": answer,
        "title": updated_title,
        "rag_applied": rag_applied,
        "referenced_pages": referenced_pages,
        "agent_trace": chat_graph_state.get("agent_trace", []),
    }
