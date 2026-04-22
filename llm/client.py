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
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaClientError("Error durante el chat con Ollama.") from exc
        
        data = response.json()
        if "error" in data:
            raise OllamaClientError(str(data["error"]))
        
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
