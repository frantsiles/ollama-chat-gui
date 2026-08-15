"""Provider OpenAI-compatible (OpenAI, LM Studio, GitHub Copilot, Groq, etc.)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import requests

from llm.base import LLMClientError, LLMProvider

# Modelos conocidos que soportan function calling (actualizar según necesidad)
_TOOLS_CAPABLE_PREFIXES = (
    "gpt-4", "gpt-3.5-turbo", "o1", "o3",
    "mistral", "mixtral",
    "llama-3", "llama3",
    "qwen", "deepseek",
    "gemma",
    "phi-3", "phi-4",
)


def _model_likely_supports_tools(model: str) -> bool:
    m = model.lower()
    return any(m.startswith(p) or p in m for p in _TOOLS_CAPABLE_PREFIXES)


class OpenAICompatProvider(LLMProvider):
    """Provider para cualquier API compatible con OpenAI (/v1/chat/completions)."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: int = 120,
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    # ------------------------------------------------------------------
    # Listado y capacidades
    # ------------------------------------------------------------------

    def list_models(self) -> list[str]:
        url = f"{self.base_url}/models"
        try:
            response = requests.get(url, headers=self._headers(), timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return sorted(item["id"] for item in data.get("data", []) if "id" in item)
        except requests.RequestException as exc:
            raise LLMClientError(f"No se pudo listar modelos: {exc}") from exc

    def model_supports_tools(self, model: str) -> bool:
        return _model_likely_supports_tools(model)

    def get_model_capabilities(self, model: str) -> set[str]:
        caps: set[str] = set()
        if self.model_supports_tools(model):
            caps.add("tools")
        return caps

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=5)
            return r.status_code in (200, 401)  # 401 = hay servidor, falta auth
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool,
        options: dict[str, Any] | None,
        fmt: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "num_predict" in options:
                payload["max_tokens"] = options["num_predict"]
        if fmt == "json":
            payload["response_format"] = {"type": "json_object"}
        elif isinstance(fmt, dict):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": fmt},
            }
        return payload

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        fmt: str | dict[str, Any] | None = None,
    ) -> str:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")

        payload = self._build_payload(model, messages, stream=False, options=options, fmt=fmt)
        url = f"{self.base_url}/chat/completions"
        try:
            response = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMClientError(f"Error de conexión con el provider: {exc}") from exc

        try:
            data = response.json()
        except Exception:
            data = {}

        if not response.ok:
            # No todos los providers OpenAI-compatible soportan json_schema:
            # degradar una vez a json_object antes de rendirse.
            if isinstance(fmt, dict) and response.status_code == 400:
                return self.chat(model, messages, options=options, fmt="json")
            err = data.get("error", {})
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise LLMClientError(f"Error del provider ({response.status_code}): {msg}")

        usage = data.get("usage", {})
        self.last_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "duration_ms": 0,
        }
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        fmt: str | dict[str, Any] | None = None,
    ) -> Iterable[str]:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")
        payload = self._build_payload(model, messages, stream=True, options=options)
        url = f"{self.base_url}/chat/completions"
        try:
            with requests.post(
                url, json=payload, headers=self._headers(), stream=True, timeout=self.timeout
            ) as response:
                if not response.ok:
                    raise LLMClientError(f"Error del provider ({response.status_code}).")
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
        except LLMClientError:
            raise
        except requests.RequestException as exc:
            raise LLMClientError(f"Error durante el streaming: {exc}") from exc

    def chat_with_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")
        payload = self._build_payload(model, messages, stream=False, options=options)
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"
        try:
            response = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMClientError(f"Error de conexión con el provider: {exc}") from exc

        try:
            data = response.json()
        except Exception:
            data = {}

        if not response.ok:
            err = data.get("error", {})
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise LLMClientError(f"Error del provider ({response.status_code}): {msg}")

        usage = data.get("usage", {})
        self.last_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "duration_ms": 0,
        }

        message = data.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "") or ""

        # Normalizar tool_calls de OpenAI → formato interno (preservando id)
        raw_calls = message.get("tool_calls", []) or []
        tool_calls = []
        for tc in raw_calls:
            fn = tc.get("function", {})
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "id": tc.get("id"),
                "function": {"name": fn.get("name", ""), "arguments": args},
            })

        return {"content": content, "tool_calls": tool_calls}

    # ------------------------------------------------------------------
    # Protocolo de mensajes de tool calling (formato OpenAI)
    # ------------------------------------------------------------------

    @staticmethod
    def _call_id(tool_call: dict[str, Any], index: int = 0) -> str:
        """ID del tool call, generando uno determinista si el provider no lo dio."""
        return tool_call.get("id") or f"call_{index}_{tool_call.get('function', {}).get('name', 'tool')}"

    def format_assistant_tool_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """OpenAI exige id + type y arguments serializados como string JSON."""
        calls = []
        for i, tc in enumerate(tool_calls):
            fn = tc.get("function", {})
            calls.append({
                "id": self._call_id(tc, i),
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": json.dumps(fn.get("arguments", {}) or {}),
                },
            })
        msg: dict[str, Any] = {"role": "assistant", "tool_calls": calls}
        # OpenAI acepta content null junto a tool_calls; solo incluir si hay texto
        msg["content"] = content or None
        return msg

    def format_tool_result_message(
        self,
        tool_call: dict[str, Any],
        output: str,
    ) -> dict[str, Any]:
        """OpenAI exige tool_call_id que apunte al call del mensaje anterior."""
        return {
            "role": "tool",
            "tool_call_id": self._call_id(tool_call),
            "content": output,
        }
