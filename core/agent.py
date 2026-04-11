"""Agente principal con ciclo ReAct y soporte para múltiples modos."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

from config import (
    MAX_AGENT_STEPS,
    MAX_CONTEXT_MESSAGES,
    MAX_CONTEXT_MESSAGES_KEEP,
    OperationMode,
)
from core.models import (
    AgentState,
    Conversation,
    Message,
    MessageRole,
    Plan,
    PlanStatus,
    StepStatus,
    ToolCall,
    ToolResult,
)
from llm.client import OllamaClient, OllamaClientError
from llm.prompts import PromptManager
from security.approval import ApprovalManager, ApprovalStatus
from tools.registry import ToolRegistry


@dataclass
class AgentResponse:
    """Respuesta del agente."""
    content: str
    status: str  # completed, awaiting_approval, max_steps, error
    tool_results: List[ToolResult] = field(default_factory=list)
    plan: Optional[Plan] = None
    error: Optional[str] = None
    trace: List[str] = field(default_factory=list)
    new_cwd: Optional[str] = None


class Agent:
    """
    Agente de IA con soporte para múltiples modos de operación.
    
    Modos:
    - CHAT: Conversación simple sin herramientas
    - AGENT: Ciclo ReAct automático con herramientas
    - PLAN: Planifica antes de ejecutar
    """
    
    def __init__(
        self,
        client: OllamaClient,
        model: str,
        workspace_root: Path,
        current_cwd: Optional[Path] = None,
        temperature: float = 0.7,
        mode: str = OperationMode.AGENT,
    ):
        """
        Inicializa el agente.
        
        Args:
            client: Cliente de Ollama
            model: Nombre del modelo a usar
            workspace_root: Raíz del workspace
            current_cwd: Directorio de trabajo actual
            temperature: Temperatura para generación
            mode: Modo de operación
        """
        self.client = client
        self.model = model
        self.workspace_root = workspace_root.resolve()
        self.current_cwd = (current_cwd or workspace_root).resolve()
        self.temperature = temperature
        self.mode = mode
        
        # Componentes
        self.tool_registry = ToolRegistry(
            workspace_root=self.workspace_root,
            current_cwd=self.current_cwd,
        )
        self.approval_manager = ApprovalManager()
        self.state = AgentState(mode=mode)
        # Running lightweight summary of old conversation turns
        self._context_summary: str = ""
    
    def set_mode(self, mode: str) -> None:
        """Cambia el modo de operación."""
        self.mode = mode
        self.state.mode = mode
    
    def set_cwd(self, cwd: Path) -> None:
        """Actualiza el directorio de trabajo."""
        self.current_cwd = cwd.resolve()
        self.tool_registry.update_cwd(self.current_cwd)
    
    def _call_model(
        self,
        messages: List[Dict[str, Any]],
        stream: bool = False,
    ) -> str:
        """Llama al modelo y retorna la respuesta."""
        if stream:
            chunks = []
            for chunk in self.client.chat_stream(
                model=self.model,
                messages=messages,
                options={"temperature": self.temperature},
            ):
                chunks.append(chunk)
            return "".join(chunks)
        else:
            return self.client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": self.temperature},
            )
    
    def _apply_context_window(
        self,
        messages: List,
    ) -> List:
        """
        Aplica ventana de contexto:
        - Si hay pocos mensajes, los devuelve todos.
        - Si hay muchos, mantiene solo los últimos N y antepone el sumario.
        """
        if len(messages) <= MAX_CONTEXT_MESSAGES_KEEP:
            return list(messages)

        recent = list(messages[-MAX_CONTEXT_MESSAGES_KEEP:])

        if self._context_summary:
            summary_msg = Message(
                role=MessageRole.SYSTEM,
                content=(
                    "[Contexto resumido de mensajes anteriores]:\n"
                    + self._context_summary
                ),
            )
            return [summary_msg] + recent

        return recent

    def _build_lightweight_summary(self, messages: List) -> str:
        """Genera un resumen textual ligero (sin llamada al LLM)."""
        parts: List[str] = []
        for msg in messages:
            if msg.role == MessageRole.USER:
                snippet = msg.content[:300].replace("\n", " ")
                parts.append(f"• Usuario: {snippet}")
            elif msg.role == MessageRole.ASSISTANT:
                first_line = msg.content.split("\n")[0][:200]
                parts.append(f"• Asistente: {first_line}")
            # Omitir mensajes de sistema (workspace ctx, tool results)
        return "\n".join(parts[-15:])  # Máximo 15 entradas

    def _maybe_summarize(self, conversation: Conversation) -> None:
        """Actualiza el sumario si la conversación supera el umbral."""
        if len(conversation.messages) < MAX_CONTEXT_MESSAGES:
            return
        old_messages = conversation.messages[:-MAX_CONTEXT_MESSAGES_KEEP]
        summary = self._build_lightweight_summary(old_messages)
        if summary:
            self._context_summary = summary

    def _build_messages(
        self,
        conversation: Conversation,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Construye la lista de mensajes para el modelo (con ventana de contexto)."""
        messages = []

        # System prompt
        if system_prompt is None:
            system_prompt = PromptManager.get_system_prompt(self.mode)

        messages.append({"role": "system", "content": system_prompt})

        # Mensajes de la conversación con ventana de contexto
        windowed = self._apply_context_window(conversation.messages)
        for msg in windowed:
            messages.append(msg.to_ollama_format())

        return messages
    
    def _add_workspace_context(self, conversation: Conversation) -> None:
        """Añade contexto del workspace a la conversación."""
        entries = []
        try:
            for item in self.current_cwd.glob("*"):
                if len(entries) >= 60:
                    break
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{item.name}{suffix}")
        except OSError:
            pass
        
        context = PromptManager.build_workspace_context(
            workspace_root=str(self.workspace_root),
            current_cwd=str(self.current_cwd),
            entries=sorted(entries),
        )
        conversation.add_system_message(context)
    
    def _repair_tool_call(self, raw_response: str) -> Optional[ToolCall]:
        """Intenta reparar una respuesta de tool call malformada."""
        repair_messages = [
            {"role": "system", "content": PromptManager.get_tool_repair_prompt()},
            {"role": "user", "content": raw_response},
        ]
        
        try:
            repaired = self._call_model(repair_messages)
        except OllamaClientError:
            return None
        
        return ToolRegistry.extract_tool_call(repaired)
    
    def chat(
        self,
        user_input: str,
        conversation: Conversation,
        attachments: Optional[List[str]] = None,
        images: Optional[List[str]] = None,
    ) -> AgentResponse:
        """
        Modo CHAT: Conversación simple sin herramientas.
        
        Args:
            user_input: Mensaje del usuario
            conversation: Conversación actual
            attachments: Archivos adjuntos (texto)
            images: Imágenes en base64
            
        Returns:
            Respuesta del agente
        """
        self.state.reset()
        self.state.mode = OperationMode.CHAT
        
        # Agregar mensaje del usuario
        user_msg = conversation.add_user_message(
            content=user_input,
            attachments=attachments or [],
            images=images or [],
        )
        
        # Llamar al modelo
        messages = self._build_messages(conversation)
        
        try:
            response = self._call_model(messages)
        except OllamaClientError as e:
            return AgentResponse(
                content="",
                status="error",
                error=str(e),
            )
        
        # Agregar respuesta
        conversation.add_assistant_message(response)
        
        return AgentResponse(
            content=response,
            status="completed",
        )
    
    def run(
        self,
        user_input: str,
        conversation: Conversation,
        attachments: Optional[List[str]] = None,
        images: Optional[List[str]] = None,
        step_callback: Optional[Callable[[str], None]] = None,
    ) -> AgentResponse:
        """
        Modo AGENT: Ciclo ReAct con herramientas.
        
        Args:
            user_input: Mensaje del usuario
            conversation: Conversación actual
            attachments: Archivos adjuntos
            images: Imágenes en base64
            
        Returns:
            Respuesta del agente
        """
        self.state.reset()
        self.state.mode = OperationMode.AGENT
        self.state.is_running = True

        # Comprimir contexto si la conversación es larga
        self._maybe_summarize(conversation)

        # Agregar contexto del workspace
        self._add_workspace_context(conversation)
        
        # Agregar mensaje del usuario
        conversation.add_user_message(
            content=user_input,
            attachments=attachments or [],
            images=images or [],
        )
        
        tool_results: List[ToolResult] = []
        
        for step in range(1, MAX_AGENT_STEPS + 1):
            self.state.step_count = step
            trace_consulta = f"Paso {step}: consultando al modelo"
            self.state.add_trace(trace_consulta)
            if step_callback:
                step_callback(trace_consulta)
            
            # Llamar al modelo
            messages = self._build_messages(conversation)
            
            try:
                response = self._call_model(messages)
            except OllamaClientError as e:
                self.state.is_running = False
                return AgentResponse(
                    content="",
                    status="error",
                    error=str(e),
                    trace=self.state.trace,
                    tool_results=tool_results,
                )
            
            if not response.strip():
                self.state.add_trace(f"Paso {step}: respuesta vacía, reintentando")
                continue
            
            # Intentar extraer tool call
            tool_call = ToolRegistry.extract_tool_call(response)
            
            if not tool_call and ToolRegistry.looks_like_tool_call(response):
                self.state.add_trace(f"Paso {step}: intentando reparar tool call malformada")
                tool_call = self._repair_tool_call(response)
            
            if not tool_call:
                # No hay tool call, es respuesta final
                self.state.add_trace(f"Paso {step}: respuesta final sin tool")
                conversation.add_assistant_message(response)
                self.state.is_running = False
                
                return AgentResponse(
                    content=response,
                    status="completed",
                    trace=self.state.trace,
                    tool_results=tool_results,
                    new_cwd=str(self.current_cwd),
                )
            
            # Validar tool call
            validation_error = self.tool_registry.validate_tool_call(tool_call)
            if validation_error:
                self.state.add_trace(f"Paso {step}: tool inválida - {validation_error}")
                conversation.add_system_message(
                    f"Error en tool call: {validation_error}"
                )
                continue
            
            # Verificar si requiere aprobación
            is_write = self.tool_registry.is_tool_write_operation(tool_call)
            if self.approval_manager.requires_approval(tool_call, is_write):
                self.state.add_trace(f"Paso {step}: esperando aprobación para {tool_call}")
                self.state.pending_approval = tool_call
                self.approval_manager.request_approval(tool_call)
                
                return AgentResponse(
                    content=f"Se requiere aprobación para: `{tool_call}`",
                    status="awaiting_approval",
                    trace=self.state.trace,
                    tool_results=tool_results,
                    new_cwd=str(self.current_cwd),
                )
            
            # Ejecutar tool
            trace_exec = f"Paso {step}: ejecutando {tool_call.tool}"
            self.state.add_trace(trace_exec)
            if step_callback:
                step_callback(trace_exec)
            result = self.tool_registry.execute(tool_call)
            tool_results.append(result)
            
            # Actualizar CWD si cambió
            if result.new_cwd:
                self.set_cwd(Path(result.new_cwd))
            
            # Agregar resultado al contexto
            observation = PromptManager.build_tool_result_context(
                step=step,
                tool_call=str(tool_call),
                result=result.output if result.success else f"Error: {result.error}",
            )
            conversation.add_system_message(observation)
        
        # Límite de pasos alcanzado
        self.state.add_trace(f"Límite de {MAX_AGENT_STEPS} pasos alcanzado")
        self.state.is_running = False
        
        return AgentResponse(
            content=f"Se alcanzó el límite de {MAX_AGENT_STEPS} pasos.",
            status="max_steps",
            trace=self.state.trace,
            tool_results=tool_results,
            new_cwd=str(self.current_cwd),
        )
    
    def resume_after_approval(
        self,
        conversation: Conversation,
        approved: bool,
    ) -> AgentResponse:
        """
        Continúa la ejecución después de una aprobación.
        
        Args:
            conversation: Conversación actual
            approved: Si fue aprobado
            
        Returns:
            Respuesta del agente
        """
        if not self.approval_manager.has_pending:
            return AgentResponse(
                content="No hay acción pendiente de aprobación.",
                status="error",
                error="No pending approval",
            )
        
        pending = self.approval_manager.pending_request
        tool_call = pending.tool_call
        
        if not approved:
            self.approval_manager.reject_pending()
            self.state.add_trace("Acción rechazada por el usuario")
            conversation.add_system_message("El usuario rechazó la acción.")
            
            return AgentResponse(
                content="Acción rechazada.",
                status="completed",
                trace=self.state.trace,
            )
        
        # Aprobar y ejecutar
        self.approval_manager.approve_pending()
        self.state.add_trace(f"Acción aprobada, ejecutando {tool_call}")
        
        result = self.tool_registry.execute(tool_call)
        
        if result.new_cwd:
            self.set_cwd(Path(result.new_cwd))
        
        # Agregar resultado
        observation = PromptManager.build_tool_result_context(
            step=self.state.step_count,
            tool_call=str(tool_call),
            result=result.output if result.success else f"Error: {result.error}",
        )
        conversation.add_system_message(observation)
        
        # Continuar el ciclo
        return self.run(
            user_input="",  # Continuar sin nuevo input
            conversation=conversation,
        )
    
    def execute_plan_step(
        self,
        plan: Plan,
        conversation: Conversation,
    ) -> AgentResponse:
        """
        Ejecuta el siguiente paso de un plan.
        
        Args:
            plan: Plan a ejecutar
            conversation: Conversación actual
            
        Returns:
            Respuesta del agente
        """
        current_step = plan.current_step
        if not current_step:
            plan.status = PlanStatus.COMPLETED
            return AgentResponse(
                content="Plan completado.",
                status="completed",
                plan=plan,
            )
        
        # Marcar como en progreso
        current_step.status = StepStatus.IN_PROGRESS
        plan.status = PlanStatus.IN_PROGRESS
        
        self.state.add_trace(f"Ejecutando paso {current_step.id}: {current_step.description}")
        
        # Si requiere aprobación
        if current_step.requires_approval:
            if current_step.tool:
                tool_call = ToolCall(
                    tool=current_step.tool,
                    args=current_step.args,
                )
                self.approval_manager.request_approval(tool_call)
                current_step.status = StepStatus.AWAITING_APPROVAL
                
                return AgentResponse(
                    content=f"Paso {current_step.id} requiere aprobación: {current_step.description}",
                    status="awaiting_approval",
                    plan=plan,
                    trace=self.state.trace,
                )
        
        # Ejecutar el paso
        if current_step.tool:
            tool_call = ToolCall(
                tool=current_step.tool,
                args=current_step.args,
            )
            result = self.tool_registry.execute(tool_call)
            current_step.result = result
            
            if result.new_cwd:
                self.set_cwd(Path(result.new_cwd))
            
            if result.success:
                current_step.status = StepStatus.COMPLETED
                self.state.add_trace(f"Paso {current_step.id} completado")
            else:
                current_step.status = StepStatus.FAILED
                current_step.error_message = result.error
                self.state.add_trace(f"Paso {current_step.id} falló: {result.error}")
        else:
            # Paso sin tool (solo descripción)
            current_step.status = StepStatus.COMPLETED
        
        # Verificar si el plan está completo
        if plan.is_complete:
            plan.status = PlanStatus.COMPLETED
            return AgentResponse(
                content="Plan completado exitosamente.",
                status="completed",
                plan=plan,
                trace=self.state.trace,
            )
        
        # Continuar con el siguiente paso
        return self.execute_plan_step(plan, conversation)
