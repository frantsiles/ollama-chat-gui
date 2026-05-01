"""Provider para Ollama (API nativa)."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Set

import requests

from config import OLLAMA_BASE_URL, OLLAMA_TIMEOUT
from llm.base import LLMClientError, LLMProvider


class OllamaProvider(LLMProvider):
    """Provider que habla con la API nativa de Ollama."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        timeout: int = OLLAMA_TIMEOUT,
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Listado y capacidades
    # ------------------------------------------------------------------

    def list_models(self) -> List[str]:
        url = f"{self.base_url}/api/tags"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMClientError(
                "No se pudo consultar Ollama. Verifica que esté activo con `ollama ps`."
            ) from exc
        data = response.json()
        return [item["name"] for item in data.get("models", []) if "name" in item]

    def get_model_capabilities(self, model: str) -> Set[str]:
        if not model:
            return set()
        url = f"{self.base_url}/api/show"
        try:
            response = requests.post(url, json={"model": model}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMClientError("No se pudieron consultar las capacidades del modelo.") from exc
        return set(response.json().get("capabilities", []))

    def model_supports_tools(self, model: str) -> bool:
        try:
            return "tools" in self.get_model_capabilities(model)
        except LLMClientError:
            return False

    def get_model_info(self, model: str) -> Dict[str, Any]:
        if not model:
            return {}
        url = f"{self.base_url}/api/show"
        try:
            response = requests.post(url, json={"model": model}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMClientError("No se pudo obtener información del modelo.") from exc
        return response.json()

    def get_context_length(self, model: str) -> int:
        try:
            info = self.get_model_info(model)
            for key, val in info.get("model_info", {}).items():
                if "context_length" in key:
                    return int(val)
            for line in info.get("parameters", "").splitlines():
                parts = line.split()
                if parts and parts[0] == "num_ctx" and len(parts) >= 2:
                    return int(parts[1])
        except Exception:
            pass
        return 0

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
        fmt: str | None = None,
    ) -> str:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if options:
            payload["options"] = options
        if fmt:
            payload["format"] = fmt

        url = f"{self.base_url}/api/chat"
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMClientError("Error durante el chat con Ollama.") from exc

        try:
            data = response.json()
        except Exception:
            data = {}

        if "error" in data:
            err = str(data["error"])
            if response.status_code == 401:
                raise LLMClientError(
                    f"El modelo '{model}' requiere autenticación. "
                    "Selecciona un modelo local."
                )
            raise LLMClientError(err)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise LLMClientError(f"Ollama respondió con error {response.status_code}.") from exc

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        self.last_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "duration_ms": data.get("total_duration", 0) // 1_000_000,
        }
        return data.get("message", {}).get("content", "")

    def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
        fmt: str | None = None,
    ) -> Iterable[str]:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if options:
            payload["options"] = options
        if fmt:
            payload["format"] = fmt

        url = f"{self.base_url}/api/chat"
        try:
            with requests.post(url, json=payload, stream=True, timeout=self.timeout) as response:
                if response.status_code == 401:
                    raise LLMClientError(
                        f"El modelo '{model}' requiere autenticación. "
                        "Selecciona un modelo local."
                    )
                if not response.ok:
                    raise LLMClientError(f"Ollama respondió con error {response.status_code}.")
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in data:
                        raise LLMClientError(str(data["error"]))
                    content = data.get("message", {}).get("content")
                    if content:
                        yield content
        except LLMClientError:
            raise
        except requests.RequestException as exc:
            raise LLMClientError("Error durante el streaming con Ollama.") from exc

    def chat_with_tools(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if not model:
            raise LLMClientError("Debes seleccionar un modelo.")
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
        }
        if options:
            payload["options"] = options

        url = f"{self.base_url}/api/chat"
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMClientError("Error durante el chat con herramientas en Ollama.") from exc

        data = response.json()
        if "error" in data:
            raise LLMClientError(str(data["error"]))

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        self.last_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "duration_ms": data.get("total_duration", 0) // 1_000_000,
        }
        message = data.get("message", {})
        # Ollama ya devuelve arguments como dict — formato interno directo
        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
        }
