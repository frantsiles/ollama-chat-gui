"""Capa de persistencia SQLite para sesiones de chat.

Diseño:
- Una tabla `sessions` con metadatos de sesión (modo, modelo, resumen, etc.)
- Una tabla `messages` con el historial de conversación
- WAL mode para mejor concurrencia con uvicorn
- Upsert de sesión + replace completo de mensajes en cada save
- Las lecturas y escrituras fallan silenciosamente para no romper el flujo
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("persistence")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    mode            TEXT NOT NULL DEFAULT 'agent',
    model           TEXT NOT NULL DEFAULT '',
    temperature     REAL NOT NULL DEFAULT 0.7,
    workspace_root  TEXT NOT NULL DEFAULT '',
    current_cwd     TEXT NOT NULL DEFAULT '',
    approval_level  TEXT NOT NULL DEFAULT 'write',
    context_summary TEXT NOT NULL DEFAULT '',
    pending_approval TEXT,
    current_plan     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    attachments TEXT NOT NULL DEFAULT '[]',
    metadata    TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages (session_id, id);
"""


class PersistenceDB:
    """
    Gestor de persistencia SQLite para sesiones y mensajes.

    Uso típico:
        db = PersistenceDB(Path("~/.local/share/ollama-chat-gui/sessions.db"))
        db.save_session(id, meta_dict, message_dicts)
        result = db.load_session(id)  # -> (meta_dict, message_dicts) | None
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info("💾 Persistence DB: %s", db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            logger.error("Error initializing DB schema: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_session(
        self,
        session_id: str,
        meta: Dict[str, Any],
        message_dicts: List[Dict[str, Any]],
    ) -> None:
        """
        Persiste una sesión completa.

        Usa INSERT OR REPLACE para la sesión y DELETE+INSERT para los
        mensajes (garantiza orden y elimina mensajes borrados).
        """
        now = datetime.now().isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions
                        (id, mode, model, temperature, workspace_root, current_cwd,
                         approval_level, context_summary, pending_approval,
                         current_plan, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        mode             = excluded.mode,
                        model            = excluded.model,
                        temperature      = excluded.temperature,
                        workspace_root   = excluded.workspace_root,
                        current_cwd      = excluded.current_cwd,
                        approval_level   = excluded.approval_level,
                        context_summary  = excluded.context_summary,
                        pending_approval = excluded.pending_approval,
                        current_plan     = excluded.current_plan,
                        updated_at       = excluded.updated_at
                    """,
                    (
                        session_id,
                        meta.get("mode", "agent"),
                        meta.get("model", ""),
                        meta.get("temperature", 0.7),
                        meta.get("workspace_root", ""),
                        meta.get("current_cwd", ""),
                        meta.get("approval_level", "write"),
                        meta.get("context_summary", ""),
                        (
                            json.dumps(meta["pending_approval"])
                            if meta.get("pending_approval")
                            else None
                        ),
                        (
                            json.dumps(meta["current_plan"])
                            if meta.get("current_plan")
                            else None
                        ),
                        meta.get("created_at", now),
                        now,
                    ),
                )

                # Reemplazar todos los mensajes
                conn.execute(
                    "DELETE FROM messages WHERE session_id = ?", (session_id,)
                )
                conn.executemany(
                    """
                    INSERT INTO messages
                        (session_id, role, content, timestamp, attachments, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            session_id,
                            msg["role"],
                            msg["content"],
                            msg["timestamp"],
                            json.dumps(msg.get("attachments", [])),
                            json.dumps(msg.get("metadata", {})),
                        )
                        for msg in message_dicts
                    ],
                )
        except sqlite3.Error as exc:
            logger.error("Error saving session %s: %s", session_id, exc)

    def load_session(
        self, session_id: str
    ) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        Carga una sesión desde SQLite.

        Retorna (meta_dict, message_dicts) o None si no existe.
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if not row:
                    return None

                msg_rows = conn.execute(
                    "SELECT role, content, timestamp, attachments, metadata "
                    "FROM messages WHERE session_id = ? ORDER BY id",
                    (session_id,),
                ).fetchall()

            meta = dict(row)
            # Deserializar campos JSON
            for field in ("pending_approval", "current_plan"):
                val = meta.get(field)
                meta[field] = json.loads(val) if val else None

            messages = [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "timestamp": r["timestamp"],
                    "attachments": json.loads(r["attachments"] or "[]"),
                    "metadata": json.loads(r["metadata"] or "{}"),
                }
                for r in msg_rows
            ]

            return meta, messages

        except sqlite3.Error as exc:
            logger.error("Error loading session %s: %s", session_id, exc)
            return None

    def delete_session(self, session_id: str) -> bool:
        """Elimina sesión y mensajes (CASCADE). Retorna True si existía."""
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM sessions WHERE id = ?", (session_id,)
                )
                return cur.rowcount > 0
        except sqlite3.Error as exc:
            logger.error("Error deleting session %s: %s", session_id, exc)
            return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Retorna metadatos de todas las sesiones (más recientes primero)."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT s.id, s.mode, s.model, s.updated_at,
                           COUNT(m.id) AS message_count
                    FROM   sessions s
                    LEFT JOIN messages m ON m.session_id = s.id
                    GROUP BY s.id
                    ORDER BY s.updated_at DESC
                    """
                ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("Error listing sessions: %s", exc)
            return []

    def cleanup_old_sessions(self, max_age_hours: int = 48) -> int:
        """Elimina sesiones sin actividad en las últimas `max_age_hours` horas."""
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM sessions WHERE updated_at < ?", (cutoff,)
                )
                deleted = cur.rowcount
            if deleted:
                logger.info("Cleaned up %d old sessions", deleted)
            return deleted
        except sqlite3.Error as exc:
            logger.error("Error cleaning old sessions: %s", exc)
            return 0
