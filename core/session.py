"""Gestor de sesiones de conversación."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.models import Conversation, Message, MessageRole


class SessionManager:
    """
    Gestor de sesiones de conversación.
    
    Maneja múltiples conversaciones y su persistencia.
    """
    
    def __init__(self, storage_dir: Optional[Path] = None):
        """
        Inicializa el gestor de sesiones.
        
        Args:
            storage_dir: Directorio para persistencia (opcional)
        """
        self.storage_dir = storage_dir
        self._sessions: Dict[str, Conversation] = {}
        self._active_session_id: Optional[str] = None
        
        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)
    
    @property
    def active_session(self) -> Optional[Conversation]:
        """Retorna la sesión activa."""
        if self._active_session_id:
            return self._sessions.get(self._active_session_id)
        return None
    
    @property
    def active_session_id(self) -> Optional[str]:
        """Retorna el ID de la sesión activa."""
        return self._active_session_id
    
    def create_session(
        self,
        workspace_root: str = "",
        title: str = "",
    ) -> Conversation:
        """
        Crea una nueva sesión de conversación.
        
        Args:
            workspace_root: Raíz del workspace
            title: Título de la sesión
            
        Returns:
            Nueva conversación creada
        """
        session = Conversation(
            workspace_root=workspace_root,
            current_cwd=workspace_root,
            title=title or f"Sesión {len(self._sessions) + 1}",
        )
        
        self._sessions[session.id] = session
        self._active_session_id = session.id
        
        return session
    
    def get_session(self, session_id: str) -> Optional[Conversation]:
        """Obtiene una sesión por ID."""
        return self._sessions.get(session_id)
    
    def set_active_session(self, session_id: str) -> bool:
        """
        Establece la sesión activa.
        
        Args:
            session_id: ID de la sesión
            
        Returns:
            True si se cambió correctamente
        """
        if session_id in self._sessions:
            self._active_session_id = session_id
            return True
        return False
    
    def delete_session(self, session_id: str) -> bool:
        """
        Elimina una sesión.
        
        Args:
            session_id: ID de la sesión a eliminar
            
        Returns:
            True si se eliminó correctamente
        """
        if session_id not in self._sessions:
            return False
        
        del self._sessions[session_id]
        
        if self._active_session_id == session_id:
            self._active_session_id = next(iter(self._sessions), None)
        
        # Eliminar archivo si existe
        if self.storage_dir:
            file_path = self.storage_dir / f"{session_id}.json"
            if file_path.exists():
                file_path.unlink()
        
        return True
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        Lista todas las sesiones.
        
        Returns:
            Lista de metadatos de sesiones
        """
        return [
            {
                "id": session.id,
                "title": session.title,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "message_count": len(session.messages),
                "is_active": session.id == self._active_session_id,
            }
            for session in self._sessions.values()
        ]
    
    def clear_session(self, session_id: Optional[str] = None) -> bool:
        """
        Limpia los mensajes de una sesión.
        
        Args:
            session_id: ID de la sesión (usa activa si no se especifica)
            
        Returns:
            True si se limpió correctamente
        """
        target_id = session_id or self._active_session_id
        if not target_id or target_id not in self._sessions:
            return False
        
        self._sessions[target_id].messages.clear()
        self._sessions[target_id].updated_at = datetime.now()
        return True
    
    def save_session(self, session_id: Optional[str] = None) -> bool:
        """
        Guarda una sesión a disco.
        
        Args:
            session_id: ID de la sesión (usa activa si no se especifica)
            
        Returns:
            True si se guardó correctamente
        """
        if not self.storage_dir:
            return False
        
        target_id = session_id or self._active_session_id
        if not target_id or target_id not in self._sessions:
            return False
        
        session = self._sessions[target_id]
        file_path = self.storage_dir / f"{target_id}.json"
        
        try:
            data = session.to_dict()
            file_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except (OSError, TypeError):
            return False
    
    def load_session(self, session_id: str) -> Optional[Conversation]:
        """
        Carga una sesión desde disco.
        
        Args:
            session_id: ID de la sesión
            
        Returns:
            Conversación cargada o None
        """
        if not self.storage_dir:
            return None
        
        file_path = self.storage_dir / f"{session_id}.json"
        if not file_path.exists():
            return None
        
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            
            # Reconstruir mensajes
            messages = []
            for msg_data in data.get("messages", []):
                msg = Message(
                    role=MessageRole(msg_data["role"]),
                    content=msg_data["content"],
                    attachments=msg_data.get("attachments", []),
                    metadata=msg_data.get("metadata", {}),
                )
                messages.append(msg)
            
            session = Conversation(
                id=data["id"],
                messages=messages,
                title=data.get("title", ""),
                workspace_root=data.get("workspace_root", ""),
                current_cwd=data.get("current_cwd", ""),
            )
            
            self._sessions[session.id] = session
            return session
            
        except (OSError, json.JSONDecodeError, KeyError):
            return None
    
    def load_all_sessions(self) -> int:
        """
        Carga todas las sesiones desde disco.
        
        Returns:
            Número de sesiones cargadas
        """
        if not self.storage_dir:
            return 0
        
        loaded = 0
        for file_path in self.storage_dir.glob("*.json"):
            session_id = file_path.stem
            if self.load_session(session_id):
                loaded += 1
        
        return loaded
    
    def save_all_sessions(self) -> int:
        """
        Guarda todas las sesiones a disco.
        
        Returns:
            Número de sesiones guardadas
        """
        if not self.storage_dir:
            return 0
        
        saved = 0
        for session_id in self._sessions:
            if self.save_session(session_id):
                saved += 1
        
        return saved
    
    def export_session(
        self,
        session_id: Optional[str] = None,
        format: str = "json",
    ) -> Optional[str]:
        """
        Exporta una sesión a texto.
        
        Args:
            session_id: ID de la sesión
            format: Formato de exportación (json, markdown)
            
        Returns:
            Contenido exportado o None
        """
        target_id = session_id or self._active_session_id
        if not target_id or target_id not in self._sessions:
            return None
        
        session = self._sessions[target_id]
        
        if format == "json":
            return json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        
        elif format == "markdown":
            lines = [
                f"# {session.title or 'Conversación'}",
                "",
                f"- ID: {session.id}",
                f"- Creado: {session.created_at.strftime('%Y-%m-%d %H:%M')}",
                f"- Mensajes: {len(session.messages)}",
                "",
                "## Conversación",
                "",
            ]
            
            role_labels = {
                MessageRole.USER: "👤 Usuario",
                MessageRole.ASSISTANT: "🤖 Asistente",
                MessageRole.SYSTEM: "⚙️ Sistema",
            }
            
            for msg in session.messages:
                label = role_labels.get(msg.role, str(msg.role))
                lines.append(f"### {label}")
                lines.append("")
                lines.append(msg.content)
                lines.append("")
            
            return "\n".join(lines)
        
        return None
    
    def get_or_create_active(
        self,
        workspace_root: str = "",
    ) -> Conversation:
        """
        Obtiene la sesión activa o crea una nueva.
        
        Args:
            workspace_root: Raíz del workspace para nueva sesión
            
        Returns:
            Conversación activa
        """
        if self.active_session:
            return self.active_session
        
        return self.create_session(workspace_root=workspace_root)
