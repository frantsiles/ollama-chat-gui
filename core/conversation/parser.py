"""Parser de intenciones: convierte una respuesta en texto libre en un tool call.

Responsabilidad única: dada una respuesta del modelo principal, decidir si
implica el uso de una herramienta y, de ser así, extraer su nombre y argumentos.

Arquitectura:
- Cada herramienta conocida tiene su propio `ToolHeuristic` (detector O(1)).
- El parser orquesta los detectores en orden, sin conocer detalles internos.
- Si ninguno acierta, hay un fallback a LLM secundario.

Ante cualquier fallo retorna `{"needs_tool": False}` para no romper el flujo.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

from llm.prompts import NATURAL_PARSER_PROMPT, PromptManager

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Primitivas regex compartidas
# ---------------------------------------------------------------------------

_FILE_PATH_PATTERN = re.compile(
    r'\b([\w/\-\.]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|md|txt|sh|html|css|'
    r'java|go|rs|cpp|c|h|vue|xml|toml|ini|rb|php|swift|kt|cs|sql))\b',
    re.IGNORECASE,
)

_CODE_BLOCK_PATTERN = re.compile(
    r'```(?:\w+)?\n(.*?)```',
    re.DOTALL,
)

_PYTHON_BLOCK_PATTERN = re.compile(
    r'```(?:python|py)\n(.*?)```',
    re.DOTALL | re.IGNORECASE,
)

_BASH_BLOCK_PATTERN = re.compile(
    r'```(?:bash|sh|shell|console)\n(.*?)```',
    re.DOTALL | re.IGNORECASE,
)

_QUOTED_PATH_PATTERN = re.compile(r'["\']([^\'"\n]{1,200})["\']')
_INLINE_BACKTICK_PATTERN = re.compile(r'`([^`\n]{1,200})`')

_SYSTEM_PATH_PREFIXES = ("/usr", "/etc", "/bin", "/var", "/proc", "http://", "https://")


# ---------------------------------------------------------------------------
# Helpers de extracción
# ---------------------------------------------------------------------------

def _is_safe_path(candidate: str) -> bool:
    """True si el path no apunta a una ubicación de sistema o URL."""
    return not candidate.startswith(_SYSTEM_PATH_PREFIXES)


def _nearest_file_path(text: str, anchor_pos: int) -> Optional[str]:
    """Path con extensión más cercano a anchor_pos."""
    best: Optional[Tuple[int, str]] = None
    for match in _FILE_PATH_PATTERN.finditer(text):
        candidate = match.group(1)
        if not _is_safe_path(candidate):
            continue
        dist = abs(match.start() - anchor_pos)
        if best is None or dist < best[0]:
            best = (dist, candidate)
    return best[1] if best else None


def _first_file_path(text: str) -> Optional[str]:
    """Primer path con extensión válido."""
    for match in _FILE_PATH_PATTERN.finditer(text):
        candidate = match.group(1)
        if _is_safe_path(candidate):
            return candidate
    return None


def _extract_path_or_dir(text: str) -> Optional[str]:
    """Extrae un path entre comillas o backticks (incluye dirs sin extensión)."""
    for pattern in (_QUOTED_PATH_PATTERN, _INLINE_BACKTICK_PATTERN):
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if not candidate or not _is_safe_path(candidate):
                continue
            # Aceptar si contiene "/", empieza con "." o parece un nombre razonable
            if "/" in candidate or candidate.startswith(".") or re.match(r"^[\w\-]+$", candidate):
                return candidate
    return None


# ---------------------------------------------------------------------------
# ToolHeuristic: contrato para detectores por herramienta
# ---------------------------------------------------------------------------

class ToolHeuristic(ABC):
    """Detector heurístico para una herramienta concreta.

    Cada subclase encapsula:
    - Los patrones de intención (futuro/presente, ES + EN).
    - La lógica de extracción de argumentos específica de su tool.
    """

    tool_name: str = ""

    @abstractmethod
    def match(self, response: str) -> Optional[Dict[str, Any]]:
        """Retorna el dict de tool call si detecta intención, o None."""


class WriteFileHeuristic(ToolHeuristic):
    tool_name = "write_file"

    _INTENT = re.compile(
        r'\b(voy a (escribir|crear|implementar|guardar)|'
        r'escribiré|crearé|implementaré|'
        r'escribiendo en|creando el archivo|'
        r'procedo a (escribir|crear)|'
        r'write_file\s*\(|'
        r"i(?:'ll| will| am going to) (write|create|implement|save)|"
        r'writing to|creating (the |a )?file|'
        r'let me (write|create|implement)|'
        # Pasado / declarativo (el modelo "finge" haber escrito ya)
        r'he (creado|escrito|implementado|generado)|'
        r'(he aquí|aquí está|aquí tienes|a continuación)\b[^.]{0,60}\barchivo\b|'
        r'(aquí está|aquí tienes|here(?:\'s| is))\b|'
        r'ha sido creado|fue creado|'
        r"i(?:'ve| have) (created|written|implemented|generated)|"
        r'(el archivo|the file)\s+\S+\s+(ha sido creado|fue creado|contains?|contiene))\b',
        re.IGNORECASE,
    )

    # Indica que el modelo está LEYENDO/ANALIZANDO código, no escribiendo.
    # Si esto aparece, NO disparamos write_file en el fallback.
    _READ_CONTEXT = re.compile(
        r'\b(el código (actual|existente)|este código (es|actual|existente)|'
        r'el archivo (actual|existente|ya) (contiene|tiene|importa)|'
        r'analizando|revisando el contenido|el contenido actual de|'
        r'this (existing|current) (code|file)|the (current|existing) (code|file)|'
        r'analyzing|reviewing the content)\b',
        re.IGNORECASE,
    )

    def match(self, response: str) -> Optional[Dict[str, Any]]:
        has_intent = bool(self._INTENT.search(response))

        code_match = _CODE_BLOCK_PATTERN.search(response)
        if not code_match:
            return None

        content = code_match.group(1)
        if not content.strip():
            return None

        path = _nearest_file_path(response, code_match.start())
        if not path:
            return None

        # Si hay intent explícito, disparar directamente
        if has_intent:
            return {
                "needs_tool": True,
                "tool": "write_file",
                "args": {"path": path, "content": content},
            }

        # Fallback agresivo: code block sustancial + path mencionado y NO es
        # lectura/análisis explícito. Cubre respuestas declarativas del modelo
        # como "El archivo test.py:" + code o "```python\n...\n```\ntest.py".
        if self._READ_CONTEXT.search(response):
            return None

        if len(content.strip()) > 20:
            return {
                "needs_tool": True,
                "tool": "write_file",
                "args": {"path": path, "content": content},
            }

        return None


class ReadFileHeuristic(ToolHeuristic):
    tool_name = "read_file"

    _INTENT = re.compile(
        r'\b(voy a (leer|ver|abrir|revisar|examinar) (el |la |los |las )?(archivo|fichero|contenido)|'
        r'leeré (el |la )?(archivo|fichero)|'
        r'revisando el (archivo|fichero)|'
        r'read_file\s*\(|'
        r"i(?:'ll| will| am going to) (read|open|check|examine) (the )?file|"
        r'reading (the )?file|let me (read|open|check) (the )?file)\b',
        re.IGNORECASE,
    )

    def match(self, response: str) -> Optional[Dict[str, Any]]:
        if not self._INTENT.search(response):
            return None

        path = _first_file_path(response)
        if not path:
            return None

        return {
            "needs_tool": True,
            "tool": "read_file",
            "args": {"path": path},
        }


class ListDirectoryHeuristic(ToolHeuristic):
    tool_name = "list_directory"

    _INTENT = re.compile(
        r'\b(voy a (listar|explorar|ver|inspeccionar) (el |la )?(directorio|carpeta|contenido del)|'
        r'listaré (el |la )?(directorio|carpeta)|'
        r'exploraré (el |la )?(directorio|carpeta)|'
        r'list_directory\s*\(|'
        r"i(?:'ll| will| am going to) (list|explore|inspect) (the )?(directory|folder|contents)|"
        r'listing (the )?(directory|folder)|let me (list|explore) (the )?(directory|folder))\b',
        re.IGNORECASE,
    )

    def match(self, response: str) -> Optional[Dict[str, Any]]:
        if not self._INTENT.search(response):
            return None

        path = _extract_path_or_dir(response) or "."
        return {
            "needs_tool": True,
            "tool": "list_directory",
            "args": {"path": path},
        }


class CreateDirectoryHeuristic(ToolHeuristic):
    tool_name = "create_directory"

    _INTENT = re.compile(
        r'\b(voy a crear (el |la )?(directorio|carpeta)|'
        r'crearé (el |la )?(directorio|carpeta)|'
        r'create_directory\s*\(|'
        r"i(?:'ll| will| am going to) create (the )?(directory|folder)|"
        r'creating (the )?(directory|folder)|let me create (the )?(directory|folder))\b',
        re.IGNORECASE,
    )

    def match(self, response: str) -> Optional[Dict[str, Any]]:
        if not self._INTENT.search(response):
            return None

        path = _extract_path_or_dir(response)
        if not path:
            return None

        return {
            "needs_tool": True,
            "tool": "create_directory",
            "args": {"path": path},
        }


class SearchFilesHeuristic(ToolHeuristic):
    tool_name = "search_files"

    _INTENT = re.compile(
        r'\b(voy a buscar (archivos|ficheros)|'
        r'buscaré (archivos|ficheros)|'
        r'search_files\s*\(|'
        r"i(?:'ll| will| am going to) search (for )?files?|"
        r'searching (for )?files?|let me search (for )?files?)\b',
        re.IGNORECASE,
    )

    _GLOB_QUOTED = re.compile(r'["\']((?:\*\*?/)?\*?\.?[\w\*\.\-/]{1,80})["\']')
    _GLOB_INLINE = re.compile(r'`((?:\*\*?/)?\*?\.?[\w\*\.\-/]{1,80})`')
    _GLOB_BARE = re.compile(r'(?<![\w/])(\*\*?/[\w\*\.\-]+|\*\.\w+|[\w\-]+\*\.\w+)(?![\w])')

    def match(self, response: str) -> Optional[Dict[str, Any]]:
        if not self._INTENT.search(response):
            return None

        pattern = self._extract_pattern(response)
        if not pattern:
            return None

        return {
            "needs_tool": True,
            "tool": "search_files",
            "args": {"pattern": pattern},
        }

    def _extract_pattern(self, text: str) -> Optional[str]:
        for regex in (self._GLOB_QUOTED, self._GLOB_INLINE, self._GLOB_BARE):
            match = regex.search(text)
            if match:
                candidate = match.group(1).strip()
                if "*" in candidate or "." in candidate:
                    return candidate
        return None


class RunCommandHeuristic(ToolHeuristic):
    tool_name = "run_command"

    _INTENT = re.compile(
        r'\b(voy a ejecutar (el |un )?comando|'
        r'ejecutaré (el |un )?comando|'
        r'corriendo (el |un )?comando|'
        r'run_command\s*\(|'
        r'voy a (correr|ejecutar|hacer)\s+(git|npm|pip|python|bash|sh|make|cargo|go|yarn|docker)\b|'
        r'ejecutar[eé]?\s+(git|npm|pip|python|bash|sh|make|cargo|go|yarn|docker)\b|'
        r"i(?:'ll| will| am going to) (run|execute) (the |a )?command|"
        r'running the command|let me (run|execute) (the |a )?command|'
        r"i(?:'ll| will| am going to) (run|execute|do) (a |the )?"
        r'(git|npm|pip|python|bash|make|cargo|yarn|docker)\b)\b',
        re.IGNORECASE,
    )

    # Detects explicit "Voy a ejecutar el comando: `...`" pattern encouraged by the system prompt
    _LABEL = re.compile(
        r'(?:comando|command)[:\s]+`([^\n`]{2,300})`',
        re.IGNORECASE,
    )

    # Detects shell commands in backticks that look like real commands
    _SHELL_CMD_PREFIXES = (
        "git", "npm", "pip", "python", "python3", "bash", "sh",
        "make", "cargo", "go ", "yarn", "docker", "kubectl",
        "ls", "cat", "grep", "find", "cp", "mv", "rm", "mkdir",
        "./", "node", "uvicorn", "pytest", "ruff", "black",
    )

    def match(self, response: str) -> Optional[Dict[str, Any]]:
        # Fast-path: explicit "comando: `...`" label (system prompt–guided format)
        label = self._LABEL.search(response)
        if label:
            cmd = label.group(1).strip().lstrip("$ ")
            if cmd:
                return {"needs_tool": True, "tool": "run_command", "args": {"command": cmd}}

        if not self._INTENT.search(response):
            return None

        command = self._extract_command(response)
        if not command:
            return None

        return {
            "needs_tool": True,
            "tool": "run_command",
            "args": {"command": command},
        }

    def _extract_command(self, text: str) -> Optional[str]:
        # 1. Bloque de código bash/shell explícito
        block = _BASH_BLOCK_PATTERN.search(text)
        if block:
            first_line = block.group(1).strip().splitlines()
            if first_line:
                command = first_line[0].lstrip("$ ").strip()
                if command:
                    return command

        # 2. "comando: xxx" o "command: xxx" (sin backticks)
        label_bare = re.search(r'(?:comando|command)[:\s]+([^\n`]{2,200})', text, re.IGNORECASE)
        if label_bare:
            cmd = label_bare.group(1).strip().strip('`')
            if cmd:
                return cmd

        # 3. Backtick inline that looks like a shell command
        candidates = [m.group(1).strip() for m in _INLINE_BACKTICK_PATTERN.finditer(text)]
        shell_candidates = [
            c for c in candidates
            if c.startswith(self._SHELL_CMD_PREFIXES) and len(c) > 3
        ]
        if shell_candidates:
            return max(shell_candidates, key=len)

        # 4. Any inline backtick with spaces (fallback)
        candidates = [c for c in candidates if " " in c or "/" in c]
        if candidates:
            return max(candidates, key=len)

        return None


class ExecutePythonHeuristic(ToolHeuristic):
    tool_name = "execute_python"

    _INTENT = re.compile(
        r'\b(voy a ejecutar (el |este )?(código|script) (de )?python|'
        r'ejecutaré (el |este )?(código|script) (de )?python|'
        r'execute_python\s*\(|'
        r"i(?:'ll| will| am going to) (run|execute) (the |this )?python (code|script)|"
        r'running (the |this )?python|let me (run|execute) (the |this )?python)\b',
        re.IGNORECASE,
    )

    def match(self, response: str) -> Optional[Dict[str, Any]]:
        if not self._INTENT.search(response):
            return None

        block = _PYTHON_BLOCK_PATTERN.search(response)
        if not block:
            return None

        code = block.group(1).strip()
        if not code:
            return None

        return {
            "needs_tool": True,
            "tool": "execute_python",
            "args": {"code": code},
        }


# ---------------------------------------------------------------------------
# Set por defecto
# Orden importa: las heurísticas más específicas (con bloque de código + intent)
# van primero para evitar falsos positivos en heurísticas más laxas.
# ---------------------------------------------------------------------------

DEFAULT_HEURISTICS: List[ToolHeuristic] = [
    WriteFileHeuristic(),
    ExecutePythonHeuristic(),
    RunCommandHeuristic(),
    ReadFileHeuristic(),
    SearchFilesHeuristic(),
    CreateDirectoryHeuristic(),
    ListDirectoryHeuristic(),
]


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

class NaturalResponseParser:
    """Segunda llamada al LLM: extrae tool call desde texto libre.

    Cadena de detección:
        1. Heurísticas por tool (O(1), sin LLM).
        2. JSON inline embebido en la respuesta.
        3. Fallback: LLM secundario forzando formato JSON.

    Cada resultado positivo incluye `"source"` indicando su origen
    (`"heuristic"`, `"inline_json"`, `"llm"`) para diagnóstico.
    """

    _MAX_RESPONSE_LEN = 2000  # Límite enviado al LLM parser

    def __init__(
        self,
        llm_call: Callable[[List[Dict[str, Any]], Optional[str]], str],
        dynamic_tool_names: Optional[List[str]] = None,
        extra_heuristics: Optional[List[ToolHeuristic]] = None,
    ) -> None:
        """
        Args:
            llm_call: callable(messages, fmt) → respuesta del modelo.
                      fmt="json" cuando se necesite forzar JSON.
            dynamic_tool_names: nombres de tools dinámicas (MCP, etc.) que
                                deben aparecer en el prompt del parser LLM.
            extra_heuristics: heurísticas adicionales para tools dinámicas.
        """
        self._llm_call = llm_call
        self._dynamic_tool_names = dynamic_tool_names or []
        self._heuristics: List[ToolHeuristic] = list(DEFAULT_HEURISTICS)
        if extra_heuristics:
            self._heuristics.extend(extra_heuristics)
        self._parser_prompt: Optional[str] = None

    def parse(self, response: str) -> Dict[str, Any]:
        """Analiza una respuesta y retorna la intención detectada.

        Returns:
            {"needs_tool": False}
            o
            {"needs_tool": True, "tool": "<nombre>", "args": {...}, "source": "..."}
        """
        # 1. Heurísticas por tool
        for heuristic in self._heuristics:
            try:
                result = heuristic.match(response)
            except Exception as exc:
                _logger.warning("Heurística %s falló: %s", heuristic.tool_name, exc)
                continue
            if result:
                result.setdefault("source", "heuristic")
                return result

        # 2. JSON inline
        inline = self._extract_inline_json_tool(response)
        if inline:
            inline.setdefault("source", "inline_json")
            return inline

        # 3. Fallback LLM
        result = self._llm_parse(response)
        if result.get("needs_tool"):
            result.setdefault("source", "llm")
        return result

    # ------------------------------------------------------------------
    # Inline JSON
    # ------------------------------------------------------------------

    def _extract_inline_json_tool(self, response: str) -> Optional[Dict[str, Any]]:
        """Detecta si el modelo embebió un JSON de tool call directamente.

        Walk brace-by-brace para soportar objetos anidados (e.g. {"args": {...}}).
        """
        for open_match in re.finditer(r'\{', response):
            start = open_match.start()
            depth = 0
            end = start
            for i, ch in enumerate(response[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            else:
                continue

            candidate = response[start:end]
            if '"tool"' not in candidate and '"needs_tool"' not in candidate:
                continue
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            if "tool" not in data and "needs_tool" not in data:
                continue
            if "needs_tool" not in data and "tool" in data:
                data["needs_tool"] = True
            return data
        return None

    # ------------------------------------------------------------------
    # Fallback LLM
    # ------------------------------------------------------------------

    def _llm_parse(self, response: str) -> Dict[str, Any]:
        """Delega al modelo secundario cuando ninguna heurística detectó nada."""
        truncated = response[: self._MAX_RESPONSE_LEN]
        messages = [
            {"role": "system", "content": self._get_parser_prompt()},
            {"role": "user", "content": truncated},
        ]

        try:
            raw = self._llm_call(messages, "json").strip()
            raw = self._strip_markdown_fences(raw)
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as exc:
            _logger.debug("Parser LLM returned malformed JSON: %s", exc)
        except Exception as exc:
            _logger.warning("Unexpected error in parser LLM call: %s", exc)

        return {"needs_tool": False}

    def _get_parser_prompt(self) -> str:
        """Construye y cachea el prompt del parser (estático tras __init__)."""
        if self._parser_prompt is None:
            extra: List[str] = [
                f"{name}(...) → herramienta dinámica registrada"
                for name in self._dynamic_tool_names
            ]
            tools_desc = PromptManager.get_tools_description_for_parser(extra or None)
            self._parser_prompt = NATURAL_PARSER_PROMPT.format(tools_description=tools_desc)
        return self._parser_prompt

    @staticmethod
    def _strip_markdown_fences(raw: str) -> str:
        """Quita bloques ```...``` si el modelo envuelve la respuesta."""
        if raw.startswith("```"):
            lines = raw.splitlines()
            return "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return raw
