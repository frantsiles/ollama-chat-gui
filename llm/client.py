"""Cliente para interactuar con Ollama API."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set

import requests

from config import OLLAMA_BASE_URL, OLLAMA_TIMEOUT


class OllamaClientError(Exception):
    """Error de comunicación con Ollama."""
    pass


class OllamaClient:
    """Cliente HTTP para Ollama API."""
    
    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        timeout: int = OLLAMA_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_usage: Dict[str, int] = {}
    
    def list_models(self) -> List[str]:
        """Lista los modelos disponibles en Ollama."""
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
        """Obtiene las capacidades de un modelo (ej: vision)."""
        if not model:
            return set()
        
        url = f"{self.base_url}/api/show"
        try:
            response = requests.post(url, json={"model": model}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaClientError(
                "No se pudieron consultar las capacidades del modelo."
            ) from exc
        
        data = response.json()
        return set(data.get("capabilities", []))
    
    def get_model_info(self, model: str) -> Dict[str, Any]:
        """Obtiene información completa de un modelo."""
        if not model:
            return {}
        
        url = f"{self.base_url}/api/show"
        try:
            response = requests.post(url, json={"model": model}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaClientError(
                "No se pudo obtener información del modelo."
            ) from exc
        
        return response.json()
    
    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None,
        fmt: Optional[str] = None,
    ) -> str:
        """Ejecuta un chat completo (sin streaming).

        Args:
            fmt: Si es "json", fuerza al modelo a producir JSON válido (útil para
                 modelos que ignoran instrucciones de formato como Gemma).
        """
        if not model:
            raise OllamaClientError("Debes seleccionar o indicar un modelo.")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options
        if fmt:
            payload["format"] = fmt

        url = f"{self.base_url}/api/chat"
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise OllamaClientError("Error durante el chat con Ollama.") from exc

        # Leer el cuerpo antes de raise_for_status para dar mensajes claros
        try:
            data = response.json()
        except Exception:
            data = {}
        if "error" in data:
            err = str(data["error"])
            if response.status_code == 401:
                raise OllamaClientError(
                    f"El modelo '{model}' requiere autenticación (modelo cloud). "
                    "Selecciona un modelo local como qwen2.5-coder o gemma."
                )
            raise OllamaClientError(err)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise OllamaClientError(f"Ollama respondió con error {response.status_code}.") from exc

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
        options: Optional[Dict[str, Any]] = None,
        fmt: Optional[str] = None,
    ) -> Iterable[str]:
        """Ejecuta un chat con streaming de respuesta."""
        if not model:
            raise OllamaClientError("Debes seleccionar o indicar un modelo.")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options
        if fmt:
            payload["format"] = fmt
        
        url = f"{self.base_url}/api/chat"
        try:
            with requests.post(
                url, json=payload, stream=True, timeout=self.timeout
            ) as response:
                # Detect auth/error before streaming
                if response.status_code == 401:
                    raise OllamaClientError(
                        f"El modelo '{model}' requiere autenticación (modelo cloud). "
                        "Selecciona un modelo local como qwen2.5-coder o gemma."
                    )
                if not response.ok:
                    raise OllamaClientError(f"Ollama respondió con error {response.status_code}.")
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
        except OllamaClientError:
            raise
        except requests.RequestException as exc:
            raise OllamaClientError("Error durante el chat con Ollama.") from exc
    
    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Genera texto usando el endpoint /api/generate."""
        if not model:
            raise OllamaClientError("Debes seleccionar o indicar un modelo.")
        
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        
        url = f"{self.base_url}/api/generate"
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaClientError("Error durante la generación con Ollama.") from exc
        
        data = response.json()
        if "error" in data:
            raise OllamaClientError(str(data["error"]))
        
        return data.get("response", "")
    
    def chat_with_tools(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ejecuta un chat usando el API nativo de function calling de Ollama.

        Returns:
            Dict con 'content' (str) y 'tool_calls' (list).
            tool_calls es una lista de dicts con campo 'function': {'name', 'arguments'}.
        """
        if not model:
            raise OllamaClientError("Debes seleccionar o indicar un modelo.")

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
            raise OllamaClientError("Error durante el chat con herramientas en Ollama.") from exc

        data = response.json()
        if "error" in data:
            raise OllamaClientError(str(data["error"]))

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        self.last_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "duration_ms": data.get("total_duration", 0) // 1_000_000,
        }

        message = data.get("message", {})
        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
        }

    def get_context_length(self, model: str) -> int:
        """Retorna el tamaño de la ventana de contexto del modelo, o 0 si no se puede determinar."""
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

    def model_supports_tools(self, model: str) -> bool:
        """Verifica si el modelo soporta function calling nativo."""
        try:
            caps = self.get_model_capabilities(model)
            return "tools" in caps
        except OllamaClientError:
            return False

    def is_available(self) -> bool:
        """Verifica si Ollama está disponible."""
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False
