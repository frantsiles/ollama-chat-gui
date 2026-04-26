"""Parser de intenciones: convierte una respuesta en texto libre en un tool call.

Responsabilidad única: dada una respuesta del modelo principal, decidir si
implica el uso de una herramienta y, de ser así, extraer su nombre y argumentos.

Ante cualquier fallo retorna `{"needs_tool": False}` para no romper el flujo.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from llm.prompts import NATURAL_PARSER_PROMPT, PromptManager

# Palabras clave que indican INTENCIÓN FUTURA de escribir/crear un archivo.
# Solo tiempo futuro/presente de acción — NO confirmaciones pasadas ("aquí está",
# "ya escribí", "el archivo contiene") para evitar re-detectar resúmenes post-tool.
_WRITE_INTENT_PATTERNS = re.compile(
    r'\b(voy a (escribir|crear|implementar|guardar)|'
    r'escribiré|crearé|implementaré|'
    r'escribiendo en|creando el archivo|'
    r'procedo a (escribir|crear)|'
    r'write_file\s*\()\b',
    re.IGNORECASE,
)

# Detecta rutas de archivo con extensión comunes
_FILE_PATH_PATTERN = re.compile(
    r'\b([\w/\-\.]+\.(?:py|js|ts|json|yaml|yml|md|txt|sh|html|css|java|go|rs|cpp|c|h))\b'
)

# Extrae el primer bloque de código de una respuesta
_CODE_BLOCK_PATTERN = re.compile(
    r'```(?:\w+)?\n(.*?)```',
    re.DOTALL,
)


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

        Primero aplica heurísticas rápidas (sin LLM). Si no hay señal clara,
        delega al LLM parser como segunda opinión.

        Returns:
            {"needs_tool": False}
            o
            {"needs_tool": True, "tool": "<nombre>", "args": {...}}
        """
        # 1. Heurística: bloque de código + intención de escribir archivo
        heuristic = self._heuristic_write_file(response)
        if heuristic:
            return heuristic

        # 2. Heurística: JSON directo de tool call embebido en la respuesta
        inline = self._extract_inline_json_tool(response)
        if inline:
            return inline

        # 3. Fallback: segunda llamada al LLM
        return self._llm_parse(response)

    # ------------------------------------------------------------------
    # Heurísticas (sin LLM, O(1))
    # ------------------------------------------------------------------

    def _heuristic_write_file(self, response: str) -> Optional[Dict[str, Any]]:
        """Detecta 'intención de escribir + bloque de código + nombre de archivo'."""
        if not _WRITE_INTENT_PATTERNS.search(response):
            return None

        code_match = _CODE_BLOCK_PATTERN.search(response)
        if not code_match:
            return None

        content = code_match.group(1)
        if not content.strip():
            return None

        # Buscar el nombre de archivo más cercano al bloque de código
        path = self._extract_file_path(response)
        if not path:
            return None

        return {
            "needs_tool": True,
            "tool": "write_file",
            "args": {"path": path, "content": content},
        }

    def _extract_file_path(self, text: str) -> Optional[str]:
        """Extrae el nombre de archivo más probable del texto."""
        matches = _FILE_PATH_PATTERN.findall(text)
        if not matches:
            return None
        # Preferir el primero que no sea una URL ni un path de sistema
        for m in matches:
            if not m.startswith(("/usr", "/etc", "/bin", "http")):
                return m
        return matches[0]

    def _extract_inline_json_tool(self, response: str) -> Optional[Dict[str, Any]]:
        """Detecta si el modelo embebió un JSON de tool call directamente."""
        # Buscar primer objeto JSON válido que tenga "tool" o "needs_tool"
        for match in re.finditer(r'\{[^{}]*"(?:tool|needs_tool)"[^{}]*\}', response, re.DOTALL):
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict) and ("tool" in data or "needs_tool" in data):
                    # Normalizar al formato del parser
                    if "needs_tool" not in data and "tool" in data:
                        data["needs_tool"] = True
                    return data
            except json.JSONDecodeError:
                continue
        return None

    # ------------------------------------------------------------------
    # Fallback LLM
    # ------------------------------------------------------------------

    def _llm_parse(self, response: str) -> Dict[str, Any]:
        """Delega al modelo secundario cuando las heurísticas no detectan nada."""
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
