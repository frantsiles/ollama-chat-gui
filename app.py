import base64
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

from ollama_client import OllamaClient, OllamaClientError


DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "")
DEFAULT_WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.getcwd())
TEXT_FILE_EXTENSIONS = (".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml", ".py", ".log")
MAX_TEXT_CHARS_PER_FILE = 12000
MAX_FILE_SIZE_MB = 8
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_SCAN_RESULTS = 300
MAX_READ_CHARS = 30000
MAX_COMMAND_OUTPUT_CHARS = 30000
COMMAND_TIMEOUT_SECONDS = 30
CHAT_COMMAND_PREFIX = "/cmd"
MAX_AGENT_STEPS = 8
MAX_AUTOCONTEXT_ENTRIES = 60
MAX_RAG_CONTEXT_CHARS = 10000
MAX_RAG_FILES = 120
MAX_RAG_FILE_CHARS = 16000
MAX_RAG_CHUNK_CHARS = 1200
MAX_RAG_TOP_CHUNKS = 6
MAX_TOOL_REPAIR_CHARS = 16000
CHAT_EXPORT_DIRNAME = ".chat_exports"
RAG_IGNORED_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}
RAG_TRIGGER_TERMS = (
    "proyecto",
    "readme",
    "repo",
    "repository",
    "arquitectura",
    "repositorio",
    "análisis",
    "analisis",
    "analiza",
    "código",
    "codigo",
    "source",
    "fuente",
)
READ_INTENT_TERMS = ("lee", "leer", "leé", "resume", "resumí", "resúmeme", "explica", "analiza")
ACTION_INTENT_TERMS = (
    "analiza",
    "analizar",
    "revisa",
    "revisar",
    "inspecciona",
    "inspeccionar",
    "busca",
    "buscar",
    "encuentra",
    "encontrar",
    "documenta",
    "documentar",
    "actualiza",
    "actualizar",
    "edita",
    "editar",
    "modifica",
    "modificar",
    "corrige",
    "corregir",
    "crea",
    "crear",
    "genera",
    "generar",
    "ejecuta",
    "ejecutar",
    "implementa",
    "implementar",
    "refactoriza",
    "refactorizar",
)
WRITE_INTENT_TERMS = (
    "edita",
    "editar",
    "edición",
    "modifica",
    "modificar",
    "actualiza",
    "actualizar",
    "actualice",
    "actualices",
    "actualicen",
    "actualize",
    "reescribe",
    "reescribir",
    "corrige",
    "corregir",
    "ajusta",
    "ajustar",
    "cambia",
    "cambiar",
    "crea",
    "crear",
    "crees",
    "genera",
    "generar",
    "genere",
    "escribe",
    "escribir",
    "sobrescribe",
    "sobrescribir",
    "edit",
    "update",
    "modify",
    "rewrite",
)
APPEND_INTENT_TERMS = (
    "agrega",
    "agregar",
    "añade",
    "añadir",
    "anexa",
    "anexar",
    "append",
    "al final",
    "al inicio",
    "inserta",
    "insertar",
    "add",
)
EXPLICIT_OVERWRITE_INTENT_TERMS = (
    "sobrescribe completo",
    "sobrescribir completo",
    "sobrescribe todo",
    "sobrescribir todo",
    "reemplaza todo",
    "replace entire",
    "replace all",
    "desde cero",
    "from scratch",
)
FILE_REF_PATTERN = re.compile(
    r"\b([a-zA-Z0-9_\-./]+\.(?:md|txt|py|json|yaml|yml|toml|csv|xml|log))\b",
    re.IGNORECASE,
)
REPLACE_PROMPT_PATTERNS = (
    re.compile(
        r"reemplaza\s+[\"'“”‘’](.+?)[\"'“”‘’]\s+por\s+[\"'“”‘’](.+?)[\"'“”‘’]",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"replace\s+[\"'“”‘’](.+?)[\"'“”‘’]\s+with\s+[\"'“”‘’](.+?)[\"'“”‘’]",
        re.IGNORECASE | re.DOTALL,
    ),
)
TOOL_JSON_CODE_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.IGNORECASE | re.DOTALL,
)
WRITE_COMMAND_PREFIXES = {
    "rm",
    "mv",
    "cp",
    "touch",
    "mkdir",
    "rmdir",
    "chmod",
    "chown",
    "ln",
    "tee",
    "truncate",
    "dd",
    "sed",
    "awk",
    "perl",
}
BLOCKED_COMMAND_PATTERNS = (
    (
        re.compile(r"(^|[;&|])\s*sudo\b", re.IGNORECASE),
        "Bloqueado por seguridad: no se permite `sudo`.",
    ),
    (
        re.compile(r"\brm\s+-rf\s+/(?:\s|$)", re.IGNORECASE),
        "Bloqueado por seguridad: patrón peligroso detectado (`rm -rf /`).",
    ),
    (
        re.compile(r"\bmkfs(\.[a-z0-9]+)?\b", re.IGNORECASE),
        "Bloqueado por seguridad: no se permite formatear dispositivos.",
    ),
    (
        re.compile(r"\bdd\s+[^\n]*\bof=/dev/", re.IGNORECASE),
        "Bloqueado por seguridad: escritura directa en `/dev/*` no permitida.",
    ),
    (
        re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\};:", re.IGNORECASE),
        "Bloqueado por seguridad: patrón de fork bomb detectado.",
    ),
    (
        re.compile(r"\b(shutdown|reboot|poweroff|halt)\b", re.IGNORECASE),
        "Bloqueado por seguridad: no se permite apagar o reiniciar el sistema.",
    ),
)
WRITE_COMMAND_OPERATORS = (">", ">>", "| tee", "sed -i")
WRITE_GIT_SUBCOMMANDS = {
    "add",
    "apply",
    "am",
    "branch",
    "checkout",
    "cherry-pick",
    "clean",
    "commit",
    "merge",
    "push",
    "rebase",
    "reset",
    "revert",
    "rm",
    "stash",
    "switch",
    "tag",
}
SUPPORTED_TOOL_NAMES = {"run_command", "read_file", "write_file", "create_directory", "list_directory"}
TOOL_PROTOCOL_SYSTEM_PROMPT = (
    "Eres un agente de IA autónomo para tareas de desarrollo en un workspace local. "
    "Sigue un ciclo ReAct: planifica el siguiente paso, ejecuta una sola tool cuando sea "
    "necesario, evalúa la observación y repite hasta completar la tarea. "
    "Reglas estrictas: "
    "1) Si necesitas una tool, responde SOLO JSON válido sin markdown ni texto extra con "
    "formato {\"tool\":\"run_command\",\"args\":{\"command\":\"ls -la\"}}. "
    "2) Usa máximo una tool por iteración. "
    "3) Cuando ya no necesites tools, responde en lenguaje natural con la solución final. "
    "4) No pidas al usuario pegar archivos del workspace; usa read_file/list_directory. "
    "5) Para editar usa write_file, usa append=true para agregar contenido y preserva el resto "
    "del archivo cuando la edición sea parcial. "
    "6) Nunca devuelvas pseudo-JSON o JSON inválido; si decides usar tool, corrige y entrega JSON válido. "
    "7) Si el usuario da una instrucción directa accionable, avanza con tools y evita pedir detalles "
    "innecesarios; aplica el cambio mínimo seguro posible. "
    "Herramientas permitidas: "
    "run_command(command), read_file(path), write_file(path, content, append=false), "
    "create_directory(path), list_directory(path='.', recursive=false)."
)


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, Any]] = []
    if "models" not in st.session_state:
        st.session_state.models = []
    if "model_capabilities" not in st.session_state:
        st.session_state.model_capabilities = {}
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0
    if "workspace_root" not in st.session_state:
        st.session_state.workspace_root = DEFAULT_WORKSPACE_ROOT
    if "command_cwd" not in st.session_state:
        st.session_state.command_cwd = DEFAULT_WORKSPACE_ROOT
    if "allow_write_commands_always" not in st.session_state:
        st.session_state.allow_write_commands_always = False
    if "pending_command" not in st.session_state:
        st.session_state.pending_command = ""
    if "pending_command_cwd" not in st.session_state:
        st.session_state.pending_command_cwd = ""
    if "pending_tool_request" not in st.session_state:
        st.session_state.pending_tool_request = ""
    if "pending_tool_request_cwd" not in st.session_state:
        st.session_state.pending_tool_request_cwd = ""
    if "pending_agent_loop" not in st.session_state:
        st.session_state.pending_agent_loop = False
    if "last_rag_sources" not in st.session_state:
        st.session_state.last_rag_sources = []
    if "last_agent_trace" not in st.session_state:
        st.session_state.last_agent_trace = []
    if "last_chat_export_path" not in st.session_state:
        st.session_state.last_chat_export_path = ""


def _resolve_workspace_root(root_text: str) -> Path:
    return Path(root_text).expanduser().resolve()


def _safe_resolve_path(workspace_root: Path, target: str) -> Path:
    if not target.strip():
        target = "."

    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = workspace_root / target_path

    resolved = target_path.resolve()
    workspace = workspace_root.resolve()
    if os.path.commonpath([str(workspace), str(resolved)]) != str(workspace):
        raise ValueError("Ruta fuera del workspace permitido.")
    return resolved


def _safe_resolve_path_from(workspace_root: Path, base_dir: Path, target: str) -> Path:
    if not target.strip():
        target = "."

    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = base_dir / target_path

    resolved = target_path.resolve()
    workspace = workspace_root.resolve()
    if os.path.commonpath([str(workspace), str(resolved)]) != str(workspace):
        raise ValueError("Ruta fuera del workspace permitido.")
    return resolved


def _scan_directory(workspace_root: Path, target: str, recursive: bool) -> str:
    root = _safe_resolve_path(workspace_root, target)
    if not root.exists():
        raise ValueError("La carpeta indicada no existe.")
    if not root.is_dir():
        raise ValueError("La ruta indicada no es una carpeta.")

    iterator = root.rglob("*") if recursive else root.glob("*")
    entries: List[str] = []
    for path in iterator:
        if len(entries) >= MAX_SCAN_RESULTS:
            break
        rel = path.relative_to(workspace_root)
        suffix = "/" if path.is_dir() else ""
        entries.append(f"{rel}{suffix}")

    if not entries:
        return f"Scan de `{root.relative_to(workspace_root)}`: no se encontraron entradas."

    return (
        f"Scan de `{root.relative_to(workspace_root)}` "
        f"(mostrando hasta {MAX_SCAN_RESULTS} resultados):\n"
        + "\n".join(f"- {entry}" for entry in entries)
    )


def _read_text_file(workspace_root: Path, target: str) -> str:
    file_path = _safe_resolve_path(workspace_root, target)
    if not file_path.exists():
        raise ValueError("El archivo indicado no existe.")
    if not file_path.is_file():
        raise ValueError("La ruta indicada no es un archivo.")

    raw = file_path.read_bytes()
    text = None
    for encoding in ("utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("No se pudo decodificar el archivo como texto.")

    trimmed = text[:MAX_READ_CHARS]
    suffix = ""
    if len(text) > MAX_READ_CHARS:
        suffix = "\n...[contenido recortado]..."

    rel = file_path.relative_to(workspace_root)
    return f"Contenido de `{rel}`:\n\n{trimmed}{suffix}"


def _write_text_file(workspace_root: Path, target: str, content: str, append: bool) -> str:
    file_path = _safe_resolve_path(workspace_root, target)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with file_path.open("a", encoding="utf-8") as fh:
            fh.write(content)
    else:
        file_path.write_text(content, encoding="utf-8")

    rel = file_path.relative_to(workspace_root)
    mode = "append" if append else "overwrite"
    return f"Escritura exitosa en `{rel}` (modo: {mode}, chars: {len(content)})."


def _add_system_context(context: str) -> None:
    st.session_state.messages.append({"role": "system", "content": context})

def _filter_exportable_messages(messages: List[Dict[str, Any]], include_system: bool) -> List[Dict[str, Any]]:
    exportable: List[Dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role", "")).strip().lower()
        if role not in {"user", "assistant", "system"}:
            continue
        if role == "system" and not include_system:
            continue
        attachments = msg.get("attachments") or []
        exportable.append(
            {
                "role": role,
                "content": str(msg.get("content", "")),
                "attachments": list(attachments),
            }
        )
    return exportable


def _build_chat_export_markdown(messages: List[Dict[str, Any]]) -> str:
    role_labels = {"user": "Usuario", "assistant": "Asistente", "system": "Sistema"}
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: List[str] = [
        "# Export de Chat",
        "",
        f"- Generado: {timestamp}",
        f"- Mensajes: {len(messages)}",
        "",
    ]
    for index, msg in enumerate(messages, start=1):
        role = str(msg.get("role", ""))
        label = role_labels.get(role, role.capitalize())
        lines.append(f"## {index}. {label}")
        lines.append("")
        attachments = msg.get("attachments", [])
        if attachments:
            lines.append(f"Adjuntos: {', '.join(str(item) for item in attachments)}")
            lines.append("")
        content = str(msg.get("content", "")).strip()
        lines.append(content if content else "[sin contenido]")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_chat_export_json(messages: List[Dict[str, Any]]) -> str:
    payload = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "message_count": len(messages),
        "messages": messages,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _export_chat_to_workspace(
    workspace_root: Path,
    messages: List[Dict[str, Any]],
    export_format: str,
    include_system: bool,
) -> Path:
    if not workspace_root.exists() or not workspace_root.is_dir():
        raise ValueError("Workspace root inválido para exportación.")

    normalized_format = export_format.strip().lower()
    if normalized_format not in {"markdown", "json"}:
        raise ValueError("Formato de exportación no soportado.")

    exportable_messages = _filter_exportable_messages(messages=messages, include_system=include_system)
    if not exportable_messages:
        raise ValueError("No hay mensajes para exportar.")

    export_dir = workspace_root / CHAT_EXPORT_DIRNAME
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    extension = "md" if normalized_format == "markdown" else "json"
    export_path = export_dir / f"chat_export_{timestamp}.{extension}"

    if normalized_format == "markdown":
        content = _build_chat_export_markdown(exportable_messages)
    else:
        content = _build_chat_export_json(exportable_messages)

    export_path.write_text(content, encoding="utf-8")
    return export_path


def _validate_command_safety(command: str) -> str | None:
    stripped = command.strip()
    if not stripped:
        return "Debes indicar un comando."
    if len(stripped) > 1200:
        return "Comando demasiado largo para ejecución segura."
    if stripped in {"cd", "c..", "cd.."}:
        return None
    if stripped.startswith("cd "):
        try:
            tokens = shlex.split(stripped)
        except ValueError:
            return "Comando `cd` inválido."
        if tokens and tokens[0] == "cd" and len(tokens) <= 2:
            return None

    for pattern, message in BLOCKED_COMMAND_PATTERNS:
        if pattern.search(stripped):
            return message
    return None


def _run_workspace_command(command_cwd: Path, command: str) -> str:
    if not command.strip():
        raise ValueError("Debes indicar un comando.")

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=command_cwd,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"El comando superó el timeout de {COMMAND_TIMEOUT_SECONDS}s."
        ) from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    combined = (
        f"CWD: {command_cwd}\n"
        f"Comando: {command}\n"
        f"Exit code: {result.returncode}\n\n"
        f"STDOUT:\n{stdout or '[vacío]'}\n\n"
        f"STDERR:\n{stderr or '[vacío]'}"
    )
    if len(combined) > MAX_COMMAND_OUTPUT_CHARS:
        combined = combined[:MAX_COMMAND_OUTPUT_CHARS] + "\n...[salida recortada]..."
    return combined


def _extract_text(uploaded_file: Any) -> str | None:
    raw = uploaded_file.getvalue()
    if not raw:
        return None

    for encoding in ("utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None

    if len(text) > MAX_TEXT_CHARS_PER_FILE:
        return text[:MAX_TEXT_CHARS_PER_FILE] + "\n...[contenido recortado]..."
    return text


def _parse_chat_command(prompt: str) -> str | None:
    stripped = prompt.strip()
    if not stripped.startswith(CHAT_COMMAND_PREFIX):
        return None

    command = stripped[len(CHAT_COMMAND_PREFIX) :].strip()
    if not command:
        raise ValueError("Debes indicar un comando luego de /cmd.")
    return command


def _ensure_command_cwd(workspace_root: Path) -> Path:
    candidate = Path(st.session_state.command_cwd).expanduser().resolve()
    workspace = workspace_root.resolve()
    if not candidate.exists() or not candidate.is_dir():
        st.session_state.command_cwd = str(workspace)
        return workspace
    if os.path.commonpath([str(workspace), str(candidate)]) != str(workspace):
        st.session_state.command_cwd = str(workspace)
        return workspace
    return candidate


def _relative_path_label(workspace_root: Path, target: Path) -> str:
    if target.resolve() == workspace_root.resolve():
        return "."
    return str(target.resolve().relative_to(workspace_root.resolve()))


def _normalize_directory_command(command: str) -> str:
    stripped = command.strip()
    if stripped in {"c..", "cd.."}:
        return "cd .."
    return command


def _execute_workspace_command_with_cd(
    workspace_root: Path, command_cwd: Path, command: str
) -> tuple[str, Path]:
    stripped = _normalize_directory_command(command).strip()
    safety_error = _validate_command_safety(stripped)
    if safety_error:
        raise ValueError(safety_error)
    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        raise ValueError(f"Comando inválido: {exc}") from exc

    if tokens and tokens[0] == "cd":
        if len(tokens) > 2:
            raise ValueError("El comando `cd` solo permite una ruta sin operadores adicionales.")
        target = tokens[1] if len(tokens) > 1 else "."
        new_cwd = _safe_resolve_path_from(workspace_root, command_cwd, target)
        if not new_cwd.exists() or not new_cwd.is_dir():
            raise ValueError("La ruta indicada no existe o no es una carpeta.")
        rel = _relative_path_label(workspace_root, new_cwd)
        return f"CWD actualizado a `{rel}` ({new_cwd})", new_cwd

    result = _run_workspace_command(command_cwd=command_cwd, command=command)
    return result, command_cwd


def _build_workspace_context(workspace_root: Path, command_cwd: Path) -> str:
    rel = _relative_path_label(workspace_root, command_cwd)
    entries: List[str] = []
    for path in command_cwd.glob("*"):
        suffix = "/" if path.is_dir() else ""
        entries.append(f"{path.name}{suffix}")
        if len(entries) >= MAX_AUTOCONTEXT_ENTRIES:
            break

    entries_text = "\n".join(f"- {entry}" for entry in entries) if entries else "- [vacío]"
    return (
        "Contexto automático de workspace:\n"
        f"- Workspace root: {workspace_root}\n"
        f"- Directorio actual: {command_cwd} (relativo: {rel})\n"
        f"- Entradas en directorio actual (hasta {MAX_AUTOCONTEXT_ENTRIES}):\n"
        f"{entries_text}"
    )


def _is_probably_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_FILE_EXTENSIONS:
        return True
    return path.name.lower() in {"readme", "readme.md", "license", "pyproject.toml", "requirements.txt"}


def _chunk_text(text: str, max_chars: int) -> List[str]:
    chunks: List[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[i : i + max_chars])
            continue
        if not current:
            current = paragraph
            continue
        if len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _tokenize_for_rag(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-zA-Z0-9_áéíóúñÁÉÍÓÚÑ]{3,}", text.lower())]


def _iter_rag_candidate_files(workspace_root: Path) -> List[Path]:
    files: List[Path] = []
    for path in workspace_root.rglob("*"):
        if any(part in RAG_IGNORED_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if not _is_probably_text_file(path):
            continue
        files.append(path)
        if len(files) >= MAX_RAG_FILES:
            break
    return files


def _read_text_file_safely(path: Path, max_chars: int) -> str | None:
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None
    return text[:max_chars]


def _build_local_rag_context(workspace_root: Path, user_prompt: str) -> tuple[str | None, List[str]]:
    query_tokens = _tokenize_for_rag(user_prompt)
    if not query_tokens:
        return None, []

    scored_chunks: List[tuple[int, str, Path]] = []
    candidate_files = _iter_rag_candidate_files(workspace_root)
    query_set = set(query_tokens)

    for path in candidate_files:
        text = _read_text_file_safely(path, max_chars=MAX_RAG_FILE_CHARS)
        if not text:
            continue
        for chunk in _chunk_text(text, max_chars=MAX_RAG_CHUNK_CHARS):
            chunk_tokens = set(_tokenize_for_rag(chunk))
            overlap = len(query_set.intersection(chunk_tokens))
            if overlap <= 0:
                continue
            bonus = 2 if path.name.lower().startswith("readme") else 0
            score = overlap + bonus
            scored_chunks.append((score, chunk, path))

    if not scored_chunks:
        return None, []

    scored_chunks.sort(key=lambda item: item[0], reverse=True)
    top = scored_chunks[:MAX_RAG_TOP_CHUNKS]
    context_blocks: List[str] = []
    source_paths: List[str] = []
    total_chars = 0

    for _, chunk, path in top:
        rel_path = str(path.relative_to(workspace_root))
        block = f"[Fuente: {rel_path}]\n{chunk}"
        projected = total_chars + len(block) + 2
        if projected > MAX_RAG_CONTEXT_CHARS:
            break
        context_blocks.append(block)
        total_chars = projected
        if rel_path not in source_paths:
            source_paths.append(rel_path)

    if not context_blocks:
        return None, []

    context = "Contexto RAG local recuperado del workspace:\n\n" + "\n\n".join(context_blocks)
    return context, source_paths


def _maybe_add_project_rag_context(workspace_root: Path, user_prompt: str) -> None:
    prompt_lower = user_prompt.lower()
    if not any(term in prompt_lower for term in RAG_TRIGGER_TERMS):
        st.session_state.last_rag_sources = []
        return
    rag_context, sources = _build_local_rag_context(workspace_root=workspace_root, user_prompt=user_prompt)
    st.session_state.last_rag_sources = sources
    if rag_context:
        _add_system_context(rag_context)


def _is_question_like_prompt(user_prompt: str) -> bool:
    stripped = user_prompt.strip().lower()
    if not stripped:
        return False
    if "?" in stripped:
        return True
    question_prefixes = (
        "qué ",
        "que ",
        "cómo ",
        "como ",
        "cuál ",
        "cual ",
        "por qué ",
        "porque ",
        "how ",
        "what ",
        "why ",
    )
    return any(stripped.startswith(prefix) for prefix in question_prefixes)


def _is_action_intent_prompt(user_prompt: str) -> bool:
    if _is_question_like_prompt(user_prompt):
        return False
    prompt_lower = user_prompt.lower()
    if _is_write_intent_prompt(user_prompt):
        return True
    if any(term in prompt_lower for term in ACTION_INTENT_TERMS):
        return True
    return False

def _is_write_intent_prompt(user_prompt: str) -> bool:
    prompt_lower = user_prompt.lower()
    return any(term in prompt_lower for term in WRITE_INTENT_TERMS)

def _is_append_intent_prompt(user_prompt: str) -> bool:
    prompt_lower = user_prompt.lower()
    return any(term in prompt_lower for term in APPEND_INTENT_TERMS)


def _is_explicit_overwrite_intent_prompt(user_prompt: str) -> bool:
    prompt_lower = user_prompt.lower()
    return any(term in prompt_lower for term in EXPLICIT_OVERWRITE_INTENT_TERMS)


def _extract_replace_instruction(user_prompt: str) -> tuple[str, str] | None:
    for pattern in REPLACE_PROMPT_PATTERNS:
        match = pattern.search(user_prompt)
        if not match:
            continue
        before = match.group(1)
        after = match.group(2)
        if before:
            return before, after
    return None


def _read_text_file_raw(path: Path) -> str | None:
    raw = path.read_bytes()
    for encoding in ("utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _extract_requested_files_from_prompt(workspace_root: Path, user_prompt: str) -> List[str]:
    prompt_lower = user_prompt.lower()
    has_read_intent = any(term in prompt_lower for term in READ_INTENT_TERMS)
    has_write_intent = _is_write_intent_prompt(user_prompt)
    if not has_read_intent and not has_write_intent:
        return []

    requested: List[str] = []
    if "readme" in prompt_lower:
        for candidate in ("README.md", "readme.md"):
            path = workspace_root / candidate
            if path.exists() and path.is_file():
                requested.append(candidate)
                break

    for match in FILE_REF_PATTERN.findall(user_prompt):
        candidate = match.strip()
        if candidate and candidate not in requested:
            requested.append(candidate)
    return requested


def _maybe_add_requested_file_context(workspace_root: Path, user_prompt: str) -> None:
    requested_files = _extract_requested_files_from_prompt(workspace_root, user_prompt)
    if not requested_files:
        return

    blocks: List[str] = []
    for file_ref in requested_files[:3]:
        try:
            content = _read_text_file(workspace_root=workspace_root, target=file_ref)
            blocks.append(content)
        except ValueError:
            continue

    if blocks:
        _add_system_context(
            "Contexto de archivo(s) solicitado(s) por el usuario:\n\n" + "\n\n---\n\n".join(blocks)
        )


def _is_write_or_edit_command(command: str) -> bool:
    normalized = command.strip().lower()
    if any(operator in normalized for operator in WRITE_COMMAND_OPERATORS):
        return True

    try:
        tokens = shlex.split(command)
    except ValueError:
        return True
    if not tokens:
        return False

    first = tokens[0].lower()
    if first == "cd":
        return False
    if first in WRITE_COMMAND_PREFIXES:
        return True
    if first == "git" and len(tokens) > 1 and tokens[1].lower() in WRITE_GIT_SUBCOMMANDS:
        return True
    return False


def _extract_json_candidates(text: str) -> List[str]:
    stripped = text.strip()
    if not stripped:
        return []

    candidates: List[str] = []
    for match in TOOL_JSON_CODE_BLOCK_PATTERN.findall(text):
        candidate = match.strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, consumed = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        candidate = text[index : index + consumed].strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _normalize_write_file_tool_request(
    workspace_root: Path,
    user_prompt: str,
    tool_request: Dict[str, Any],
) -> tuple[Dict[str, Any], str | None]:
    if tool_request.get("tool") != "write_file":
        return tool_request, None

    args = dict(tool_request.get("args", {}))
    target = str(args.get("path", "")).strip()
    if not target:
        return tool_request, None

    file_path = _safe_resolve_path(workspace_root, target)
    if not file_path.exists() or not file_path.is_file():
        return {"tool": "write_file", "args": args}, None

    existing_text = _read_text_file_raw(file_path)
    if existing_text is None:
        return {"tool": "write_file", "args": args}, None

    append = bool(args.get("append", False))
    content = str(args.get("content", ""))
    replace_instruction = _extract_replace_instruction(user_prompt)

    if replace_instruction and not append:
        before, after = replace_instruction
        if before in existing_text:
            args["append"] = False
            args["content"] = existing_text.replace(before, after)
            return (
                {"tool": "write_file", "args": args},
                "Se aplicó reemplazo seguro preservando el resto del archivo.",
            )

    if _is_append_intent_prompt(user_prompt) and not append:
        if content and existing_text and not existing_text.endswith("\n") and not content.startswith("\n"):
            content = "\n\n" + content
        args["append"] = True
        args["content"] = content
        return (
            {"tool": "write_file", "args": args},
            "Se ajustó la solicitud a append=true para evitar sobrescribir el archivo completo.",
        )

    if (
        _is_write_intent_prompt(user_prompt)
        and not append
        and not _is_explicit_overwrite_intent_prompt(user_prompt)
    ):
        existing_len = len(existing_text)
        new_len = len(content)
        if existing_len >= 200 and new_len < int(existing_len * 0.6):
            raise ValueError(
                "Bloqueado para evitar sobrescritura destructiva: la IA intentó reemplazar un "
                "archivo existente con contenido parcial. Si querías reemplazar todo, indícalo "
                "explícitamente con 'sobrescribe completo'."
            )

    return {"tool": "write_file", "args": args}, None


def _extract_tool_request(assistant_text: str) -> Dict[str, Any] | None:
    for candidate in _extract_json_candidates(assistant_text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        tool_name = parsed.get("tool")
        args = parsed.get("args", {})
        if not isinstance(tool_name, str) or tool_name not in SUPPORTED_TOOL_NAMES:
            continue
        if not isinstance(args, dict):
            continue
        return {"tool": tool_name, "args": args}
    return None

def _looks_like_tool_request_text(assistant_text: str) -> bool:
    normalized = assistant_text.lower()
    if "\"tool\"" in normalized and "\"args\"" in normalized:
        return True
    if "{" not in normalized:
        return False
    return any(tool_name in normalized for tool_name in SUPPORTED_TOOL_NAMES)


def _attempt_tool_request_repair_from_text(
    client: OllamaClient,
    model: str,
    temperature: float,
    assistant_text: str,
) -> Dict[str, Any] | None:
    trimmed = assistant_text.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_TOOL_REPAIR_CHARS:
        trimmed = trimmed[:MAX_TOOL_REPAIR_CHARS]

    recovery_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": TOOL_PROTOCOL_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Recibirás una solicitud de tool potencialmente malformada. "
                "Convierte esa solicitud a JSON válido de una tool soportada, sin explicaciones. "
                "Si no hay una solicitud de tool clara, responde `{}`."
            ),
        },
        {
            "role": "user",
            "content": f"Corrige y devuelve solo JSON válido:\n\n{trimmed}",
        },
    ]
    chunks: List[str] = []
    try:
        for chunk in client.chat_stream(
            model=model,
            messages=recovery_messages,
            options={"temperature": temperature},
        ):
            chunks.append(chunk)
    except OllamaClientError:
        return None
    recovery_text = "".join(chunks)
    return _extract_tool_request(recovery_text)


def _attempt_tool_request_recovery(
    client: OllamaClient,
    model: str,
    temperature: float,
    messages: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    recovery_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": TOOL_PROTOCOL_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "El usuario pidió una acción de edición/escritura de archivos en el workspace. "
                "Responde SOLO con un JSON válido de una herramienta soportada, sin texto extra, "
                "sin markdown y sin explicaciones."
            ),
        },
        *messages,
        {
            "role": "user",
            "content": (
                "Devuelve únicamente la solicitud JSON de herramienta necesaria para aplicar los "
                "cambios solicitados."
            ),
        },
    ]
    chunks: List[str] = []
    try:
        for chunk in client.chat_stream(
            model=model,
            messages=recovery_messages,
            options={"temperature": temperature},
        ):
            chunks.append(chunk)
    except OllamaClientError:
        return None
    recovery_text = "".join(chunks)
    return _extract_tool_request(recovery_text)


def _attempt_action_tool_request_recovery(
    client: OllamaClient,
    model: str,
    temperature: float,
    messages: List[Dict[str, Any]],
    user_prompt: str,
    assistant_text: str,
) -> Dict[str, Any] | None:
    trimmed_assistant = assistant_text.strip()
    if len(trimmed_assistant) > MAX_TOOL_REPAIR_CHARS:
        trimmed_assistant = trimmed_assistant[:MAX_TOOL_REPAIR_CHARS]

    recovery_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": TOOL_PROTOCOL_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "El usuario dio una instrucción directa y accionable. "
                "Debes avanzar con la siguiente tool ejecutable y NO pedir más detalles, "
                "salvo que sea imposible continuar de forma segura. "
                "Responde SOLO JSON válido de una tool soportada."
            ),
        },
        *messages[-18:],
        {
            "role": "system",
            "content": (
                "Última respuesta del asistente (si no fue tool):\n"
                f"{trimmed_assistant or '[vacía]'}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Instrucción original del usuario:\n{user_prompt}\n\n"
                "Devuelve solo JSON válido con la siguiente acción."
            ),
        },
    ]
    chunks: List[str] = []
    try:
        for chunk in client.chat_stream(
            model=model,
            messages=recovery_messages,
            options={"temperature": temperature},
        ):
            chunks.append(chunk)
    except OllamaClientError:
        return None
    recovery_text = "".join(chunks)
    return _extract_tool_request(recovery_text)


def _validate_tool_request(tool_request: Dict[str, Any]) -> str | None:
    tool_name = tool_request["tool"]
    args = tool_request["args"]

    if tool_name == "run_command":
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return "run_command requiere `args.command` como string no vacío."
        safety_error = _validate_command_safety(command)
        if safety_error:
            return f"run_command bloqueado: {safety_error}"
        return None

    if tool_name == "read_file":
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            return "read_file requiere `args.path` como string no vacío."
        return None

    if tool_name == "write_file":
        path = args.get("path")
        content = args.get("content")
        append = args.get("append", False)
        if not isinstance(path, str) or not path.strip():
            return "write_file requiere `args.path` como string no vacío."
        if not isinstance(content, str):
            return "write_file requiere `args.content` como string."
        if not isinstance(append, bool):
            return "write_file requiere `args.append` como booleano (true/false)."
        return None

    if tool_name == "create_directory":
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            return "create_directory requiere `args.path` como string no vacío."
        return None

    if tool_name == "list_directory":
        path = args.get("path", ".")
        recursive = args.get("recursive", False)
        if not isinstance(path, str):
            return "list_directory requiere `args.path` como string."
        if not isinstance(recursive, bool):
            return "list_directory requiere `args.recursive` como booleano."
        return None

    return f"Herramienta no soportada: {tool_name}"


def _is_tool_request_write(tool_request: Dict[str, Any]) -> bool:
    tool_name = tool_request["tool"]
    args = tool_request["args"]
    if tool_name in {"write_file", "create_directory"}:
        return True
    if tool_name == "run_command":
        command = str(args.get("command", ""))
        return _is_write_or_edit_command(command)
    return False


def _format_tool_request_for_user(tool_request: Dict[str, Any]) -> str:
    tool_name = tool_request["tool"]
    args = tool_request["args"]
    return f"{tool_name}({json.dumps(args, ensure_ascii=False)})"


def _execute_tool_request(
    workspace_root: Path, command_cwd: Path, tool_request: Dict[str, Any]
) -> tuple[str, Path]:
    tool_name = tool_request["tool"]
    args = tool_request["args"]

    if tool_name == "run_command":
        command = str(args.get("command", "")).strip()
        if not command:
            raise ValueError("run_command requiere `args.command`.")
        return _execute_workspace_command_with_cd(
            workspace_root=workspace_root, command_cwd=command_cwd, command=command
        )

    if tool_name == "read_file":
        target = str(args.get("path", "")).strip()
        if not target:
            raise ValueError("read_file requiere `args.path`.")
        result = _read_text_file(workspace_root=workspace_root, target=target)
        return result, command_cwd

    if tool_name == "write_file":
        target = str(args.get("path", "")).strip()
        if not target:
            raise ValueError("write_file requiere `args.path`.")
        content = str(args.get("content", ""))
        append = bool(args.get("append", False))
        result = _write_text_file(
            workspace_root=workspace_root,
            target=target,
            content=content,
            append=append,
        )
        return result, command_cwd

    if tool_name == "create_directory":
        target = str(args.get("path", "")).strip()
        if not target:
            raise ValueError("create_directory requiere `args.path`.")
        dir_path = _safe_resolve_path(workspace_root, target)
        dir_path.mkdir(parents=True, exist_ok=True)
        rel = dir_path.relative_to(workspace_root)
        return f"Directorio listo: `{rel}` ({dir_path})", command_cwd

    if tool_name == "list_directory":
        target = str(args.get("path", ".")).strip() or "."
        recursive = bool(args.get("recursive", False))
        result = _scan_directory(workspace_root=workspace_root, target=target, recursive=recursive)
        return result, command_cwd

    raise ValueError(f"Herramienta no soportada: {tool_name}")


def _call_model_once(
    client: OllamaClient,
    model: str,
    temperature: float,
    messages: List[Dict[str, Any]],
) -> str:
    chunks: List[str] = []
    for chunk in client.chat_stream(
        model=model,
        messages=messages,
        options={"temperature": temperature},
    ):
        chunks.append(chunk)
    return "".join(chunks)


def _build_tool_observation(tool_request: Dict[str, Any], tool_result: str, step: int | None) -> str:
    step_label = f"paso {step}" if step else "paso aprobado por usuario"
    return (
        f"Observation ({step_label}):\n"
        f"- Solicitud: {_format_tool_request_for_user(tool_request)}\n\n"
        f"{tool_result}"
    )

def _format_trace_result_preview(text: str, max_chars: int = 180) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        return "[sin salida]"
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars] + "..."


def _run_agent_reasoning_loop(
    client: OllamaClient,
    model: str,
    temperature: float,
    workspace_root: Path,
    command_cwd: Path,
    user_prompt: str,
) -> Dict[str, Any]:
    current_cwd = command_cwd
    executed_steps = 0
    trace_lines: List[str] = []
    action_intent = _is_action_intent_prompt(user_prompt)
    action_recovery_used = False
    action_guidance_injected = False

    for step in range(1, MAX_AGENT_STEPS + 1):
        trace_lines.append(f"Paso {step}: consultando al modelo.")
        model_messages = [{"role": "system", "content": TOOL_PROTOCOL_SYSTEM_PROMPT}, *st.session_state.messages]
        assistant_content = _call_model_once(
            client=client,
            model=model,
            temperature=temperature,
            messages=model_messages,
        )
        if not assistant_content.strip():
            trace_lines.append(f"Paso {step}: respuesta vacía, aplicando reintento.")
            retry_messages = [
                {
                    "role": "system",
                    "content": (
                        "Responde con contenido útil. Si necesitas tools, usa JSON válido de tool; "
                        "si no, responde con la solución final en texto."
                    ),
                },
                *st.session_state.messages[-12:],
            ]
            assistant_content = _call_model_once(
                client=client,
                model=model,
                temperature=temperature,
                messages=retry_messages,
            )
        if not assistant_content.strip():
            return {
                "status": "completed",
                "assistant_content": (
                    "No recibí contenido del modelo durante el ciclo del agente. "
                    "Intenta nuevamente con una instrucción más específica."
                ),
                "new_cwd": current_cwd,
                "executed_steps": executed_steps,
                "trace_lines": trace_lines,
            }

        tool_request = _extract_tool_request(assistant_content)
        if not tool_request and _looks_like_tool_request_text(assistant_content):
            repaired_tool_request = _attempt_tool_request_repair_from_text(
                client=client,
                model=model,
                temperature=temperature,
                assistant_text=assistant_content,
            )
            if repaired_tool_request:
                tool_request = repaired_tool_request
                trace_lines.append(
                    f"Paso {step}: se reparó una solicitud de tool malformada: "
                    f"`{_format_tool_request_for_user(tool_request)}`."
                )

        if not tool_request and step == 1 and _is_write_intent_prompt(user_prompt):
            recovered_tool_request = _attempt_tool_request_recovery(
                client=client,
                model=model,
                temperature=temperature,
                messages=st.session_state.messages,
            )
            if recovered_tool_request:
                tool_request = recovered_tool_request
                trace_lines.append(
                    f"Paso {step}: se recuperó una solicitud de tool: "
                    f"`{_format_tool_request_for_user(tool_request)}`."
                )

        if not tool_request and action_intent and user_prompt.strip() and not action_recovery_used:
            action_recovery_used = True
            recovered_action_tool_request = _attempt_action_tool_request_recovery(
                client=client,
                model=model,
                temperature=temperature,
                messages=st.session_state.messages,
                user_prompt=user_prompt,
                assistant_text=assistant_content,
            )
            if recovered_action_tool_request:
                tool_request = recovered_action_tool_request
                trace_lines.append(
                    f"Paso {step}: recuperación forzada para instrucción accionable → "
                    f"`{_format_tool_request_for_user(tool_request)}`."
                )

        if not tool_request:
            if action_intent and step < MAX_AGENT_STEPS and not action_guidance_injected:
                action_guidance_injected = True
                trace_lines.append(
                    f"Paso {step}: no hubo tool pese a instrucción accionable; "
                    "se inyecta guía y se reintenta."
                )
                _add_system_context(
                    "Instrucción operativa del sistema: el usuario pidió una acción directa. "
                    "No pidas más detalle salvo bloqueo real; usa la siguiente tool necesaria."
                )
                continue
            trace_lines.append(f"Paso {step}: respuesta final sin tool, ciclo completado.")
            return {
                "status": "completed",
                "assistant_content": assistant_content,
                "new_cwd": current_cwd,
                "executed_steps": executed_steps,
                "trace_lines": trace_lines,
            }

        validation_error = _validate_tool_request(tool_request)
        if validation_error:
            trace_lines.append(f"Paso {step}: tool inválida ({validation_error}).")
            _add_system_context(
                "Observation (tool inválida):\n"
                f"- Error: {validation_error}\n"
                f"- Respuesta original: {assistant_content}"
            )
            executed_steps += 1
            continue

        try:
            tool_request, safety_adjustment = _normalize_write_file_tool_request(
                workspace_root=workspace_root,
                user_prompt=user_prompt,
                tool_request=tool_request,
            )
        except ValueError as exc:
            return {
                "status": "completed",
                "assistant_content": f"⚠️ {exc}",
                "new_cwd": current_cwd,
                "executed_steps": executed_steps,
                "trace_lines": trace_lines,
            }

        validation_error = _validate_tool_request(tool_request)
        if validation_error:
            trace_lines.append(
                f"Paso {step}: tool inválida tras ajustes de seguridad ({validation_error})."
            )
            _add_system_context(f"Observation (tool inválida tras ajustes de seguridad): {validation_error}")
            executed_steps += 1
            continue

        if safety_adjustment:
            trace_lines.append(f"Paso {step}: ajuste de seguridad aplicado ({safety_adjustment}).")
            _add_system_context(f"Ajuste de seguridad aplicado al write_file: {safety_adjustment}")

        if _is_tool_request_write(tool_request) and not st.session_state.allow_write_commands_always:
            st.session_state.pending_tool_request = json.dumps(tool_request, ensure_ascii=False)
            st.session_state.pending_tool_request_cwd = str(current_cwd)
            st.session_state.pending_agent_loop = True
            trace_lines.append(
                f"Paso {step}: pendiente aprobación para `{_format_tool_request_for_user(tool_request)}`."
            )
            return {
                "status": "awaiting_approval",
                "assistant_content": (
                    "La IA necesita aprobación para continuar el plan con esta acción:\n"
                    f"`{_format_tool_request_for_user(tool_request)}`\n\n"
                    "Usa los botones **Aceptar**, **Rechazar** o **Aceptar siempre**."
                ),
                "new_cwd": current_cwd,
                "executed_steps": executed_steps,
                "trace_lines": trace_lines,
            }

        try:
            tool_result, current_cwd = _execute_tool_request(
                workspace_root=workspace_root,
                command_cwd=current_cwd,
                tool_request=tool_request,
            )
            trace_lines.append(
                f"Paso {step}: ejecutada `{_format_tool_request_for_user(tool_request)}` → "
                f"{_format_trace_result_preview(tool_result)}"
            )
        except ValueError as exc:
            tool_result = f"Error ejecutando tool solicitada por la IA: {exc}"
            trace_lines.append(
                f"Paso {step}: error en `{_format_tool_request_for_user(tool_request)}` ({exc})."
            )

        _add_system_context(_build_tool_observation(tool_request=tool_request, tool_result=tool_result, step=step))
        executed_steps += 1
    trace_lines.append(f"Límite alcanzado: {MAX_AGENT_STEPS} pasos.")

    return {
        "status": "max_steps",
        "assistant_content": (
            f"Se alcanzó el límite de {MAX_AGENT_STEPS} pasos del agente. "
            "Puedes pedirle que continúe con una instrucción más específica."
        ),
        "new_cwd": current_cwd,
        "executed_steps": executed_steps,
        "trace_lines": trace_lines,
    }


def build_user_message(
    prompt: str,
    uploaded_files: List[Any],
    supports_vision: bool,
    max_file_size_bytes: int,
) -> tuple[Dict[str, Any], List[str]]:
    message: Dict[str, Any] = {"role": "user", "content": prompt}
    attachment_labels: List[str] = []
    ignored_files: List[str] = []
    text_context_blocks: List[str] = []
    image_blobs: List[str] = []

    for uploaded_file in uploaded_files:
        filename = uploaded_file.name
        mime = uploaded_file.type or ""
        lower_name = filename.lower()
        raw = uploaded_file.getvalue()
        size_bytes = len(raw)

        if size_bytes > max_file_size_bytes:
            ignored_files.append(
                f"{filename} (excede tamaño máximo de {MAX_FILE_SIZE_MB} MB)"
            )
            continue

        if mime.startswith("image/"):
            if not supports_vision:
                ignored_files.append(f"{filename} (imagen no soportada por el modelo seleccionado)")
                continue
            image_blobs.append(base64.b64encode(raw).decode("utf-8"))
            attachment_labels.append(f"🖼️ {filename}")
            continue

        if mime.startswith("text/") or lower_name.endswith(TEXT_FILE_EXTENSIONS):
            extracted_text = _extract_text(uploaded_file)
            if not extracted_text:
                ignored_files.append(f"{filename} (no se pudo leer como texto)")
                continue
            text_context_blocks.append(f"[Archivo: {filename}]\n{extracted_text}")
            attachment_labels.append(f"📄 {filename}")
            continue

        ignored_files.append(f"{filename} (tipo no soportado)")

    if text_context_blocks:
        message["content"] = (
            f"{prompt}\n\n---\nContexto de archivos adjuntos:\n\n" + "\n\n".join(text_context_blocks)
        )
    if image_blobs:
        message["images"] = image_blobs
    if attachment_labels:
        message["attachments"] = attachment_labels

    return message, ignored_files


def main() -> None:
    st.set_page_config(page_title="Ollama Chat GUI", page_icon="💬", layout="wide")
    init_state()

    st.title("Ollama Chat GUI")
    st.caption("Cliente gráfico local para chatear con modelos de Ollama.")

    with st.sidebar:
        st.header("Configuración")
        base_url = st.text_input("Ollama URL", value=DEFAULT_BASE_URL)
        temperature = st.slider("Temperature", min_value=0.0, max_value=1.5, value=0.7, step=0.1)
        workspace_root_text = st.text_input(
            "Workspace root",
            value=st.session_state.workspace_root,
            help="Solo se permitirá leer/escribir dentro de esta carpeta.",
        )

        client = OllamaClient(base_url=base_url)
        st.session_state.workspace_root = workspace_root_text

        if st.button("Recargar modelos"):
            try:
                st.session_state.models = client.list_models()
                st.success("Modelos actualizados.")
            except OllamaClientError as exc:
                st.error(str(exc))

        if not st.session_state.models:
            try:
                st.session_state.models = client.list_models()
            except OllamaClientError:
                st.session_state.models = []

        if st.session_state.models:
            default_index = 0
            if DEFAULT_MODEL and DEFAULT_MODEL in st.session_state.models:
                default_index = st.session_state.models.index(DEFAULT_MODEL)
            model = st.selectbox("Modelo", st.session_state.models, index=default_index)
        else:
            st.warning("No se detectaron modelos. Ejecuta `ollama list` para verificar.")
            model = st.text_input("Modelo manual", value=DEFAULT_MODEL or "gemma3:latest")

        capabilities = st.session_state.model_capabilities.get(model, set())
        if model and not capabilities:
            try:
                capabilities = client.get_model_capabilities(model)
                st.session_state.model_capabilities[model] = capabilities
            except OllamaClientError:
                capabilities = set()

        if capabilities:
            st.caption(f"Capacidades: {', '.join(sorted(capabilities))}")

        supports_vision = "vision" in capabilities

        if st.button("Limpiar chat"):
            st.session_state.messages = []
            st.session_state.pending_tool_request = ""
            st.session_state.pending_tool_request_cwd = ""
            st.session_state.pending_agent_loop = False
            st.session_state.pending_command = ""
            st.session_state.pending_command_cwd = ""
            st.session_state.last_agent_trace = []
            st.rerun()

        st.divider()
        st.subheader("Exportar chat")
        export_format = st.selectbox(
            "Formato de archivo",
            options=["markdown", "json"],
            format_func=lambda value: "Markdown (.md)" if value == "markdown" else "JSON (.json)",
            key="chat_export_format",
        )
        include_system_on_export = st.checkbox(
            "Incluir mensajes de sistema",
            value=True,
            key="chat_export_include_system",
        )
        if st.button("Exportar chat a archivo"):
            try:
                export_workspace_root = _resolve_workspace_root(st.session_state.workspace_root)
                export_path = _export_chat_to_workspace(
                    workspace_root=export_workspace_root,
                    messages=st.session_state.messages,
                    export_format=export_format,
                    include_system=include_system_on_export,
                )
                st.session_state.last_chat_export_path = str(export_path)
                try:
                    relative_export_path = export_path.relative_to(export_workspace_root)
                except ValueError:
                    relative_export_path = export_path
                st.success(f"Chat exportado en `{relative_export_path}`")
            except ValueError as exc:
                st.error(str(exc))
        if st.session_state.last_chat_export_path:
            st.caption(f"Último export: `{st.session_state.last_chat_export_path}`")

    for msg in st.session_state.messages:
        if msg["role"] not in {"user", "assistant"}:
            continue
        content = str(msg.get("content", ""))
        if msg["role"] == "assistant" and not content.strip():
            continue
        with st.chat_message(msg["role"]):
            st.markdown(content)
            attachments = msg.get("attachments", [])
            if attachments:
                st.caption(f"Adjuntos: {', '.join(attachments)}")

    workspace_root = _resolve_workspace_root(st.session_state.workspace_root)
    command_cwd = _ensure_command_cwd(workspace_root)
    st.caption(f"Workspace activo: `{workspace_root}`")
    st.caption(f"Directorio actual para comandos: `{command_cwd}`")
    st.subheader("Adjuntar archivos")
    uploaded_files = st.file_uploader(
        "Adjuntar archivos al próximo mensaje",
        type=[
            "png",
            "jpg",
            "jpeg",
            "webp",
            "gif",
            "txt",
            "md",
            "json",
            "csv",
            "xml",
            "yaml",
            "yml",
            "py",
            "log",
        ],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
        help="Imágenes se envían al modelo si soporta vision. Archivos de texto se inyectan como contexto.",
    )
    st.caption(f"Tamaño máximo por archivo: {MAX_FILE_SIZE_MB} MB")
    st.caption(f"También puedes ejecutar comandos desde el chat con `{CHAT_COMMAND_PREFIX} <comando>`.") 

    if uploaded_files:
        image_files = [f for f in uploaded_files if (f.type or "").startswith("image/")]
        if image_files:
            st.caption("Previsualización de imágenes:")
            for image_file in image_files:
                st.image(image_file, caption=image_file.name, width=220)
    st.caption(
        "Ruta activa en chat: "
        f"`{command_cwd}` (relativa al workspace: `{_relative_path_label(workspace_root, command_cwd)}`)"
    )
    if st.session_state.last_rag_sources:
        st.caption("Fuentes RAG usadas (última respuesta): " + ", ".join(st.session_state.last_rag_sources))
    if st.session_state.last_agent_trace:
        with st.expander("Traza del agente (última ejecución)", expanded=False):
            st.markdown("\n".join(f"- {line}" for line in st.session_state.last_agent_trace))
    if st.session_state.pending_command:
        st.warning(
            "Hay un comando pendiente que puede escribir/editar archivos:\n"
            f"`{st.session_state.pending_command}`"
        )
        approve_col, reject_col, always_col = st.columns(3)
        if approve_col.button("Aceptar", key="approve_pending_command"):
            pending_cwd = Path(
                st.session_state.pending_command_cwd or st.session_state.command_cwd
            ).expanduser().resolve()
            try:
                command_result, new_cwd = _execute_workspace_command_with_cd(
                    workspace_root=workspace_root,
                    command_cwd=pending_cwd,
                    command=st.session_state.pending_command,
                )
                st.session_state.command_cwd = str(new_cwd)
                _add_system_context(
                    f"Resultado de comando aprobado por usuario (cwd: `{new_cwd}`):\n\n"
                    f"{command_result}"
                )
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"```text\n{command_result}\n```"}
                )
            except ValueError as exc:
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"Error ejecutando comando: {exc}"}
                )
            st.session_state.pending_command = ""
            st.session_state.pending_command_cwd = ""
            st.rerun()
        if reject_col.button("Rechazar", key="reject_pending_command"):
            st.session_state.messages.append(
                {"role": "assistant", "content": "Comando rechazado por el usuario."}
            )
            st.session_state.pending_command = ""
            st.session_state.pending_command_cwd = ""
            st.rerun()
        if always_col.button("Aceptar siempre", key="approve_always_pending_command"):
            st.session_state.allow_write_commands_always = True
            pending_cwd = Path(
                st.session_state.pending_command_cwd or st.session_state.command_cwd
            ).expanduser().resolve()
            try:
                command_result, new_cwd = _execute_workspace_command_with_cd(
                    workspace_root=workspace_root,
                    command_cwd=pending_cwd,
                    command=st.session_state.pending_command,
                )
                st.session_state.command_cwd = str(new_cwd)
                _add_system_context(
                    f"Resultado de comando aprobado en modo 'siempre' (cwd: `{new_cwd}`):\n\n"
                    f"{command_result}"
                )
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"```text\n{command_result}\n```"}
                )
            except ValueError as exc:
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"Error ejecutando comando: {exc}"}
                )
            st.session_state.pending_command = ""
            st.session_state.pending_command_cwd = ""
            st.rerun()
    if st.session_state.pending_tool_request:
        st.warning("Hay una acción pendiente solicitada por la IA que puede escribir/editar archivos.")
        pending_tool_obj = json.loads(st.session_state.pending_tool_request)
        st.code(_format_tool_request_for_user(pending_tool_obj), language="text")
        approve_tool_col, reject_tool_col, always_tool_col = st.columns(3)

        if approve_tool_col.button("Aceptar", key="approve_pending_tool"):
            pending_cwd = Path(
                st.session_state.pending_tool_request_cwd or st.session_state.command_cwd
            ).expanduser().resolve()
            should_resume_agent = bool(st.session_state.pending_agent_loop)
            try:
                tool_result, new_cwd = _execute_tool_request(
                    workspace_root=workspace_root,
                    command_cwd=pending_cwd,
                    tool_request=pending_tool_obj,
                )
                st.session_state.command_cwd = str(new_cwd)
                _add_system_context(
                    _build_tool_observation(
                        tool_request=pending_tool_obj,
                        tool_result=tool_result,
                        step=None,
                    )
                )
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"```text\n{tool_result}\n```"}
                )
                st.session_state.pending_tool_request = ""
                st.session_state.pending_tool_request_cwd = ""
                st.session_state.pending_agent_loop = False
                if should_resume_agent:
                    loop_result = _run_agent_reasoning_loop(
                        client=client,
                        model=model,
                        temperature=temperature,
                        workspace_root=workspace_root,
                        command_cwd=new_cwd,
                        user_prompt="",
                    )
                    st.session_state.command_cwd = str(loop_result["new_cwd"])
                    st.session_state.last_agent_trace = list(loop_result.get("trace_lines", []))
                    st.session_state.messages.append(
                        {"role": "assistant", "content": loop_result["assistant_content"]}
                    )
            except ValueError as exc:
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"Error ejecutando tool: {exc}"}
                )
                st.session_state.pending_tool_request = ""
                st.session_state.pending_tool_request_cwd = ""
                st.session_state.pending_agent_loop = False
            except OllamaClientError as exc:
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"Error reanudando el agente: {exc}"}
                )
                st.session_state.pending_tool_request = ""
                st.session_state.pending_tool_request_cwd = ""
                st.session_state.pending_agent_loop = False
            st.rerun()

        if reject_tool_col.button("Rechazar", key="reject_pending_tool"):
            st.session_state.messages.append(
                {"role": "assistant", "content": "Acción de tool rechazada por el usuario."}
            )
            st.session_state.pending_tool_request = ""
            st.session_state.pending_tool_request_cwd = ""
            st.session_state.pending_agent_loop = False
            st.rerun()

        if always_tool_col.button("Aceptar siempre", key="approve_always_pending_tool"):
            st.session_state.allow_write_commands_always = True
            pending_cwd = Path(
                st.session_state.pending_tool_request_cwd or st.session_state.command_cwd
            ).expanduser().resolve()
            should_resume_agent = bool(st.session_state.pending_agent_loop)
            try:
                tool_result, new_cwd = _execute_tool_request(
                    workspace_root=workspace_root,
                    command_cwd=pending_cwd,
                    tool_request=pending_tool_obj,
                )
                st.session_state.command_cwd = str(new_cwd)
                _add_system_context(
                    _build_tool_observation(
                        tool_request=pending_tool_obj,
                        tool_result=tool_result,
                        step=None,
                    )
                )
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"```text\n{tool_result}\n```"}
                )
                st.session_state.pending_tool_request = ""
                st.session_state.pending_tool_request_cwd = ""
                st.session_state.pending_agent_loop = False
                if should_resume_agent:
                    loop_result = _run_agent_reasoning_loop(
                        client=client,
                        model=model,
                        temperature=temperature,
                        workspace_root=workspace_root,
                        command_cwd=new_cwd,
                        user_prompt="",
                    )
                    st.session_state.command_cwd = str(loop_result["new_cwd"])
                    st.session_state.last_agent_trace = list(loop_result.get("trace_lines", []))
                    st.session_state.messages.append(
                        {"role": "assistant", "content": loop_result["assistant_content"]}
                    )
            except ValueError as exc:
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"Error ejecutando tool: {exc}"}
                )
                st.session_state.pending_tool_request = ""
                st.session_state.pending_tool_request_cwd = ""
                st.session_state.pending_agent_loop = False
            except OllamaClientError as exc:
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"Error reanudando el agente: {exc}"}
                )
                st.session_state.pending_tool_request = ""
                st.session_state.pending_tool_request_cwd = ""
                st.session_state.pending_agent_loop = False
            st.rerun()

    user_prompt = st.chat_input(f"Escribe tu mensaje... (o {CHAT_COMMAND_PREFIX} <comando>)")
    if not user_prompt:
        return

    try:
        chat_command = _parse_chat_command(user_prompt)
    except ValueError as exc:
        st.error(str(exc))
        return

    if chat_command:
        st.session_state.last_rag_sources = []
        st.session_state.last_agent_trace = []
        command_user_content = f"🛠️ Ejecutar comando en workspace: `{chat_command}`"
        st.session_state.messages.append({"role": "user", "content": command_user_content})
        with st.chat_message("user"):
            st.markdown(command_user_content)

        if _is_write_or_edit_command(chat_command) and not st.session_state.allow_write_commands_always:
            st.session_state.pending_command = chat_command
            st.session_state.pending_command_cwd = str(command_cwd)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "Este comando puede escribir/editar archivos y requiere aprobación. "
                        "Usa los botones: Aceptar, Rechazar o Aceptar siempre."
                    ),
                }
            )
            st.rerun()
            return

        with st.chat_message("assistant"):
            placeholder = st.empty()
            try:
                command_result, new_cwd = _execute_workspace_command_with_cd(
                    workspace_root=workspace_root,
                    command_cwd=command_cwd,
                    command=chat_command,
                )
                st.session_state.command_cwd = str(new_cwd)
                _add_system_context(
                    f"Resultado de comando en workspace `{workspace_root}` (cwd: `{new_cwd}`):\n\n"
                    f"{command_result}"
                )
                assistant_content = f"```text\n{command_result}\n```"
                placeholder.markdown(assistant_content)
            except ValueError as exc:
                assistant_content = f"Error ejecutando comando: {exc}"
                placeholder.error(assistant_content)

        st.session_state.messages.append({"role": "assistant", "content": assistant_content})
        st.rerun()
        return
    _add_system_context(_build_workspace_context(workspace_root=workspace_root, command_cwd=command_cwd))
    _maybe_add_project_rag_context(workspace_root=workspace_root, user_prompt=user_prompt)
    _maybe_add_requested_file_context(workspace_root=workspace_root, user_prompt=user_prompt)

    user_message, ignored_files = build_user_message(
        prompt=user_prompt,
        uploaded_files=uploaded_files or [],
        supports_vision=supports_vision,
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
    )

    st.session_state.messages.append(user_message)
    with st.chat_message("user"):
        st.markdown(user_prompt)
        attachments = user_message.get("attachments", [])
        if attachments:
            st.caption(f"Adjuntos: {', '.join(attachments)}")
        if ignored_files:
            st.warning("No se enviaron algunos archivos:\n- " + "\n- ".join(ignored_files))
    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("🧠 Ejecutando ciclo del agente...")
        try:
            loop_result = _run_agent_reasoning_loop(
                client=client,
                model=model,
                temperature=temperature,
                workspace_root=workspace_root,
                command_cwd=command_cwd,
                user_prompt=user_prompt,
            )
        except OllamaClientError as exc:
            placeholder.error(str(exc))
            return

        st.session_state.command_cwd = str(loop_result["new_cwd"])
        st.session_state.last_agent_trace = list(loop_result.get("trace_lines", []))
        assistant_content = str(loop_result["assistant_content"])
        if loop_result["status"] == "awaiting_approval":
            placeholder.warning(assistant_content)
        else:
            placeholder.markdown(assistant_content)

    st.session_state.messages.append({"role": "assistant", "content": assistant_content})
    if loop_result["status"] == "awaiting_approval":
        st.rerun()
        return
    st.session_state.uploader_key += 1
    st.rerun()


if __name__ == "__main__":
    main()
