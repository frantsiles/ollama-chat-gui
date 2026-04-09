from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Set

import requests


class OllamaClientError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def list_models(self) -> List[str]:
        url = f"{self.base_url}/api/tags"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaClientError(
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
            raise OllamaClientError("No se pudieron consultar las capacidades del modelo.") from exc

        data = response.json()
        return set(data.get("capabilities", []))

    def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, float] | None = None,
    ) -> Iterable[str]:
        if not model:
            raise OllamaClientError("Debes seleccionar o indicar un modelo.")

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options

        url = f"{self.base_url}/api/chat"
        try:
            with requests.post(url, json=payload, stream=True, timeout=self.timeout) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if "error" in data:
                        raise OllamaClientError(str(data["error"]))

                    message = data.get("message", {})
                    content = message.get("content")
                    if content:
                        yield content
        except requests.RequestException as exc:
            raise OllamaClientError("Error durante el chat con Ollama.") from exc
