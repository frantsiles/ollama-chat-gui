"""Configuración centralizada para Ollama Chat GUI."""

from __future__ import annotations

import os
import re
from pathlib import Path as _Path

# =============================================================================
# Ollama Configuration
# =============================================================================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))

# =============================================================================
# Workspace Configuration
# =============================================================================
DEFAULT_WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.getcwd())

# =============================================================================
# File Handling
# =============================================================================
TEXT_FILE_EXTENSIONS = (
    ".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml",
    ".py", ".log", ".toml", ".ini", ".cfg", ".conf",
    ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".sh", ".bash", ".zsh", ".fish",
    ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
)
MAX_TEXT_CHARS_PER_FILE = 12000
MAX_FILE_SIZE_MB = 8
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# =============================================================================
# Tool Limits
# =============================================================================
MAX_SCAN_RESULTS = 300
MAX_READ_CHARS = 30000
MAX_COMMAND_OUTPUT_CHARS = 30000
COMMAND_TIMEOUT_SECONDS: int = int(os.getenv("COMMAND_TIMEOUT_SECONDS", "120"))
PYTHON_SANDBOX_TIMEOUT_SECONDS: int = int(os.getenv("PYTHON_SANDBOX_TIMEOUT_SECONDS", "30"))

# =============================================================================
# Agent Configuration
# =============================================================================
MAX_AGENT_STEPS: int = int(os.getenv("MAX_AGENT_STEPS", "100"))
MAX_PLAN_STEPS = 20
MAX_TOOL_REPAIR_CHARS = 16000
# Tiempo máximo (segundos) para que el agente complete una tarea antes de cancelarse
AGENT_TASK_TIMEOUT: int = int(os.getenv("AGENT_TASK_TIMEOUT", "300"))

# =============================================================================
# Context Management
# =============================================================================
# Start summarizing when conversation has more messages than this
MAX_CONTEXT_MESSAGES = 20
# Always keep the last N messages verbatim in the context window
MAX_CONTEXT_MESSAGES_KEEP = 8

# =============================================================================
# Input Validation
# =============================================================================
# Maximum length of a single user message (chars)
MAX_INPUT_CHARS = 8000
# Maximum total attachment content per request
MAX_ATTACHMENT_CHARS_TOTAL = 8000
# Maximum content per individual attachment file
MAX_ATTACHMENT_CHARS_PER_FILE = 4000

# =============================================================================
# Persistence
# =============================================================================
PERSISTENCE_DB_PATH = _Path(
    os.getenv(
        "CHAT_DB_PATH",
        os.path.join(os.path.expanduser("~"), ".local", "share", "ollama-chat-gui", "sessions.db"),
    )
)

# =============================================================================
# RAG Configuration
# =============================================================================
MAX_AUTOCONTEXT_ENTRIES = 60
MAX_RAG_CONTEXT_CHARS = 10000
MAX_RAG_FILES = 120
MAX_RAG_FILE_CHARS = 16000
MAX_RAG_CHUNK_CHARS = 1200
MAX_RAG_TOP_CHUNKS = 6
RAG_IGNORED_DIRS = {
    ".git", ".venv", "__pycache__", "node_modules",
    ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "dist", "build", ".tox", ".eggs",
}

# =============================================================================
# Semantic RAG / Embeddings
# =============================================================================
EMBEDDING_ENABLED: bool = os.getenv("EMBEDDING_ENABLED", "true").lower() != "false"
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
CHROMA_DB_PATH = _Path(
    os.getenv(
        "CHROMA_DB_PATH",
        os.path.join(os.path.expanduser("~"), ".local", "share", "ollama-chat-gui", "chroma"),
    )
)
# Puntuación mínima cosine (0-1) para emitir sugerencias proactivas
RAG_PROACTIVE_SCORE_THRESHOLD: float = float(os.getenv("RAG_PROACTIVE_SCORE_THRESHOLD", "0.75"))
# Turnos de cooldown entre dos rondas de sugerencias proactivas para el mismo set de archivos
RAG_PROACTIVE_COOLDOWN_TURNS: int = int(os.getenv("RAG_PROACTIVE_COOLDOWN_TURNS", "2"))
# Número de chunks semánticos a recuperar por query
RAG_SEMANTIC_TOP_K: int = int(os.getenv("RAG_SEMANTIC_TOP_K", "6"))
# Límites para documentos externos en la KB
KB_MAX_DOCUMENT_CHARS: int = 50_000
KB_CHUNK_CHARS: int = 1_000
# Máximo de URLs permitidas en la KB externa
KB_MAX_DOCUMENTS: int = 500

# =============================================================================
# Long-term Memory
# =============================================================================
MEMORY_ENABLED: bool = os.getenv("MEMORY_ENABLED", "true").lower() != "false"
MEMORY_AUTO_EXTRACT: bool = os.getenv("MEMORY_AUTO_EXTRACT", "true").lower() != "false"
MEMORY_MAX_WORKSPACE_ITEMS: int = int(os.getenv("MEMORY_MAX_WORKSPACE_ITEMS", "50"))
MEMORY_MAX_PROFILE_ITEMS: int = int(os.getenv("MEMORY_MAX_PROFILE_ITEMS", "30"))

# =============================================================================
# Reflection & Self-Correction
# =============================================================================
# Reflexión crítica desactivada por defecto. Añade una llamada extra al modelo
# por cada respuesta y, en la práctica, suele introducir más latencia que valor.
# Para activarla: REFLECTION_ENABLED=true
REFLECTION_ENABLED: bool = os.getenv("REFLECTION_ENABLED", "false").lower() == "true"
REFLECTION_TEMPERATURE: float = float(os.getenv("REFLECTION_TEMPERATURE", "0.3"))
MAX_STEP_RETRIES: int = int(os.getenv("MAX_STEP_RETRIES", "3"))

# =============================================================================
# Chat Export
# =============================================================================
CHAT_EXPORT_DIRNAME = ".chat_exports"

# =============================================================================
# Operation Modes
# =============================================================================
class OperationMode:
    """Modos de operación del agente."""
    CHAT = "chat"       # Solo conversación, sin tools
    AGENT = "agent"     # Ciclo ReAct automático con tools
    PLAN = "plan"       # Planifica primero, ejecuta después

# =============================================================================
# Approval Levels
# =============================================================================
class ApprovalLevel:
    """Niveles de aprobación para acciones."""
    NONE = "none"           # No requiere aprobación
    WRITE_ONLY = "write"    # Solo acciones de escritura
    ALL = "all"             # Todas las acciones

# =============================================================================
# Tool Names
# =============================================================================
SUPPORTED_TOOLS = {
    "run_command",
    "read_file",
    "write_file",
    "create_directory",
    "list_directory",
    "search_files",
    "execute_python",
}

# =============================================================================
# Blocked Command Patterns (Security)
# =============================================================================
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

WRITE_COMMAND_PREFIXES = {
    "rm", "mv", "cp", "touch", "mkdir", "rmdir",
    "chmod", "chown", "ln", "tee", "truncate", "dd", "sed", "awk", "perl",
}

WRITE_COMMAND_OPERATORS = (">", ">>", "| tee", "sed -i")

WRITE_GIT_SUBCOMMANDS = {
    "add", "apply", "am", "branch", "checkout", "cherry-pick",
    "clean", "commit", "merge", "push", "rebase", "reset",
    "revert", "rm", "stash", "switch", "tag",
}

# =============================================================================
# Native Function Calling
# =============================================================================
# Use Ollama's native tool-calling API when the model supports it
FUNCTION_CALLING_ENABLED: bool = os.getenv("FUNCTION_CALLING_ENABLED", "true").lower() != "false"

# =============================================================================
# MCP (Model Context Protocol)
# =============================================================================
MCP_ENABLED: bool = os.getenv("MCP_ENABLED", "false").lower() == "true"
# Path to JSON file that lists MCP server configurations
MCP_SERVERS_FILE: str = os.getenv(
    "MCP_SERVERS_FILE",
    str(_Path(os.getcwd()) / "mcp_servers.json"),
)
