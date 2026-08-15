"""Construcción de exports de conversación en Markdown.

Funciones puras, sin dependencias de FastAPI, usadas por web/api.py.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List

_ROLE_LABELS = {"user": "Usuario", "assistant": "Asistente"}
_MODE_LABELS = {"chat": "Chat", "agent": "Agent", "plan": "Plan"}

_SLUG_INVALID_RE = re.compile(r"[^A-Za-z0-9_\-]+")


def build_markdown_export(
    *,
    title: str,
    model: str,
    mode: str,
    created_at: str,
    messages: List[Dict[str, Any]],
) -> str:
    """Construye el contenido Markdown completo de una conversación."""
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mode_label = _MODE_LABELS.get(mode, mode or "-")

    lines: List[str] = [
        f"# {title.strip() if title and title.strip() else 'Chat sin título'}",
        "",
        f"- Modelo: {model or '-'}",
        f"- Modo: {mode_label}",
        f"- Creado: {created_at or '-'}",
        f"- Exportado: {exported_at}",
        f"- Mensajes: {len(messages)}",
        "",
        "---",
        "",
    ]

    for i, msg in enumerate(messages, start=1):
        role = str(msg.get("role", ""))
        label = _ROLE_LABELS.get(role, role.capitalize() or "Mensaje")
        lines.append(f"## {i}. {label}")
        lines.append("")

        attachments = msg.get("attachments") or []
        if attachments:
            lines.append(f"Adjuntos: {', '.join(str(a) for a in attachments)}")
            lines.append("")

        content = str(msg.get("content", "")).strip()
        lines.append(content if content else "*[sin contenido]*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _slugify(text: str) -> str:
    """Convierte texto a un slug ASCII seguro para usar en Content-Disposition."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.strip().replace(" ", "_")
    slug = _SLUG_INVALID_RE.sub("", ascii_text)
    return slug.strip("_-")


def safe_export_filename(title: str, session_id: str) -> str:
    """Nombre de archivo ASCII para el header Content-Disposition."""
    slug = _slugify(title or "")
    if not slug:
        slug = f"chat-{session_id[:8]}"
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{slug}_{date}.md"
