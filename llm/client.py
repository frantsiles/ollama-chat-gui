"""Factory de providers LLM y aliases de compatibilidad."""

from __future__ import annotations

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    LM_STUDIO_BASE_URL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
)
from llm.base import LLMClientError, LLMProvider
from llm.providers.anthropic import AnthropicProvider
from llm.providers.ollama import OllamaProvider
from llm.providers.openai_compat import OpenAICompatProvider

# ---------------------------------------------------------------------------
# Alias de compatibilidad — el resto del código puede seguir importando estos
# ---------------------------------------------------------------------------
OllamaClientError = LLMClientError


def create_client(
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """Instancia el provider adecuado según el nombre.

    Args:
        provider: "ollama" | "openai" | "lmstudio" | "anthropic".
                  Si es None usa LLM_PROVIDER de config.
        base_url: Override de URL base (opcional).
        api_key:  Override de API key (opcional).
    """
    p = (provider or LLM_PROVIDER).lower()

    if p == "ollama":
        return OllamaProvider(
            base_url=base_url or OLLAMA_BASE_URL,
            timeout=OLLAMA_TIMEOUT,
        )

    if p == "lmstudio":
        return OpenAICompatProvider(
            base_url=base_url or LM_STUDIO_BASE_URL,
            api_key=api_key or "",
            timeout=OLLAMA_TIMEOUT,
        )

    if p in ("openai", "copilot", "groq", "openai_compat"):
        return OpenAICompatProvider(
            base_url=base_url or OPENAI_BASE_URL,
            api_key=api_key or OPENAI_API_KEY,
            timeout=OLLAMA_TIMEOUT,
        )

    if p == "anthropic":
        return AnthropicProvider(
            api_key=api_key or ANTHROPIC_API_KEY,
            base_url=base_url or ANTHROPIC_BASE_URL,
            timeout=OLLAMA_TIMEOUT,
        )

    # Fallback: Ollama
    return OllamaProvider(base_url=base_url or OLLAMA_BASE_URL, timeout=OLLAMA_TIMEOUT)


def OllamaClient(
    base_url: str = OLLAMA_BASE_URL,
    timeout: int = OLLAMA_TIMEOUT,
) -> OllamaProvider:
    """Alias de compatibilidad — retorna un OllamaProvider."""
    return OllamaProvider(base_url=base_url, timeout=timeout)
