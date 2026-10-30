"""
LangChain BaseChatModel Wrapper for the Kenvue Local LLM Microservice (http://localhost:8001).
Enables native LangChain LCEL chains, ChatPromptTemplates, and agents to invoke the Admin-configured
Azure OpenAI provider through the existing local microservice.
"""
import logging
from typing import Any, Dict, List, Optional
import httpx
from pydantic import Field
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger("kenvue_agentic_llm")


def _convert_lc_messages_to_dict(messages: List[BaseMessage]) -> List[Dict[str, str]]:
    converted: List[Dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, HumanMessage):
            role = "user"
        else:
            role = getattr(msg, "type", "user")
            if role == "human":
                role = "user"
            elif role == "ai":
                role = "assistant"
        converted.append({"role": role, "content": str(msg.content)})
    return converted


class KenvueMicroserviceChatModel(BaseChatModel):
    """
    LangChain ChatModel that routes requests to the Kenvue LLM Microservice (/generate).
    Preserves full compatibility with Admin .env configuration (Azure OpenAI) and HTTP status codes.
    """

    llm_service_url: str = Field(default="http://localhost:8001")
    provider: str = Field(default="azure_openai")
    model: str = Field(default="gpt-4o-mini")
    api_key: str = Field(default="")
    timeout: float = Field(default=90.0)
    bound_tools: List[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return f"kenvue-microservice-{self.provider}"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "llm_service_url": self.llm_service_url,
            "provider": self.provider,
            "model": self.model,
            "bound_tools_count": len(self.bound_tools),
        }

    def bind_tools(self, tools: List[Any], **kwargs: Any) -> "KenvueMicroserviceChatModel":
        """Binds LangChain tools to this ChatModel instance for agentic inspection and invocation."""
        clone = self.model_copy(deep=True)
        clone.bound_tools = list(tools)
        return clone

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.api_key or not self.api_key.strip():
            raise RuntimeError("LLM_HTTP_400:API key is not configured")
        payload = {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "messages": _convert_lc_messages_to_dict(messages),
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.llm_service_url}/generate", json=payload)

        if response.status_code >= 400:
            error_detail = response.text
            try:
                data = response.json()
                if isinstance(data, dict) and "detail" in data:
                    error_detail = data["detail"]
            except Exception:
                pass
            raise RuntimeError(f"LLM_HTTP_{response.status_code}:{error_detail}")

        content = response.json().get("content", "")
        message = AIMessage(
            content=content,
            response_metadata={
                "provider": self.provider,
                "model": self.model,
                "status_code": response.status_code,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.api_key or not self.api_key.strip():
            raise RuntimeError("LLM_HTTP_400:API key is not configured")
        payload = {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "messages": _convert_lc_messages_to_dict(messages),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.llm_service_url}/generate", json=payload)

        if response.status_code >= 400:
            error_detail = response.text
            try:
                data = response.json()
                if isinstance(data, dict) and "detail" in data:
                    error_detail = data["detail"]
            except Exception:
                pass
            raise RuntimeError(f"LLM_HTTP_{response.status_code}:{error_detail}")

        content = response.json().get("content", "")
        message = AIMessage(
            content=content,
            response_metadata={
                "provider": self.provider,
                "model": self.model,
                "status_code": response.status_code,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
