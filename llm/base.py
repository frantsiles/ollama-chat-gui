"""Interfaz base para providers LLM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Set


class LLMClientError(Exception):
    """Error de comunicación con un provider LLM."""
    pass


class LLMProvider(ABC):
    """Contrato que deben implementar todos los providers LLM."""

    # Actualizado tras cada llamada con métricas de uso
    last_usage: Dict[str, int]

    def __init__(self) -> None:
        self.last_usage: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Métodos obligatorios
    # ------------------------------------------------------------------

    @abstractmethod
    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
        fmt: str | Dict[str, Any] | None = None,
    ) -> str:
        """Chat sin streaming. Retorna el texto de la respuesta.

        Args:
            fmt: None (texto libre), "json" (JSON sin schema) o un dict con
                 un JSON schema para structured outputs.
        """

    @abstractmethod
    def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
        fmt: str | Dict[str, Any] | None = None,
    ) -> Iterable[str]:
        """Chat con streaming. Yield de fragmentos de texto."""

    @abstractmethod
    def chat_with_tools(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        options: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Chat con function calling nativo.

        Retorna dict normalizado:
            {
                "content": str,
                "tool_calls": [
                    {"id": str | None, "function": {"name": str, "arguments": dict}}
                ]
            }

        El "id" (si el provider lo entrega) DEBE preservarse: es necesario
        para reinyectar los resultados con format_tool_result_message().
        """

    @abstractmethod
    def list_models(self) -> List[str]:
        """Lista los modelos disponibles en este provider."""

    @abstractmethod
    def model_supports_tools(self, model: str) -> bool:
        """True si el modelo soporta function calling nativo."""

    # ------------------------------------------------------------------
    # Métodos opcionales con implementaciones por defecto
    # ------------------------------------------------------------------

    def get_model_capabilities(self, model: str) -> Set[str]:
        """Retorna capacidades del modelo (p.ej. {'tools', 'vision'})."""
        caps: Set[str] = set()
        if self.model_supports_tools(model):
            caps.add("tools")
        return caps

    def get_model_info(self, model: str) -> Dict[str, Any]:
        """Información detallada del modelo (puede retornar dict vacío)."""
        return {}

    def get_context_length(self, model: str) -> int:
        """Retorna la ventana de contexto del modelo, o 0 si se desconoce."""
        return 0

    def is_available(self) -> bool:
        """True si el provider está accesible."""
        return True

    # ------------------------------------------------------------------
    # Protocolo de mensajes de tool calling
    #
    # Cada provider tiene su propio formato de "asistente pidió tools" y
    # "resultado de tool". Estas implementaciones por defecto siguen el
    # formato de Ollama; OpenAI-compatible y Anthropic las sobreescriben.
    # ------------------------------------------------------------------

    def format_assistant_tool_message(
        self,
        content: str,
        tool_calls: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Mensaje del asistente que contiene tool calls (formato normalizado)."""
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {"function": tc.get("function", {})}
                for tc in tool_calls
            ],
        }

    def format_tool_result_message(
        self,
        tool_call: Dict[str, Any],
        output: str,
    ) -> Dict[str, Any]:
        """Mensaje con el resultado de una tool (formato normalizado).

        Args:
            tool_call: tool call normalizado ({"id": ..., "function": {...}}).
            output: salida (o error) de la ejecución.
        """
        msg: Dict[str, Any] = {"role": "tool", "content": output}
        name = tool_call.get("function", {}).get("name")
        if name:
            msg["tool_name"] = name
        return msg
