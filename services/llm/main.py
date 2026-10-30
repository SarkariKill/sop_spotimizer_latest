import asyncio
import os
import random
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Azure OpenAI LLM & Embedding Service", version="0.3.0")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, ".env")

_LLM_CONCURRENCY_SEMAPHORE = asyncio.Semaphore(3)


def _read_env_key(key_name: str) -> str:
    """Read key dynamically from .env file on disk so Admin UI updates take effect immediately without restart."""
    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        k, v = s.split("=", 1)
                        if k.strip() == key_name:
                            return v.strip().strip('"').strip("'")
        except Exception:
            pass
    return os.getenv(key_name, "").strip()


def _normalize_azure_endpoint(raw_endpoint: str) -> str:
    """
    Normalizes AZURE_OPENAI_ENDPOINT so whether the Admin enters:
      - https://resource.openai.azure.com
      - https://resource.openai.azure.com/
      - https://resource.openai.azure.com/openai/deployments/...
    we reliably extract the base endpoint URL: https://resource.openai.azure.com
    """
    ep = (raw_endpoint or "").strip().rstrip("/")
    if not ep:
        return ""
    # Strip any trailing /openai/... path if a full deployment URL was pasted
    ep = re.sub(r"/openai(?:/.*)?$", "", ep, flags=re.IGNORECASE).rstrip("/")
    return ep


class GenerateRequest(BaseModel):
    provider: Literal["azure_openai"] = "azure_openai"
    model: str = ""
    api_key: str = ""
    messages: list[dict[str, str]]
    max_tokens: int = 4096
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_api_version: Optional[str] = None


class EmbeddingsRequest(BaseModel):
    texts: List[str]
    azure_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    embedding_deployment: Optional[str] = None
    azure_api_version: Optional[str] = None


class Provider(ABC):
    @abstractmethod
    async def generate(self, model, api_key, messages, max_tokens: int = 4096, **kwargs):
        raise NotImplementedError


class AzureOpenAIProvider(Provider):
    async def generate(
        self,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        azure_endpoint: Optional[str] = None,
        azure_deployment: Optional[str] = None,
        azure_api_version: Optional[str] = None,
    ) -> str:
        endpoint = _normalize_azure_endpoint(
            azure_endpoint or _read_env_key("AZURE_OPENAI_ENDPOINT")
        )
        key = (
            api_key
            or _read_env_key("AZURE_OPENAI_KEY")
            or _read_env_key("LLM_API_KEY")
        ).strip()
        deployment = (
            azure_deployment
            or _read_env_key("AZURE_OPENAI_DEPLOYMENT_NAME")
            or model
        ).strip()
        api_version = (
            azure_api_version
            or _read_env_key("AZURE_OPENAI_API_VERSION")
            or "2024-02-01"
        ).strip()

        if not endpoint:
            raise HTTPException(
                400,
                "Azure OpenAI Endpoint (AZURE_OPENAI_ENDPOINT) is not configured by Admin in .env.",
            )
        if not key:
            raise HTTPException(
                400,
                "Azure OpenAI API Key (AZURE_OPENAI_KEY) is not configured by Admin in .env.",
            )
        if not deployment:
            raise HTTPException(
                400,
                "Azure OpenAI Deployment Name (AZURE_OPENAI_DEPLOYMENT_NAME) is not configured by Admin in .env.",
            )

        effective_max_tokens = max(4096, min(int(max_tokens or 4096), 8192))
        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions"
        headers = {
            "api-key": key,
            "Content-Type": "application/json",
        }
        params = {"api-version": api_version}

        payload = {
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": effective_max_tokens,
        }

        async with _LLM_CONCURRENCY_SEMAPHORE:
            async with httpx.AsyncClient(timeout=90) as client:
                last_err = "Azure OpenAI request failed after retries"
                last_code = 503
                for attempt in range(4):
                    try:
                        r = await client.post(
                            url,
                            headers=headers,
                            params=params,
                            json=payload,
                        )
                    except httpx.RequestError as exc:
                        last_err = str(exc)
                        last_code = 503
                        if attempt < 3:
                            await asyncio.sleep(1.5 * (attempt + 1) + random.uniform(0.2, 0.7))
                            continue
                        break

                    if r.status_code == 200:
                        data = r.json()
                        choices = data.get("choices") or []
                        if choices:
                            return (choices[0].get("message") or {}).get("content") or ""
                        return ""

                    # Handle reasoning / newer Azure models that require max_completion_tokens instead of max_tokens
                    if r.status_code == 400 and "max_completion_tokens" in r.text and "max_tokens" in payload:
                        payload.pop("max_tokens", None)
                        payload["max_completion_tokens"] = effective_max_tokens
                        payload.pop("temperature", None)
                        continue

                    if r.status_code in (429, 500, 502, 503, 504):
                        last_err = r.text
                        last_code = r.status_code
                        if attempt < 3:
                            await asyncio.sleep(1.5 * (attempt + 1) + random.uniform(0.2, 0.9))
                            continue
                        break

                    if r.status_code >= 400:
                        raise HTTPException(r.status_code, r.text)

                raise HTTPException(last_code, last_err)

    async def embed(
        self,
        texts: List[str],
        azure_endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        embedding_deployment: Optional[str] = None,
        azure_api_version: Optional[str] = None,
    ) -> List[List[float]]:
        if not texts:
            return []

        endpoint = _normalize_azure_endpoint(
            azure_endpoint or _read_env_key("AZURE_OPENAI_ENDPOINT")
        )
        key = (
            api_key
            or _read_env_key("AZURE_OPENAI_KEY")
            or _read_env_key("LLM_API_KEY")
        ).strip()
        deployment = (
            embedding_deployment
            or _read_env_key("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
            or "text-embedding-3-small"
        ).strip()
        api_version = (
            azure_api_version
            or _read_env_key("AZURE_OPENAI_API_VERSION")
            or "2024-02-01"
        ).strip()

        if not endpoint or not key or not deployment:
            raise HTTPException(
                400,
                "Azure OpenAI Embedding configuration (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_EMBEDDING_DEPLOYMENT) is incomplete in .env.",
            )

        url = f"{endpoint}/openai/deployments/{deployment}/embeddings"
        headers = {
            "api-key": key,
            "Content-Type": "application/json",
        }
        params = {"api-version": api_version}

        all_embeddings: List[List[float]] = []
        batch_size = 64

        async with httpx.AsyncClient(timeout=60) as client:
            for start_idx in range(0, len(texts), batch_size):
                batch = [t if (t and t.strip()) else " " for t in texts[start_idx : start_idx + batch_size]]
                last_err = "Azure OpenAI Embedding request failed"
                last_code = 503
                for attempt in range(3):
                    try:
                        r = await client.post(
                            url,
                            headers=headers,
                            params=params,
                            json={"input": batch},
                        )
                    except httpx.RequestError as exc:
                        last_err = str(exc)
                        last_code = 503
                        if attempt < 2:
                            await asyncio.sleep(1.0 * (attempt + 1))
                            continue
                        raise HTTPException(last_code, last_err) from exc

                    if r.status_code == 200:
                        items = sorted(r.json().get("data", []), key=lambda x: x.get("index", 0))
                        all_embeddings.extend([item["embedding"] for item in items])
                        break

                    if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        last_err = r.text
                        last_code = r.status_code
                        await asyncio.sleep(1.2 * (attempt + 1))
                        continue

                    raise HTTPException(r.status_code, r.text)

        return all_embeddings


AZURE_PROVIDER = AzureOpenAIProvider()


@app.get("/health")
def health():
    return {"status": "ok", "service": "llm", "provider": "azure_openai"}


@app.get("/providers")
def providers():
    deployment = _read_env_key("AZURE_OPENAI_DEPLOYMENT_NAME") or "gpt-4o-mini"
    embedding_deployment = _read_env_key("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or "text-embedding-3-small"
    return {
        "providers": {
            "azure_openai": {
                "models": [deployment],
                "embedding_deployment": embedding_deployment,
            },
        }
    }


@app.post("/generate")
async def generate(request: GenerateRequest):
    content = await AZURE_PROVIDER.generate(
        model=request.model,
        api_key=request.api_key,
        messages=request.messages,
        max_tokens=request.max_tokens,
        azure_endpoint=request.azure_endpoint,
        azure_deployment=request.azure_deployment,
        azure_api_version=request.azure_api_version,
    )
    deployment = (
        request.azure_deployment
        or _read_env_key("AZURE_OPENAI_DEPLOYMENT_NAME")
        or request.model
    )
    return {
        "content": content,
        "provider": "azure_openai",
        "model": deployment,
    }


@app.post("/embeddings")
async def embeddings(request: EmbeddingsRequest):
    vectors = await AZURE_PROVIDER.embed(
        texts=request.texts,
        azure_endpoint=request.azure_endpoint,
        api_key=request.api_key,
        embedding_deployment=request.embedding_deployment,
        azure_api_version=request.azure_api_version,
    )
    return {
        "embeddings": vectors,
        "provider": "azure_openai",
        "embedding_deployment": request.embedding_deployment or _read_env_key("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
    }
