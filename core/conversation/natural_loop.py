"""Bucle de conversación natural: modelo → parser → tool → modelo.

Responsabilidad única: orquestar el ciclo en el que el modelo principal
responde en texto libre, un parser detecta si hay tool call, y la tool se
ejecuta hasta que el modelo emite una respuesta final.

NO conoce detalles de:
- Aprobaciones (las consulta a través del approval_manager inyectado)
- Construcción del system prompt (la recibe ya armada)
- Reflexión / memoria (esas las maneja el orquestador externo)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_SIMULATION_RE = re.compile(
    r"simulaci[oó]n\s+de\s+la\s+ejecuci[oó]n|"
    r"simular[eé]\s+(el\s+)?comando|"
    r"como\s+si\s+hubiera\s+ejecutado|"
    r"fingir[eé]\s+ejecutar|"
    r"ejecuci[oó]n\s+simulada",
    re.IGNORECASE,
)

from config import MAX_AGENT_STEPS
from core.models import (
    AgentState,
    Conversation,
    ToolCall,
    ToolResult,
)
from llm.client import OllamaClientError
from llm.prompts import PromptManager


@dataclass
class LoopResult:
    """Resultado de un run del bucle natural."""
    status: str                       # completed | awaiting_approval | cancelled | error | max_steps
    final_response: str = ""          # respuesta final al usuario (solo si completed)
    tool_results: List[ToolResult] = field(default_factory=list)
    error: Optional[str] = None
    pending_tool_call: Optional[ToolCall] = None  # solo si awaiting_approval


class NaturalConversationLoop:
    """Bucle natural-language → parser → tool → modelo."""

    def __init__(
        self,
        llm_call: Callable[[List[Dict[str, Any]], Optional[str]], str],
        build_messages: Callable[[Conversation, Optional[str]], List[Dict[str, Any]]],
        parse_response: Callable[[str], Dict[str, Any]],
        validate_tool_call: Callable[[ToolCall], Optional[str]],
        is_write_operation: Callable[[ToolCall], bool],
        requires_approval: Callable[[ToolCall, bool], bool],
        execute_tool: Callable[[ToolCall], ToolResult],
        on_cwd_change: Callable[[Path], None],
        state: AgentState,
    ) -> None:
        self._llm_call = llm_call
        self._build_messages = build_messages
        self._parse_response = parse_response
        self._validate_tool_call = validate_tool_call
        self._is_write_operation = is_write_operation
        self._requires_approval = requires_approval
        self._execute_tool = execute_tool
        self._on_cwd_change = on_cwd_change
        self._state = state

    def run(
        self,
        conversation: Conversation,
        system_prompt: str,
        step_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_steps: Optional[int] = None,
    ) -> LoopResult:
        """Ejecuta el bucle natural y retorna el resultado.

        Args:
            conversation: conversación con el mensaje del usuario ya añadido.
            system_prompt: system prompt completo (con workspace embebido).
            step_callback: notificación opcional de cada paso.
            cancel_check: función que indica si se solicitó cancelación.
            max_steps: límite de pasos; si None usa MAX_AGENT_STEPS del config.
        """
        limit = max_steps if max_steps is not None else MAX_AGENT_STEPS
        tool_results: List[ToolResult] = []
        # Respuestas intermedias del asistente (solo durante este run, no se
        # persisten — son razonamiento intermedio que el usuario no necesita ver).
        # Los tool results SÍ se persisten en conversation para que el modelo
        # recuerde en turnos futuros qué leyó/ejecutó.
        extra_messages: List[Dict[str, Any]] = []
        consecutive_empty = 0

        for step in range(1, limit + 1):
            self._state.step_count = step

            if cancel_check and cancel_check():
                return LoopResult(
                    status="cancelled",
                    final_response="Ejecución cancelada por el usuario.",
                    tool_results=tool_results,
                )

            self._notify(f"Paso {step}: consultando al modelo", step_callback)

            messages = self._build_messages(conversation, system_prompt)
            messages.extend(extra_messages)

            try:
                response_text = self._llm_call(messages, None)  # sin fmt="json"
            except OllamaClientError as exc:
                return LoopResult(
                    status="error",
                    error=str(exc),
                    tool_results=tool_results,
                )

            if not response_text.strip():
                consecutive_empty += 1
                self._state.add_trace(f"Paso {step}: respuesta vacía ({consecutive_empty}/3)")
                if consecutive_empty >= 3:
                    summary = (
                        "Las herramientas se ejecutaron correctamente."
                        if tool_results
                        else "Sin resultado."
                    )
                    return LoopResult(
                        status="completed",
                        final_response=summary,
                        tool_results=tool_results,
                    )
                continue

            consecutive_empty = 0

            # Detectar simulación explícita — el modelo finge ejecutar en lugar de
            # llamar a una tool. Inyectar corrección y continuar el loop.
            if _SIMULATION_RE.search(response_text):
                self._state.add_trace(
                    f"Paso {step}: respuesta de simulación detectada — corrigiendo"
                )
                extra_messages.append({"role": "assistant", "content": response_text})
                extra_messages.append({
                    "role": "system",
                    "content": (
                        "CORRECCIÓN: No puedes simular ni inventar resultados de herramientas. "
                        "Si necesitas ejecutar un comando real, usa run_command() ahora mismo. "
                        "Anuncia el comando con el formato: "
                        "\"Voy a ejecutar el comando: `<comando>`\" y nada más."
                    ),
                })
                continue

            self._state.add_trace(f"Paso {step}: analizando respuesta con parser")
            parsed = self._parse_response(response_text)

            # Sin tool → respuesta final
            if not parsed.get("needs_tool"):
                return LoopResult(
                    status="completed",
                    final_response=response_text,
                    tool_results=tool_results,
                )

            tool_name = parsed.get("tool", "")
            tool_args = parsed.get("args", {})

            if not tool_name:
                # Parser inconsistente: needs_tool=true sin nombre → tratar como final
                return LoopResult(
                    status="completed",
                    final_response=response_text,
                    tool_results=tool_results,
                )

            tool_call = ToolCall(
                tool=tool_name,
                args=tool_args if isinstance(tool_args, dict) else {},
            )

            # Validación
            validation_error = self._validate_tool_call(tool_call)
            if validation_error:
                self._state.add_trace(f"Paso {step}: tool inválida - {validation_error}")
                extra_messages.append({"role": "assistant", "content": response_text})
                extra_messages.append({
                    "role": "system",
                    "content": (
                        f"La tool '{tool_name}' no pudo ejecutarse: {validation_error}. "
                        "Continúa sin ella."
                    ),
                })
                continue

            # Aprobación
            is_write = self._is_write_operation(tool_call)
            if self._requires_approval(tool_call, is_write):
                # Persistir la respuesta del modelo en la conversación antes de pausar
                conversation.add_assistant_message(response_text)
                return LoopResult(
                    status="awaiting_approval",
                    final_response=f"Se requiere aprobación para: `{tool_call}`",
                    tool_results=tool_results,
                    pending_tool_call=tool_call,
                )

            # Ejecución
            cmd_preview = tool_args.get("command", "") if tool_name == "run_command" else ""
            if cmd_preview:
                self._notify({
                    "kind": "exec",
                    "message": f"Ejecutando: {tool_name}",
                    "command": cmd_preview,
                }, step_callback)
            else:
                self._notify(f"Paso {step}: ejecutando {tool_call.tool}", step_callback)
            result = self._execute_tool(tool_call)
            tool_results.append(result)

            if result.new_cwd:
                self._on_cwd_change(Path(result.new_cwd))

            # Notificar resultado de la tool al frontend
            self._notify({
                "kind": "tool_result",
                "tool": tool_call.tool,
                "success": result.success,
                "output": (result.output or "")[:2000],
            }, step_callback)

            # Razonamiento intermedio del asistente: solo en este run
            extra_messages.append({"role": "assistant", "content": response_text})
            # Tool result: PERSISTENTE en conversation para que el modelo
            # recuerde en turnos futuros qué leyó/ejecutó/encontró.
            tool_result_text = PromptManager.build_tool_result_context(
                step=step,
                tool_call=str(tool_call),
                result=result.output if result.success else f"Error: {result.error}",
            )
            conversation.add_system_message(tool_result_text)
            # Nudge: indicar al modelo que decida si la tarea está completa.
            extra_messages.append({
                "role": "system",
                "content": (
                    "La herramienta se ejecutó correctamente. "
                    "Si la tarea del usuario ya está resuelta, responde en UNA sola frase "
                    "confirmando qué hiciste (ej: 'Listo, creé el archivo X con Y.'). "
                    "NO muestres el contenido del archivo ni bloques de código — solo confirma. "
                    "Solo usa otra herramienta si falta algo concreto para completar la tarea."
                ),
            })

        return LoopResult(
            status="max_steps",
            final_response=f"Se alcanzó el límite de {limit} pasos.",
            tool_results=tool_results,
        )

    def _notify(
        self,
        message,
        step_callback,
    ) -> None:
        """Registra el evento en el trace y notifica al callback si existe."""
        trace_text = message if isinstance(message, str) else message.get("message", str(message))
        self._state.add_trace(trace_text)
        if step_callback:
            step_callback(message)
