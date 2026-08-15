"""Provider para Anthropic Claude API."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import requests

from llm.base import LLMClientError, LLMProvider

# Modelos Claude disponibles (se actualiza periódicamente)
_CLAUDE_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
]

_ANTHROPIC_API_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096


def _extract_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Separa los system messages de los demás (Anthropic requiere param separado).

    Concatena TODOS los system messages (prompt principal + contexto de
    workspace + tool results persistidos) — quedarse solo con el último
    haría perder el prompt principal.
    """
    system_parts: list[str] = []
    rest = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                system_parts.append(content)
        else:
            rest.append(msg)
    return "\n\n".join(system_parts), rest


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte herramientas de formato OpenAI a formato Anthropic."""
    result = []
    for tool in tools:
        fn = tool.get("function", tool)
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


class AnthropicProvider(LLMProvider):
    """Provider para Anthropic Claude API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout: int = 120,
    ) -> None:
        super().__init__()
        if not api_key:
            raise LLMClientError(
                "Se requiere ANTHROPIC_API_KEY para usar el provider Anthropic."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Listado y capacidades
    # ------------------------------------------------------------------

    def list_models(self) -> list[str]:
        """Intenta listar modelos vía API; si falla, retorna lista estática."""
        try:
            url = f"{self.base_url}/v1/models"
            response = requests.get(url, headers=self._headers(), timeout=self.timeout)
            if response.ok:
                data = response.json()
                return [m["id"] for m in data.get("data", []) if "id" in m]
        except requests.RequestException:
            pass
        return list(_CLAUDE_MODELS)

    def model_supports_tools(self, model: str) -> bool:
        # Todos los modelos Claude 3+ soportan tools
        return True

    def get_model_capabilities(self, model: str) -> set[str]:
        return {"tools", "vision"}

    def is_available(self) -> bool:
        try:
            r = requests.get(
                f"{self.base_url}/v1/models",
                headers=self._headers(),
                timeout=5,
            )
            return r.status_code in (200, 404)  # 404 = endpoint no existe pero hay conexión
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        fmt: str | dict[str, Any] | None = None,
    ) -> str:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")

        system, msgs = _extract_system(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": msgs,
        }
        if system:
            payload["system"] = system
        if options and "temperature" in options:
            payload["temperature"] = options["temperature"]

        url = f"{self.base_url}/v1/messages"
        try:
            response = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMClientError(f"Error de conexión con Anthropic: {exc}") from exc

        try:
            data = response.json()
        except Exception:
            data = {}

        if not response.ok:
            err = data.get("error", {})
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise LLMClientError(f"Error de Anthropic ({response.status_code}): {msg}")

        usage = data.get("usage", {})
        self.last_usage = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "duration_ms": 0,
        }

        content_blocks = data.get("content", [])
        text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        return "".join(text_parts)

    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        fmt: str | dict[str, Any] | None = None,
    ) -> Iterable[str]:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")

        system, msgs = _extract_system(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": msgs,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if options and "temperature" in options:
            payload["temperature"] = options["temperature"]

        url = f"{self.base_url}/v1/messages"
        try:
            with requests.post(
                url, json=payload, headers=self._headers(), stream=True, timeout=self.timeout
            ) as response:
                if not response.ok:
                    raise LLMClientError(f"Error de Anthropic ({response.status_code}).")
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield text
        except LLMClientError:
            raise
        except requests.RequestException as exc:
            raise LLMClientError(f"Error durante el streaming con Anthropic: {exc}") from exc

    def chat_with_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")

        system, msgs = _extract_system(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": msgs,
            "tools": _convert_tools(tools),
        }
        if system:
            payload["system"] = system
        if options and "temperature" in options:
            payload["temperature"] = options["temperature"]

        url = f"{self.base_url}/v1/messages"
        try:
            response = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMClientError(f"Error de conexión con Anthropic: {exc}") from exc

        try:
            data = response.json()
        except Exception:
            data = {}

        if not response.ok:
            err = data.get("error", {})
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise LLMClientError(f"Error de Anthropic ({response.status_code}): {msg}")

        usage = data.get("usage", {})
        self.last_usage = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "duration_ms": 0,
        }

        content_blocks = data.get("content", [])
        text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        content = "".join(text_parts)

        # Normalizar tool_use de Anthropic → formato interno (preservando id)
        tool_calls = []
        for block in content_blocks:
            if block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {}),
                    }
                })

        return {"content": content, "tool_calls": tool_calls}

    # ------------------------------------------------------------------
    # Protocolo de mensajes de tool calling (formato Anthropic)
    # ------------------------------------------------------------------

    def format_assistant_tool_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Anthropic representa los tool calls como bloques tool_use."""
        blocks: list[dict[str, Any]] = []
        if content:
            blocks.append({"type": "text", "text": content})
        for i, tc in enumerate(tool_calls):
            fn = tc.get("function", {})
            blocks.append({
                "type": "tool_use",
                "id": tc.get("id") or f"toolu_{i}_{fn.get('name', 'tool')}",
                "name": fn.get("name", ""),
                "input": fn.get("arguments", {}) or {},
            })
        return {"role": "assistant", "content": blocks}

    def format_tool_result_message(
        self,
        tool_call: dict[str, Any],
        output: str,
    ) -> dict[str, Any]:
        """Anthropic espera el resultado como bloque tool_result en un mensaje user."""
        fn = tool_call.get("function", {})
        return {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call.get("id") or f"toolu_0_{fn.get('name', 'tool')}",
                "content": output,
            }],
        }
