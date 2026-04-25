"""Ejecución autónoma de planes con retry, resolución de args y reparación de código.

Responsabilidad única: dado un Plan, ejecutar sus pasos en orden, manejando:
  - Aprobaciones cuando aplica
  - Resolución dinámica de args (placeholders, valores faltantes)
  - Reparación automática de código Python con SyntaxError
  - Retry inteligente cuando un paso falla

NO conoce detalles de:
- Construcción del system prompt (recibe el LLM call directo)
- Conversación natural / parser (este es el modo PLAN, separado)
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import MAX_STEP_RETRIES
from core.models import (
    AgentState,
    Conversation,
    MessageRole,
    Plan,
    PlanStatus,
    StepStatus,
    ToolCall,
)
from llm.prompts import PromptManager, STEP_RETRY_PROMPT


# Placeholder: {nombre} que NO esté precedido de f' o f" (evita falsos positivos con f-strings)
_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_]\w*\}")


class PlanExecutor:
    """Ejecuta los pasos de un Plan con retry, resolución de args y validación."""

    def __init__(
        self,
        llm_call: Callable[[List[Dict[str, Any]], Optional[str]], str],
        tool_registry: Any,
        approval_manager: Any,
        state: AgentState,
        on_cwd_change: Callable[[Path], None],
    ) -> None:
        self._llm_call = llm_call
        self._tool_registry = tool_registry
        self._approval_manager = approval_manager
        self._state = state
        self._on_cwd_change = on_cwd_change

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    def execute(
        self,
        plan: Plan,
        conversation: Conversation,
        auto_execute: bool = False,
        step_callback: Optional[Callable[[str, dict], None]] = None,
    ) -> "PlanExecutionResult":
        """Ejecuta el siguiente paso del plan (recursivo hasta completar).

        Returns:
            PlanExecutionResult con status, content, plan, y trace.
        """
        current_step = plan.current_step
        if not current_step:
            plan.status = PlanStatus.COMPLETED
            return PlanExecutionResult(
                status="completed",
                content="Plan completado.",
                plan=plan,
            )

        current_step.status = StepStatus.IN_PROGRESS
        plan.status = PlanStatus.IN_PROGRESS
        self._state.add_trace(
            f"Ejecutando paso {current_step.id}: {current_step.description}"
        )

        # Aprobación (solo si no estamos en auto_execute)
        if current_step.requires_approval and not auto_execute and current_step.tool:
            tool_call = ToolCall(tool=current_step.tool, args=current_step.args)
            self._approval_manager.request_approval(tool_call)
            current_step.status = StepStatus.AWAITING_APPROVAL
            return PlanExecutionResult(
                status="awaiting_approval",
                content=(
                    f"Paso {current_step.id} requiere aprobación: "
                    f"{current_step.description}"
                ),
                plan=plan,
            )

        # Normalizar tool: None, "none", "null", "" → sin herramienta
        effective_tool = current_step.tool
        if effective_tool and effective_tool.lower() in ("none", "null", ""):
            effective_tool = None

        if effective_tool:
            self._execute_step_with_tool(
                current_step, effective_tool, plan, conversation,
                auto_execute, step_callback,
            )
        else:
            current_step.status = StepStatus.COMPLETED

        if step_callback:
            step_callback(current_step.description, plan.to_dict())

        if plan.is_complete:
            plan.status = PlanStatus.COMPLETED
            return PlanExecutionResult(
                status="completed",
                content="Plan completado exitosamente.",
                plan=plan,
            )

        # Continuar con el siguiente paso
        return self.execute(plan, conversation, auto_execute, step_callback)

    # ------------------------------------------------------------------
    # Ejecución de un paso individual con tool
    # ------------------------------------------------------------------

    def _execute_step_with_tool(
        self,
        current_step,
        effective_tool: str,
        plan: Plan,
        conversation: Conversation,
        auto_execute: bool,
        step_callback: Optional[Callable[[str, dict], None]],
    ) -> None:
        """Ejecuta el paso actual con tool, incluyendo retry si falla."""
        # Resolver args dinámicamente cuando aplica (solo en auto_execute)
        resolved_args = current_step.args
        if auto_execute and self._needs_arg_resolution(effective_tool, current_step.args):
            resolved_args = self._resolve_step_args(
                step_id=current_step.id,
                step_description=current_step.description,
                tool_name=effective_tool,
                raw_args=current_step.args,
                conversation=conversation,
            )

        # Reparar código Python si aplica
        if effective_tool == "execute_python" and "code" in resolved_args:
            resolved_args["code"] = self._try_fix_python_code(resolved_args["code"])

        tool_call = ToolCall(tool=effective_tool, args=resolved_args)
        result = self._tool_registry.execute(tool_call)
        current_step.result = result

        if result.new_cwd:
            self._on_cwd_change(Path(result.new_cwd))

        if result.success:
            current_step.status = StepStatus.COMPLETED
            self._state.add_trace(f"Paso {current_step.id} completado")
        else:
            # Retry inteligente solo en auto_execute
            retry_success = False
            if auto_execute:
                retry_success = self._retry_step(
                    current_step, effective_tool, resolved_args,
                    plan, conversation, step_callback,
                )

            if not retry_success:
                current_step.status = StepStatus.FAILED
                current_step.error_message = result.error
                self._state.add_trace(
                    f"Paso {current_step.id} falló definitivamente: {result.error}"
                )

        # Persistir observación para que pasos posteriores la vean
        observation = PromptManager.build_tool_result_context(
            step=current_step.id,
            tool_call=str(tool_call),
            result=(
                current_step.result.output
                if current_step.result.success
                else f"Error: {current_step.result.error}"
            ),
        )
        conversation.add_system_message(observation)

    def _retry_step(
        self,
        current_step,
        effective_tool: str,
        resolved_args: Dict[str, Any],
        plan: Plan,
        conversation: Conversation,
        step_callback: Optional[Callable[[str, dict], None]],
    ) -> bool:
        """Intenta reintentar un paso fallido. Retorna True si tuvo éxito."""
        result = current_step.result
        for attempt in range(1, MAX_STEP_RETRIES + 1):
            self._state.add_trace(
                f"Paso {current_step.id} falló: {result.error} "
                f"(reintentando {attempt}/{MAX_STEP_RETRIES})"
            )
            if step_callback:
                step_callback(
                    f"Reintentando paso {current_step.id} ({attempt}/{MAX_STEP_RETRIES})",
                    plan.to_dict(),
                )

            retry_call = self._build_retry_call(
                step_description=current_step.description,
                tool_name=effective_tool,
                original_args=resolved_args,
                error_message=result.error or result.output,
                attempt=attempt,
                conversation=conversation,
            )
            if not retry_call:
                return False

            if retry_call.tool == "execute_python" and "code" in retry_call.args:
                retry_call.args["code"] = self._try_fix_python_code(retry_call.args["code"])

            result = self._tool_registry.execute(retry_call)
            current_step.result = result
            if result.new_cwd:
                self._on_cwd_change(Path(result.new_cwd))
            if result.success:
                current_step.status = StepStatus.COMPLETED
                self._state.add_trace(
                    f"Paso {current_step.id} completado tras reintento {attempt}"
                )
                return True
            resolved_args = retry_call.args

        return False

    # ------------------------------------------------------------------
    # Resolución de args dinámicos
    # ------------------------------------------------------------------

    def _needs_arg_resolution(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Decide si los args de un paso necesitan resolución dinámica via LLM."""
        if not args or self._args_have_placeholders(args):
            return True
        if tool_name == "write_file":
            content = args.get("content", "")
            if not content or not content.strip():
                return True
        if tool_name == "read_file":
            path = args.get("path", "")
            if not path or not path.strip():
                return True
        if tool_name == "execute_python":
            code = args.get("code", "")
            if not code or not code.strip():
                return True
            return False
        # Validar que los args requeridos estén presentes
        test_call = ToolCall(tool=tool_name, args=args)
        if self._tool_registry.validate_tool_call(test_call) is not None:
            return True
        return False

    @staticmethod
    def _args_have_placeholders(args: Dict[str, Any]) -> bool:
        """Detecta placeholders {nombre} en los args (excepto en 'code')."""
        for key, v in args.items():
            if key == "code":
                continue  # f-strings legítimos
            if isinstance(v, str) and _PLACEHOLDER_RE.search(v):
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
        """Pide al LLM que resuelva los args usando los resultados anteriores."""
        prev_results = self._collect_observations(conversation)

        system = (
            f"Estás ejecutando el paso {step_id} de un plan.\n"
            f"Genera los argumentos EXACTOS para la herramienta `{tool_name}`.\n"
            "USA los valores REALES que aparecen en los resultados anteriores.\n"
            "Por ejemplo, si un paso anterior creó 'AAAAAAAA_20260411.log', usa ESE nombre exacto.\n"
            "Responde SOLO un objeto JSON válido. Sin texto, sin markdown."
        )
        messages = [{"role": "system", "content": system}]
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
                f"Args originales: {json.dumps(raw_args, ensure_ascii=False)}\n\n"
                "Genera los args con valores reales extraídos de los resultados anteriores. SOLO JSON."
            ),
        })
        try:
            raw = self._llm_call(messages, "json").strip()
            raw = self._strip_markdown(raw)
            resolved = json.loads(raw)
            if isinstance(resolved, dict):
                self._state.add_trace(f"Args del paso {step_id} resueltos dinámicamente")
                return resolved
        except Exception:
            pass
        return raw_args

    # ------------------------------------------------------------------
    # Retry alternativo con LLM
    # ------------------------------------------------------------------

    def _build_retry_call(
        self,
        step_description: str,
        tool_name: str,
        original_args: Dict[str, Any],
        error_message: str,
        attempt: int,
        conversation: Conversation,
    ) -> Optional[ToolCall]:
        """Genera un ToolCall alternativo via LLM cuando un paso falla."""
        prev_results = self._collect_observations(conversation)

        messages = [{"role": "system", "content": STEP_RETRY_PROMPT}]
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
                f"Args originales: {json.dumps(original_args, ensure_ascii=False)}\n"
                f"Error: {error_message}\n"
                f"Intento: {attempt} de {MAX_STEP_RETRIES}\n\n"
                "Genera la corrección. SOLO JSON."
            ),
        })

        try:
            raw = self._llm_call(messages, "json").strip()
            raw = self._strip_markdown(raw)
            data = json.loads(raw)

            if data.get("strategy") == "impossible":
                self._state.add_trace(
                    f"Retry imposible: {data.get('reason', 'sin razón')}"
                )
                return None

            tool = data.get("tool", tool_name)
            args = data.get("args", {})
            if isinstance(args, dict) and tool:
                self._state.add_trace(
                    f"Retry intento {attempt}: {data.get('strategy', 'corrección')}"
                )
                return ToolCall(tool=tool, args=args)
        except Exception:
            self._state.add_trace(f"Retry intento {attempt}: no se pudo generar alternativa")

        return None

    # ------------------------------------------------------------------
    # Reparación de código Python
    # ------------------------------------------------------------------

    def _try_fix_python_code(self, code: str) -> str:
        """Valida con ast.parse() y pide al LLM que corrija si hay SyntaxError."""
        try:
            ast.parse(code)
            return code
        except SyntaxError as exc:
            self._state.add_trace(
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
            fixed = self._llm_call(messages, None).strip()
            fixed = self._strip_markdown(fixed)
            ast.parse(fixed)
            self._state.add_trace("Código Python reparado exitosamente")
            return fixed
        except Exception:
            pass
        return code

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_observations(conversation: Conversation) -> List[str]:
        """Extrae las observaciones (resultados de tools) del historial."""
        return [
            msg.content
            for msg in conversation.messages
            if msg.role == MessageRole.SYSTEM and "Observation" in msg.content
        ]

    @staticmethod
    def _strip_markdown(raw: str) -> str:
        """Quita bloques ```...``` si el modelo envuelve la respuesta."""
        if raw.startswith("```"):
            lines = raw.splitlines()
            return "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return raw


from dataclasses import dataclass, field


@dataclass
class PlanExecutionResult:
    """Resultado de ejecutar un (o varios) pasos del plan."""
    status: str                # completed | awaiting_approval
    content: str = ""
    plan: Optional[Plan] = None
    trace: List[str] = field(default_factory=list)
