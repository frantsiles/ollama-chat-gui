"""Provider OpenAI-compatible (OpenAI, LM Studio, GitHub Copilot, Groq, etc.)."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Set

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

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    # ------------------------------------------------------------------
    # Listado y capacidades
    # ------------------------------------------------------------------

    def list_models(self) -> List[str]:
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

    def get_model_capabilities(self, model: str) -> Set[str]:
        caps: Set[str] = set()
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
        messages: List[Dict[str, Any]],
        stream: bool,
        options: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "num_predict" in options:
                payload["max_tokens"] = options["num_predict"]
        return payload

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
        fmt: str | None = None,
    ) -> str:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")
        if fmt == "json":
            # Algunos providers soportan response_format
            pass

        payload = self._build_payload(model, messages, stream=False, options=options)
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
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
        fmt: str | None = None,
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
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
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

        # Normalizar tool_calls de OpenAI → formato interno
        raw_calls = message.get("tool_calls", []) or []
        tool_calls = []
        for tc in raw_calls:
            fn = tc.get("function", {})
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"function": {"name": fn.get("name", ""), "arguments": args}})

        return {"content": content, "tool_calls": tool_calls}
