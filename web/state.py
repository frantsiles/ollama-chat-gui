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
    OLLAMA_BASE_URL,
    OLLAMA_DEFAULT_MODEL,
    OperationMode,
)
from core.models import Conversation, Message, MessageRole, Plan


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
    """Gestor de sesiones en memoria."""
    
    _sessions: Dict[str, Session] = {}
    
    @classmethod
    def get_or_create(cls, session_id: Optional[str] = None) -> Session:
        """Obtiene o crea una sesión."""
        if session_id and session_id in cls._sessions:
            return cls._sessions[session_id]

        if session_id:
            session = Session(id=session_id)
        else:
            session = Session()
        cls._sessions[session.id] = session
        return session
    
    @classmethod
    def get(cls, session_id: str) -> Optional[Session]:
        """Obtiene una sesión por ID."""
        return cls._sessions.get(session_id)
    
    @classmethod
    def delete(cls, session_id: str) -> bool:
        """Elimina una sesión."""
        if session_id in cls._sessions:
            del cls._sessions[session_id]
            return True
        return False
    
    @classmethod
    def list_sessions(cls) -> List[Dict[str, Any]]:
        """Lista todas las sesiones."""
        return [session.to_dict() for session in cls._sessions.values()]
    
    @classmethod
    def cleanup_old_sessions(cls, max_age_hours: int = 24) -> int:
        """Limpia sesiones antiguas."""
        now = datetime.now()
        to_delete = []
        
        for session_id, session in cls._sessions.items():
            age = (now - session.created_at).total_seconds() / 3600
            if age > max_age_hours:
                to_delete.append(session_id)
        
        for session_id in to_delete:
            del cls._sessions[session_id]
        
        return len(to_delete)
