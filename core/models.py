"""Modelos de datos para el agente de IA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class MessageRole(str, Enum):
    """Roles de mensaje en la conversación."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class StepStatus(str, Enum):
    """Estado de un paso del plan."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"


class PlanStatus(str, Enum):
    """Estado general del plan."""
    DRAFT = "draft"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Message:
    """Mensaje en la conversación."""
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    attachments: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)  # Base64 encoded
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_ollama_format(self) -> Dict[str, Any]:
        """Convierte a formato esperado por Ollama API."""
        msg = {"role": self.role.value, "content": self.content}
        if self.images:
            msg["images"] = self.images
        return msg
    
    def to_dict(self) -> Dict[str, Any]:
        """Serializa el mensaje completo."""
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "attachments": self.attachments,
            "metadata": self.metadata,
        }


@dataclass
class ToolCall:
    """Solicitud de ejecución de herramienta."""
    tool: str
    args: Dict[str, Any]
    reasoning: str = ""
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "args": self.args,
            "reasoning": self.reasoning,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolCall:
        return cls(
            tool=data["tool"],
            args=data.get("args", {}),
            reasoning=data.get("reasoning", ""),
            id=data.get("id", str(uuid4())[:8]),
        )
    
    def __str__(self) -> str:
        import json
        return f"{self.tool}({json.dumps(self.args, ensure_ascii=False)})"


@dataclass
class ToolResult:
    """Resultado de ejecución de herramienta."""
    tool_call: ToolCall
    success: bool
    output: str
    error: Optional[str] = None
    new_cwd: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_call": self.tool_call.to_dict(),
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "new_cwd": self.new_cwd,
        }


@dataclass
class PlanStep:
    """Paso individual en un plan de ejecución."""
    id: int
    description: str
    tool: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    requires_approval: bool = False
    result: Optional[ToolResult] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "tool": self.tool,
            "args": self.args,
            "status": self.status.value,
            "requires_approval": self.requires_approval,
            "result": self.result.to_dict() if self.result else None,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlanStep:
        return cls(
            id=data["id"],
            description=data["description"],
            tool=data.get("tool"),
            args=data.get("args", {}),
            status=StepStatus(data.get("status", "pending")),
            requires_approval=data.get("requires_approval", False),
            error_message=data.get("error_message"),
        )


@dataclass
class Plan:
    """Plan de ejecución con múltiples pasos."""
    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    description: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    context: str = ""  # Contexto original del usuario
    
    @property
    def current_step_index(self) -> int:
        """Retorna el índice del primer paso pendiente."""
        for i, step in enumerate(self.steps):
            if step.status in (StepStatus.PENDING, StepStatus.AWAITING_APPROVAL):
                return i
        return len(self.steps)
    
    @property
    def current_step(self) -> Optional[PlanStep]:
        """Retorna el paso actual."""
        idx = self.current_step_index
        if idx < len(self.steps):
            return self.steps[idx]
        return None
    
    @property
    def is_complete(self) -> bool:
        """Verifica si todos los pasos están completos."""
        return all(
            step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
            for step in self.steps
        )
    
    @property
    def progress(self) -> tuple[int, int]:
        """Retorna (completados, total)."""
        completed = sum(
            1 for step in self.steps
            if step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        )
        return completed, len(self.steps)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "context": self.context,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Plan:
        return cls(
            id=data.get("id", str(uuid4())),
            title=data.get("title", ""),
            description=data.get("description", ""),
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
            status=PlanStatus(data.get("status", "draft")),
            context=data.get("context", ""),
        )
    
    def to_markdown(self) -> str:
        """Genera representación markdown del plan."""
        lines = [f"# {self.title or 'Plan de Ejecución'}", ""]
        if self.description:
            lines.extend([self.description, ""])
        
        lines.append("## Pasos")
        for step in self.steps:
            status_icon = {
                StepStatus.PENDING: "⬜",
                StepStatus.IN_PROGRESS: "🔄",
                StepStatus.COMPLETED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.SKIPPED: "⏭️",
                StepStatus.AWAITING_APPROVAL: "⏸️",
            }.get(step.status, "⬜")
            
            approval_mark = " 🔒" if step.requires_approval else ""
            lines.append(f"{status_icon} **{step.id}.** {step.description}{approval_mark}")
            
            if step.tool:
                lines.append(f"   - Tool: `{step.tool}`")
            if step.error_message:
                lines.append(f"   - Error: {step.error_message}")
        
        return "\n".join(lines)


@dataclass
class AgentState:
    """Estado interno del agente durante una ejecución."""
    mode: str = "chat"  # chat, agent, plan
    is_running: bool = False
    current_plan: Optional[Plan] = None
    step_count: int = 0
    trace: List[str] = field(default_factory=list)
    pending_approval: Optional[ToolCall] = None
    last_error: Optional[str] = None
    
    def add_trace(self, message: str) -> None:
        """Agrega una línea al trace de ejecución."""
        self.trace.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
    
    def reset(self) -> None:
        """Reinicia el estado para una nueva ejecución."""
        self.is_running = False
        self.step_count = 0
        self.trace = []
        self.pending_approval = None
        self.last_error = None


@dataclass
class Conversation:
    """Conversación completa con historial."""
    id: str = field(default_factory=lambda: str(uuid4()))
    messages: List[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    title: str = ""
    workspace_root: str = ""
    current_cwd: str = ""
    
    def add_message(self, message: Message) -> None:
        """Agrega un mensaje a la conversación."""
        self.messages.append(message)
        self.updated_at = datetime.now()
    
    def add_user_message(self, content: str, **kwargs) -> Message:
        """Crea y agrega un mensaje de usuario."""
        msg = Message(role=MessageRole.USER, content=content, **kwargs)
        self.add_message(msg)
        return msg
    
    def add_assistant_message(self, content: str, **kwargs) -> Message:
        """Crea y agrega un mensaje del asistente."""
        msg = Message(role=MessageRole.ASSISTANT, content=content, **kwargs)
        self.add_message(msg)
        return msg
    
    def add_system_message(self, content: str, **kwargs) -> Message:
        """Crea y agrega un mensaje de sistema."""
        msg = Message(role=MessageRole.SYSTEM, content=content, **kwargs)
        self.add_message(msg)
        return msg
    
    def get_ollama_messages(self) -> List[Dict[str, Any]]:
        """Retorna mensajes en formato Ollama."""
        return [msg.to_ollama_format() for msg in self.messages]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "title": self.title,
            "workspace_root": self.workspace_root,
            "current_cwd": self.current_cwd,
        }
