"""Sistema de aprobación para acciones peligrosas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from config import ApprovalLevel
from core.models import ToolCall


class ApprovalStatus(str, Enum):
    """Estado de una solicitud de aprobación."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ALWAYS_APPROVED = "always_approved"


@dataclass
class ApprovalRequest:
    """Solicitud de aprobación para una acción."""
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    tool_call: Optional[ToolCall] = None
    description: str = ""
    reason: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    
    def approve(self) -> None:
        """Aprueba la solicitud."""
        self.status = ApprovalStatus.APPROVED
        self.resolved_at = datetime.now()
    
    def reject(self) -> None:
        """Rechaza la solicitud."""
        self.status = ApprovalStatus.REJECTED
        self.resolved_at = datetime.now()
    
    def approve_always(self) -> None:
        """Aprueba y marca para aprobar siempre."""
        self.status = ApprovalStatus.ALWAYS_APPROVED
        self.resolved_at = datetime.now()
    
    @property
    def is_pending(self) -> bool:
        return self.status == ApprovalStatus.PENDING
    
    @property
    def is_approved(self) -> bool:
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.ALWAYS_APPROVED)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool_call": self.tool_call.to_dict() if self.tool_call else None,
            "description": self.description,
            "reason": self.reason,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class ApprovalManager:
    """
    Gestor de aprobaciones para acciones del agente.
    
    Maneja la lógica de cuándo pedir aprobación y mantiene
    el estado de aprobaciones permanentes.
    """
    
    def __init__(self, level: str = ApprovalLevel.WRITE_ONLY):
        """
        Inicializa el gestor de aprobaciones.
        
        Args:
            level: Nivel de aprobación (none, write, all)
        """
        self.level = level
        self._always_approved_tools: set[str] = set()
        self._pending_request: Optional[ApprovalRequest] = None
        self._history: List[ApprovalRequest] = []
    
    @property
    def pending_request(self) -> Optional[ApprovalRequest]:
        """Retorna la solicitud pendiente actual."""
        return self._pending_request
    
    @property
    def has_pending(self) -> bool:
        """Indica si hay una solicitud pendiente."""
        return self._pending_request is not None and self._pending_request.is_pending
    
    def requires_approval(self, tool_call: ToolCall, is_write: bool) -> bool:
        """
        Determina si una llamada a tool requiere aprobación.
        
        Args:
            tool_call: Llamada a evaluar
            is_write: Si es una operación de escritura
            
        Returns:
            True si requiere aprobación
        """
        # Sin aprobaciones
        if self.level == ApprovalLevel.NONE:
            return False
        
        # Ya fue aprobada permanentemente
        if tool_call.tool in self._always_approved_tools:
            return False
        
        # Todas las acciones requieren aprobación
        if self.level == ApprovalLevel.ALL:
            return True
        
        # Solo escritura requiere aprobación
        if self.level == ApprovalLevel.WRITE_ONLY:
            return is_write
        
        return False
    
    def request_approval(
        self,
        tool_call: ToolCall,
        description: Optional[str] = None,
        reason: str = "",
    ) -> ApprovalRequest:
        """
        Crea una solicitud de aprobación.
        
        Args:
            tool_call: Llamada que requiere aprobación
            description: Descripción legible de la acción
            reason: Razón por la que se pide aprobación
            
        Returns:
            ApprovalRequest creada
        """
        if description is None:
            description = str(tool_call)
        
        request = ApprovalRequest(
            tool_call=tool_call,
            description=description,
            reason=reason,
        )
        
        self._pending_request = request
        return request
    
    def resolve_pending(self, status: ApprovalStatus) -> Optional[ApprovalRequest]:
        """
        Resuelve la solicitud pendiente.
        
        Args:
            status: Estado de resolución
            
        Returns:
            La solicitud resuelta o None si no había pendiente
        """
        if not self._pending_request:
            return None
        
        request = self._pending_request
        
        if status == ApprovalStatus.APPROVED:
            request.approve()
        elif status == ApprovalStatus.REJECTED:
            request.reject()
        elif status == ApprovalStatus.ALWAYS_APPROVED:
            request.approve_always()
            if request.tool_call:
                self._always_approved_tools.add(request.tool_call.tool)
        
        self._history.append(request)
        self._pending_request = None
        
        return request
    
    def approve_pending(self) -> Optional[ApprovalRequest]:
        """Aprueba la solicitud pendiente."""
        return self.resolve_pending(ApprovalStatus.APPROVED)
    
    def reject_pending(self) -> Optional[ApprovalRequest]:
        """Rechaza la solicitud pendiente."""
        return self.resolve_pending(ApprovalStatus.REJECTED)
    
    def approve_always(self) -> Optional[ApprovalRequest]:
        """Aprueba permanentemente la solicitud pendiente."""
        return self.resolve_pending(ApprovalStatus.ALWAYS_APPROVED)
    
    def clear_pending(self) -> None:
        """Limpia la solicitud pendiente sin resolver."""
        self._pending_request = None
    
    def reset(self) -> None:
        """Reinicia todo el estado de aprobaciones."""
        self._always_approved_tools.clear()
        self._pending_request = None
        self._history.clear()
    
    def set_level(self, level: str) -> None:
        """Cambia el nivel de aprobación."""
        self.level = level
    
    def get_history(self) -> List[ApprovalRequest]:
        """Retorna el historial de aprobaciones."""
        return list(self._history)
