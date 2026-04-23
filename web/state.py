"""Gestión de estado de sesiones sin Streamlit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from config import (
    ApprovalLevel,
    DEFAULT_WORKSPACE_ROOT,
    OLLAMA_DEFAULT_MODEL,
    OperationMode,
)
from core.models import Conversation, Message, MessageRole


@dataclass
class Session:
    """Sesión de usuario."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    conversation: Conversation = field(default_factory=Conversation)
    mode: str = OperationMode.AGENT
    model: str = OLLAMA_DEFAULT_MODEL
    temperature: float = 0.7
    workspace_root: str = DEFAULT_WORKSPACE_ROOT
    current_cwd: str = DEFAULT_WORKSPACE_ROOT
    approval_level: str = ApprovalLevel.WRITE_ONLY
    pending_approval: Optional[Dict[str, Any]] = None
    current_plan: Optional[Dict[str, Any]] = None
    agent_trace: List[str] = field(default_factory=list)
    # Running lightweight summary of conversation history (for context windowing)
    context_summary: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serializa la sesión."""
        return {
            "id": self.id,
            "mode": self.mode,
            "model": self.model,
            "temperature": self.temperature,
            "workspace_root": self.workspace_root,
            "current_cwd": self.current_cwd,
            "approval_level": self.approval_level,
            "pending_approval": self.pending_approval,
            "current_plan": self.current_plan,
            "agent_trace": self.agent_trace,
            "message_count": len(self.conversation.messages),
            "has_context_summary": bool(self.context_summary),
        }
    
    def add_message(self, role: str, content: str, **kwargs) -> Message:
        """Agrega un mensaje a la conversación."""
        msg_role = MessageRole(role)
        msg = Message(role=msg_role, content=content, **kwargs)
        self.conversation.add_message(msg)
        return msg
    
    def get_messages_for_display(self) -> List[Dict[str, Any]]:
        """Obtiene mensajes formateados para el frontend."""
        messages = []
        for msg in self.conversation.messages:
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT):
                messages.append({
                    "role": msg.role.value,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                })
        return messages
    
    def clear(self) -> None:
        """Limpia la sesión."""
        self.conversation = Conversation()
        self.pending_approval = None
        self.current_plan = None
        self.agent_trace = []
        self.context_summary = ""


class SessionManager:
    """
    Gestor de sesiones con caché en memoria y backing store SQLite.

    Flujo de lectura:  memoria  →  SQLite  →  crear nueva
    Flujo de escritura: actualizar memoria + guardar en SQLite
    """

    _sessions: Dict[str, Session] = {}
    _db: Any = None  # PersistenceDB | None
    _session_locks: Dict[str, Any] = {}   # session_id → asyncio.Lock
    _cancel_flags: Dict[str, Any] = {}    # session_id → threading.Event

    # ------------------------------------------------------------------
    # Concurrencia y cancelación
    # ------------------------------------------------------------------

    @classmethod
    def get_lock(cls, session_id: str) -> Any:
        """
        Retorna (o crea) el asyncio.Lock de la sesión.
        Garantiza que sólo un agente se ejecute por sesión a la vez.
        """
        if session_id not in cls._session_locks:
            import asyncio as _asyncio
            cls._session_locks[session_id] = _asyncio.Lock()
        return cls._session_locks[session_id]

    @classmethod
    def get_cancel_flag(cls, session_id: str) -> Any:
        """
        Retorna (o crea) el threading.Event de cancelación de la sesión.
        Usa threading.Event (no asyncio.Event) para ser seguro desde hilos.
        """
        if session_id not in cls._cancel_flags:
            import threading as _threading
            cls._cancel_flags[session_id] = _threading.Event()
        return cls._cancel_flags[session_id]

    @classmethod
    def request_cancel(cls, session_id: str) -> None:
        """Solicita la cancelación del agente en ejecución para la sesión."""
        cls.get_cancel_flag(session_id).set()

    # ------------------------------------------------------------------
    # Inicialización de persistencia
    # ------------------------------------------------------------------

    @classmethod
    def init_persistence(cls, db_path: Path) -> None:
        """Conecta la capa SQLite. Llamar una vez en startup."""
        from web.persistence import PersistenceDB  # import diferido para evitar ciclos
        cls._db = PersistenceDB(db_path)

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    @classmethod
    def _session_to_meta(cls, session: Session) -> Dict[str, Any]:
        """Extrae metadatos de una sesión para persistencia."""
        return {
            "mode": session.mode,
            "model": session.model,
            "temperature": session.temperature,
            "workspace_root": session.workspace_root,
            "current_cwd": session.current_cwd,
            "approval_level": session.approval_level,
            "context_summary": session.context_summary,
            "pending_approval": session.pending_approval,
            "current_plan": session.current_plan,
            "created_at": session.created_at.isoformat(),
        }

    @classmethod
    def _messages_to_dicts(cls, session: Session) -> List[Dict[str, Any]]:
        """Convierte los mensajes de la sesión a dicts para SQLite."""
        return [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "attachments": msg.attachments,
                "metadata": msg.metadata,
            }
            for msg in session.conversation.messages
        ]

    @classmethod
    def _reconstruct(
        cls,
        session_id: str,
        meta: Dict[str, Any],
        msg_dicts: List[Dict[str, Any]],
    ) -> Session:
        """Reconstruye un objeto Session a partir de datos de SQLite."""
        messages: List[Message] = []
        for d in msg_dicts:
            try:
                messages.append(
                    Message(
                        role=MessageRole(d["role"]),
                        content=d["content"],
                        timestamp=datetime.fromisoformat(d["timestamp"]),
                        attachments=d.get("attachments", []),
                        metadata=d.get("metadata", {}),
                    )
                )
            except (ValueError, KeyError):
                continue

        conv = Conversation()
        conv.messages = messages

        return Session(
            id=session_id,
            conversation=conv,
            mode=meta.get("mode", OperationMode.AGENT),
            model=meta.get("model", OLLAMA_DEFAULT_MODEL),
            temperature=float(meta.get("temperature", 0.7)),
            workspace_root=meta.get("workspace_root", DEFAULT_WORKSPACE_ROOT),
            current_cwd=meta.get("current_cwd", DEFAULT_WORKSPACE_ROOT),
            approval_level=meta.get("approval_level", ApprovalLevel.WRITE_ONLY),
            context_summary=meta.get("context_summary", ""),
            pending_approval=meta.get("pending_approval"),
            current_plan=meta.get("current_plan"),
            created_at=datetime.fromisoformat(
                meta.get("created_at", datetime.now().isoformat())
            ),
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @classmethod
    def get_or_create(cls, session_id: Optional[str] = None) -> Session:
        """Obtiene o crea una sesión (memoria → DB → nueva)."""
        if session_id and session_id in cls._sessions:
            return cls._sessions[session_id]

        # Intentar cargar desde DB
        if session_id and cls._db:
            result = cls._db.load_session(session_id)
            if result:
                meta, msg_dicts = result
                session = cls._reconstruct(session_id, meta, msg_dicts)
                cls._sessions[session.id] = session
                return session

        # Crear nueva
        session = Session(id=session_id) if session_id else Session()
        cls._sessions[session.id] = session
        return session

    @classmethod
    def get(cls, session_id: str) -> Optional[Session]:
        """Obtiene una sesión por ID (memoria → DB)."""
        if session_id in cls._sessions:
            return cls._sessions[session_id]

        if cls._db:
            result = cls._db.load_session(session_id)
            if result:
                meta, msg_dicts = result
                session = cls._reconstruct(session_id, meta, msg_dicts)
                cls._sessions[session.id] = session
                return session

        return None

    @classmethod
    def save(cls, session: Session) -> None:
        """Persiste el estado actual de una sesión en SQLite."""
        if not cls._db:
            return
        cls._db.save_session(
            session.id,
            cls._session_to_meta(session),
            cls._messages_to_dicts(session),
        )

    @classmethod
    def delete(cls, session_id: str) -> bool:
        """Elimina una sesión de memoria y SQLite."""
        in_memory = cls._sessions.pop(session_id, None) is not None
        in_db = cls._db.delete_session(session_id) if cls._db else False
        return in_memory or in_db

    @classmethod
    def list_sessions(cls) -> List[Dict[str, Any]]:
        """Lista sesiones (desde DB si disponible, sino memoria)."""
        if cls._db:
            return cls._db.list_sessions()
        return [s.to_dict() for s in cls._sessions.values()]

    @classmethod
    def cleanup_old_sessions(cls, max_age_hours: int = 24) -> int:
        """Limpia sesiones antiguas de memoria y SQLite."""
        now = datetime.now()
        to_delete = [
            sid
            for sid, s in cls._sessions.items()
            if (now - s.created_at).total_seconds() / 3600 > max_age_hours
        ]
        for sid in to_delete:
            cls._sessions.pop(sid, None)

        db_deleted = cls._db.cleanup_old_sessions(max_age_hours) if cls._db else 0
        return len(to_delete) + db_deleted
