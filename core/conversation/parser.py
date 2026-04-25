"""Parser de intenciones: convierte una respuesta en texto libre en un tool call.

Responsabilidad única: dada una respuesta del modelo principal, decidir si
implica el uso de una herramienta y, de ser así, extraer su nombre y argumentos.

Ante cualquier fallo retorna `{"needs_tool": False}` para no romper el flujo.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from llm.prompts import NATURAL_PARSER_PROMPT, PromptManager


class NaturalResponseParser:
    """Segunda llamada al LLM: extrae tool call desde texto libre."""

    def __init__(
        self,
        llm_call: Callable[[List[Dict[str, Any]], Optional[str]], str],
        dynamic_tool_names: Optional[List[str]] = None,
    ) -> None:
        """
        Args:
            llm_call: callable(messages, fmt) → respuesta del modelo. fmt="json"
                      cuando se necesite forzar JSON.
            dynamic_tool_names: nombres de tools dinámicas (MCP, etc.) que
                                deben aparecer en la descripción para el parser.
        """
        self._llm_call = llm_call
        self._dynamic_tool_names = dynamic_tool_names or []

    def parse(self, response: str) -> Dict[str, Any]:
        """Analiza una respuesta y retorna la intención detectada.

        Returns:
            {"needs_tool": False}
            o
            {"needs_tool": True, "tool": "<nombre>", "args": {...}}
        """
        parser_prompt = self._build_parser_prompt()
        messages = [
            {"role": "system", "content": parser_prompt},
            {"role": "user", "content": response},
        ]

        try:
            raw = self._llm_call(messages, "json").strip()
            raw = self._strip_markdown_fences(raw)
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        return {"needs_tool": False}

    def _build_parser_prompt(self) -> str:
        """Construye el prompt del parser con la lista de tools disponibles."""
        extra: List[str] = [
            f"{name}(...) → herramienta dinámica registrada"
            for name in self._dynamic_tool_names
        ]
        tools_desc = PromptManager.get_tools_description_for_parser(extra or None)
        return NATURAL_PARSER_PROMPT.format(tools_description=tools_desc)

    @staticmethod
    def _strip_markdown_fences(raw: str) -> str:
        """Quita bloques ```...``` si el modelo envuelve la respuesta."""
        if raw.startswith("```"):
            lines = raw.splitlines()
            return "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return raw
