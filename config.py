"""Configuración centralizada para Ollama Chat GUI."""

from __future__ import annotations

import os
from pathlib import Path

# =============================================================================
# Ollama Configuration
# =============================================================================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "")
OLLAMA_TIMEOUT = 60

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
COMMAND_TIMEOUT_SECONDS = 30

# =============================================================================
# Agent Configuration
# =============================================================================
MAX_AGENT_STEPS = 12
MAX_PLAN_STEPS = 20
MAX_TOOL_REPAIR_CHARS = 16000

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
}

# =============================================================================
# Blocked Command Patterns (Security)
# =============================================================================
import re

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
