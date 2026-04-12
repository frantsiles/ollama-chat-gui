"""Agente principal con ciclo ReAct y soporte para múltiples modos."""

from __future__ import annotations

import ast as _ast
import json as _json
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

from config import (
    MAX_AGENT_STEPS,
    MAX_CONTEXT_MESSAGES,
    MAX_CONTEXT_MESSAGES_KEEP,
    MAX_STEP_RETRIES,
    REFLECTION_ENABLED,
    REFLECTION_TEMPERATURE,
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
        # Memory context string injected into system prompt
        self._memory_context: str = ""
        # Optional MemoryStore for auto-extraction
        self._memory_store: Optional[Any] = None
    
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

        # System prompt con memoria inyectada
        if system_prompt is None:
            system_prompt = PromptManager.get_system_prompt_with_memory(
                self.mode, self._memory_context
            )

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
    
    # ------------------------------------------------------------------
    # Reflexión crítica (auto-revisión de respuestas)
    # ------------------------------------------------------------------

    def _reflect_on_response(
        self,
        response: str,
        conversation: Conversation,
    ) -> str:
        """
        Revisa la respuesta antes de entregarla.
        Si detecta problemas, retorna una versión corregida.
        """
        if not REFLECTION_ENABLED:
            return response

        from llm.prompts import REFLECTION_PROMPT

        # Contexto: últimos mensajes para que el revisor entienda la conversación
        recent = [
            f"{m.role.value}: {m.content[:500]}"
            for m in conversation.messages[-4:]
            if m.content
        ]
        context = "\n".join(recent)

        messages = [
            {"role": "system", "content": REFLECTION_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Contexto de la conversación:\n{context}\n\n"
                    f"Respuesta a revisar:\n{response}"
                ),
            },
        ]

        try:
            raw = self.client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": REFLECTION_TEMPERATURE},
            ).strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            data = _json.loads(raw)
            if data.get("status") == "needs_fix" and data.get("corrected_response"):
                self.state.add_trace(
                    f"Reflexión: corregida ({', '.join(data.get('issues', []))})"
                )
                return data["corrected_response"]
        except Exception:
            pass  # Reflexión fallida = usar respuesta original

        return response

    # ------------------------------------------------------------------
    # Retry inteligente de pasos de plan
    # ------------------------------------------------------------------

    def _retry_failed_step(
        self,
        step_description: str,
        tool_name: str,
        original_args: Dict[str, Any],
        error_message: str,
        attempt: int,
        conversation: Conversation,
    ) -> Optional[ToolCall]:
        """
        Genera un ToolCall alternativo para reintentar un paso fallido.

        Args:
            step_description: Qué intenta hacer el paso.
            tool_name: Herramienta que falló.
            original_args: Args originales.
            error_message: Mensaje de error.
            attempt: Número de intento (1-based).
            conversation: Conversación actual (para contexto).

        Returns:
            ToolCall alternativo o None si es imposible.
        """
        from llm.prompts import STEP_RETRY_PROMPT

        # Resultados previos como contexto
        prev_results: List[str] = []
        for msg in conversation.messages:
            if msg.role == MessageRole.SYSTEM and "Observation" in msg.content:
                prev_results.append(msg.content)

        messages = [
            {"role": "system", "content": STEP_RETRY_PROMPT},
        ]
        if prev_results:
            messages.append({
                "role": "system",
                "content": (
                    "Resultados de pasos anteriores:\n"
                    + "\n---\n".join(prev_results[-5:])
                ),
            })
        messages.append({
            "role": "user",
            "content": (
                f"Paso: {step_description}\n"
                f"Herramienta: {tool_name}\n"
                f"Args originales: {_json.dumps(original_args, ensure_ascii=False)}\n"
                f"Error: {error_message}\n"
                f"Intento: {attempt} de {MAX_STEP_RETRIES}\n\n"
                "Genera la corrección. SOLO JSON."
            ),
        })

        try:
            raw = self._call_model(messages).strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            data = _json.loads(raw)

            if data.get("strategy") == "impossible":
                self.state.add_trace(
                    f"Retry imposible: {data.get('reason', 'sin razón')}"
                )
                return None

            tool = data.get("tool", tool_name)
            args = data.get("args", {})
            if isinstance(args, dict) and tool:
                self.state.add_trace(
                    f"Retry intento {attempt}: {data.get('strategy', 'corrección')}"
                )
                return ToolCall(tool=tool, args=args)
        except Exception:
            self.state.add_trace(f"Retry intento {attempt}: no se pudo generar alternativa")

        return None

    # ------------------------------------------------------------------
    # Extracción de memorias post-respuesta
    # ------------------------------------------------------------------

    def _maybe_extract_memories(
        self,
        user_input: str,
        response_content: str,
    ) -> None:
        """Extrae memorias de la conversación si hay MemoryStore disponible."""
        if not self._memory_store:
            return

        def llm_call(messages: List[Dict[str, Any]]) -> str:
            return self.client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": 0.2},
            )

        try:
            self._memory_store.extract_memories(
                llm_call=llm_call,
                workspace_root=str(self.workspace_root),
                user_message=user_input,
                assistant_response=response_content,
            )
        except Exception:
            pass  # No romper el flujo por errores de memoria

    # ------------------------------------------------------------------
    # Modos de operación
    # ------------------------------------------------------------------

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
        
        # Reflexión crítica
        response = self._reflect_on_response(response, conversation)

        # Agregar respuesta
        conversation.add_assistant_message(response)

        # Extraer memorias en background
        self._maybe_extract_memories(user_input, response)
        
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
        cancel_check: Optional[Callable[[], bool]] = None,
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

            # Verificar cancelación antes de consultar al modelo
            if cancel_check and cancel_check():
                cancel_msg = "Cancelado por el usuario."
                self.state.add_trace(cancel_msg)
                self.state.is_running = False
                return AgentResponse(
                    content="Ejecución cancelada por el usuario.",
                    status="cancelled",
                    trace=self.state.trace,
                    tool_results=tool_results,
                    new_cwd=str(self.current_cwd),
                )

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

                # Reflexión crítica antes de entregar
                response = self._reflect_on_response(response, conversation)

                conversation.add_assistant_message(response)
                self.state.is_running = False

                # Extraer memorias
                self._maybe_extract_memories(user_input, response)
                
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
    
    # ------------------------------------------------------------------
    # Helpers para ejecución autónoma de planes
    # ------------------------------------------------------------------

    # Placeholder: {nombre} que NO esté precedido de f' o f" (para evitar falsos positivos con f-strings)
    _PLACEHOLDER_RE = _re.compile(r"\{[a-zA-Z_]\w*\}")

    @staticmethod
    def _args_have_placeholders(args: Dict[str, Any]) -> bool:
        """
        Detecta si algún arg contiene un placeholder tipo {nombre}.
        Ignora 'code' de execute_python (tiene f-strings válidos).
        """
        for key, v in args.items():
            # Saltar el código Python (tiene f-strings legítimos)
            if key == "code":
                continue
            if isinstance(v, str) and Agent._PLACEHOLDER_RE.search(v):
                return True
        return False

    def _needs_arg_resolution(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """
        Decide si los args de un paso necesitan resolución dinámica.
        """
        if not args or self._args_have_placeholders(args):
            return True
        # write_file con content vacío
        if tool_name == "write_file":
            content = args.get("content", "")
            if not content or not content.strip():
                return True
        # read_file con path vacío o ausente
        if tool_name == "read_file":
            path = args.get("path", "")
            if not path or not path.strip():
                return True
        # execute_python: no resolver (el código ya es autocontenido)
        if tool_name == "execute_python":
            code = args.get("code", "")
            if not code or not code.strip():
                return True
            return False
        # Validar que los args requeridos estén presentes
        test_call = ToolCall(tool=tool_name, args=args)
        if self.tool_registry.validate_tool_call(test_call) is not None:
            return True
        return False

    def _resolve_step_args(
        self,
        step_id: int,
        step_description: str,
        tool_name: str,
        raw_args: Dict[str, Any],
        conversation: Conversation,
    ) -> Dict[str, Any]:
        """
        Llama al LLM para resolver los args del paso usando resultados
        reales de pasos anteriores ya presentes en la conversación.
        Hace fallback a raw_args si falla.
        """
        # Recopilar resultados de pasos anteriores como contexto explícito
        prev_results: List[str] = []
        for msg in conversation.messages:
            if msg.role == MessageRole.SYSTEM and "Observation" in msg.content:
                prev_results.append(msg.content)

        system = (
            f"Estás ejecutando el paso {step_id} de un plan.\n"
            f"Genera los argumentos EXACTOS para la herramienta `{tool_name}`.\n"
            "USA los valores REALES que aparecen en los resultados anteriores.\n"
            "Por ejemplo, si un paso anterior creó 'AAAAAAAA_20260411.log', usa ESE nombre exacto.\n"
            "Responde SOLO un objeto JSON válido. Sin texto, sin markdown."
        )
        messages = [{"role": "system", "content": system}]
        # Inyectar resultados anteriores como contexto directo
        if prev_results:
            messages.append({
                "role": "system",
                "content": "Resultados de pasos anteriores:\n" + "\n---\n".join(prev_results[-5:]),
            })
        messages.append({
            "role": "user",
            "content": (
                f"Paso: {step_description}\n"
                f"Herramienta: {tool_name}\n"
                f"Args originales: {_json.dumps(raw_args, ensure_ascii=False)}\n\n"
                "Genera los args con valores reales extraídos de los resultados anteriores. SOLO JSON."
            ),
        })
        try:
            raw = self._call_model(messages).strip()
            # Quitar bloque de código markdown si el modelo lo envuelve
            if raw.startswith("```"):
                lines = raw.splitlines()
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            resolved = _json.loads(raw)
            if isinstance(resolved, dict):
                self.state.add_trace(
                    f"Args del paso {step_id} resueltos dinámicamente"
                )
                return resolved
        except Exception:
            pass
        return raw_args

    def _try_fix_python_code(self, code: str) -> str:
        """
        Valida código Python con ast.parse().
        Si tiene SyntaxError, pide al LLM que lo corrija.
        Retorna el código corregido o el original si falla.
        """
        try:
            _ast.parse(code)
            return code
        except SyntaxError as exc:
            self.state.add_trace(
                f"Código Python tiene SyntaxError: {exc.msg} (línea {exc.lineno}), intentando reparar"
            )

        repair_prompt = (
            "El siguiente código Python tiene un error de sintaxis. "
            "Corrígelo y devuelve SOLO el código Python corregido. "
            "Sin explicaciones, sin markdown, sin bloques de código. Solo el código puro."
        )
        messages = [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": code},
        ]
        try:
            fixed = self._call_model(messages).strip()
            # Quitar markdown si el modelo lo envuelve
            if fixed.startswith("```"):
                lines = fixed.splitlines()
                fixed = "\n".join(lines[1:-1]) if len(lines) > 2 else fixed
            _ast.parse(fixed)
            self.state.add_trace("Código Python reparado exitosamente")
            return fixed
        except Exception:
            pass
        return code

    def execute_plan_step(
        self,
        plan: Plan,
        conversation: Conversation,
        auto_execute: bool = False,
        step_callback: Optional[Callable[[str, dict], None]] = None,
    ) -> AgentResponse:
        """
        Ejecuta el siguiente paso de un plan.

        Args:
            plan: Plan a ejecutar
            conversation: Conversación actual
            auto_execute: Si es True, omite las aprobaciones por paso y
                          ejecuta el plan completo de forma autónoma.
            step_callback: Función opcional llamada después de cada paso con
                           (descripción, plan_dict). Útil para streaming via WS.

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

        # Si requiere aprobación Y no estamos en modo auto_execute
        if current_step.requires_approval and not auto_execute:
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
        # Normalizar tool: None, "none", "null", "" se tratan como paso sin herramienta
        effective_tool = current_step.tool
        if effective_tool and effective_tool.lower() in ("none", "null", ""):
            effective_tool = None

        if effective_tool:
            # Resolver args dinámicamente cuando sea necesario (solo en auto_execute)
            resolved_args = current_step.args
            if auto_execute and self._needs_arg_resolution(effective_tool, current_step.args):
                resolved_args = self._resolve_step_args(
                    step_id=current_step.id,
                    step_description=current_step.description,
                    tool_name=effective_tool,
                    raw_args=current_step.args,
                    conversation=conversation,
                )

            # Validar y reparar código Python antes de ejecutar
            if effective_tool == "execute_python" and "code" in resolved_args:
                resolved_args["code"] = self._try_fix_python_code(
                    resolved_args["code"]
                )

            tool_call = ToolCall(
                tool=effective_tool,
                args=resolved_args,
            )
            result = self.tool_registry.execute(tool_call)
            current_step.result = result

            if result.new_cwd:
                self.set_cwd(Path(result.new_cwd))

            if result.success:
                current_step.status = StepStatus.COMPLETED
                self.state.add_trace(f"Paso {current_step.id} completado")
            else:
                # --- Retry inteligente ---
                retry_success = False
                if auto_execute:
                    for attempt in range(1, MAX_STEP_RETRIES + 1):
                        self.state.add_trace(
                            f"Paso {current_step.id} falló: {result.error} "
                            f"(reintentando {attempt}/{MAX_STEP_RETRIES})"
                        )
                        if step_callback:
                            step_callback(
                                f"Reintentando paso {current_step.id} "
                                f"({attempt}/{MAX_STEP_RETRIES})",
                                plan.to_dict(),
                            )

                        retry_call = self._retry_failed_step(
                            step_description=current_step.description,
                            tool_name=effective_tool,
                            original_args=resolved_args,
                            error_message=result.error or result.output,
                            attempt=attempt,
                            conversation=conversation,
                        )
                        if not retry_call:
                            break

                        # Validar Python si aplica
                        if (
                            retry_call.tool == "execute_python"
                            and "code" in retry_call.args
                        ):
                            retry_call.args["code"] = self._try_fix_python_code(
                                retry_call.args["code"]
                            )

                        result = self.tool_registry.execute(retry_call)
                        current_step.result = result
                        if result.new_cwd:
                            self.set_cwd(Path(result.new_cwd))
                        if result.success:
                            current_step.status = StepStatus.COMPLETED
                            self.state.add_trace(
                                f"Paso {current_step.id} completado tras reintento {attempt}"
                            )
                            retry_success = True
                            break
                        # Actualizar args para el próximo intento
                        resolved_args = retry_call.args

                if not retry_success:
                    current_step.status = StepStatus.FAILED
                    current_step.error_message = result.error
                    self.state.add_trace(
                        f"Paso {current_step.id} falló definitivamente: {result.error}"
                    )

            # Inyectar resultado en la conversación para que pasos
            # posteriores puedan referenciarlo al resolver sus args
            observation = PromptManager.build_tool_result_context(
                step=current_step.id,
                tool_call=str(tool_call),
                result=result.output if result.success else f"Error: {result.error}",
            )
            conversation.add_system_message(observation)
        else:
            # Paso sin tool (solo descripción)
            current_step.status = StepStatus.COMPLETED

        # Notificar progreso al caller (usado para streaming por WS)
        if step_callback:
            step_callback(current_step.description, plan.to_dict())

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
        return self.execute_plan_step(plan, conversation, auto_execute, step_callback)
