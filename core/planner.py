"""Gestor de planes para el modo Plan."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import MAX_PLAN_STEPS, OperationMode
from core.models import (
    Conversation,
    Plan,
    PlanStatus,
    PlanStep,
    StepStatus,
)
from llm.client import OllamaClient, OllamaClientError
from llm.prompts import PromptManager


# Patrón para extraer JSON de plan
PLAN_JSON_PATTERN = re.compile(
    r'\{[^{}]*"action"\s*:\s*"create_plan"[^{}]*"plan"\s*:\s*(\{.*?\})\s*\}',
    re.IGNORECASE | re.DOTALL,
)

# Patrones de expresiones inválidas que algunos modelos insertan en los args
# Elimina: "valor" + cualquier_expresion(...)   →  "valor"
# El lookahead asegura que no se toca JSON válido
_INVALID_EXPR_RE = re.compile(
    r'(")\s*\+\s*.+?(?=\s*[,}\]])',
    re.DOTALL,
)
_TRAILING_COMMA_RE = re.compile(r',\s*([}\]])')


class PlanManager:
    """
    Gestor de planes para el modo Plan.
    
    Maneja la creación, edición y ejecución de planes.
    """
    
    def __init__(self, client: OllamaClient, model: str, temperature: float = 0.7):
        """
        Inicializa el gestor de planes.
        
        Args:
            client: Cliente de Ollama
            model: Nombre del modelo
            temperature: Temperatura para generación
        """
        self.client = client
        self.model = model
        self.temperature = temperature
        self._current_plan: Optional[Plan] = None
        self._plan_history: List[Plan] = []
    
    @property
    def current_plan(self) -> Optional[Plan]:
        """Retorna el plan actual."""
        return self._current_plan
    
    @property
    def has_active_plan(self) -> bool:
        """Indica si hay un plan activo."""
        return (
            self._current_plan is not None
            and self._current_plan.status not in (
                PlanStatus.COMPLETED,
                PlanStatus.CANCELLED,
                PlanStatus.FAILED,
            )
        )
    
    def _call_model(self, messages: List[Dict[str, Any]]) -> str:
        """Llama al modelo forzando JSON (el plan siempre es un objeto JSON)."""
        return self.client.chat(
            model=self.model,
            messages=messages,
            options={"temperature": self.temperature},
            fmt="json",
        )
    
    @staticmethod
    def _sanitize_json_str(raw: str) -> str:
        """
        Limpia patrones inválidos que algunos modelos insertan en el JSON:
        - Expresiones de concatenación: "..." + func(...)  →  ""
        - Comas finales antes de } o ]
        """
        cleaned = _INVALID_EXPR_RE.sub('"', raw)
        cleaned = _TRAILING_COMMA_RE.sub(r'\1', cleaned)
        return cleaned

    @staticmethod
    def _try_parse(text: str) -> Optional[Dict[str, Any]]:
        """Intenta parsear JSON, con fallback tras sanitizar."""
        for candidate in (text, PlanManager._sanitize_json_str(text)):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
        return None

    def _extract_plan_from_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Extrae un plan del texto de respuesta."""
        # 1. Extraer bloque ```json ... ``` si existe
        md_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL | re.IGNORECASE)
        if md_match:
            data = self._try_parse(md_match.group(1))
            if data and ("plan" in data or data.get("action") == "create_plan"):
                return data

        # 2. Intentar parsear la respuesta completa como JSON
        data = self._try_parse(response.strip())
        if data and ("plan" in data or data.get("action") == "create_plan"):
            return data

        # 3. Buscar JSON embebido con raw_decode
        decoder = json.JSONDecoder()
        for i, char in enumerate(response):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(response[i:])
                if isinstance(parsed, dict):
                    if "action" in parsed and parsed.get("action") == "create_plan":
                        return parsed
                    if "plan" in parsed:
                        return parsed
            except json.JSONDecodeError:
                # Intentar con sanitización
                try:
                    sanitized = self._sanitize_json_str(response[i:])
                    parsed, _ = decoder.raw_decode(sanitized)
                    if isinstance(parsed, dict) and (
                        ("action" in parsed and parsed.get("action") == "create_plan")
                        or "plan" in parsed
                    ):
                        return parsed
                except json.JSONDecodeError:
                    pass

        return None
    
    def create_plan(
        self,
        user_request: str,
        conversation: Conversation,
        context: Optional[str] = None,
    ) -> Optional[Plan]:
        """
        Crea un plan basado en la solicitud del usuario.
        
        Args:
            user_request: Solicitud del usuario
            conversation: Conversación actual
            context: Contexto adicional
            
        Returns:
            Plan creado o None si no se pudo crear
        """
        # Construir mensajes
        system_prompt = PromptManager.get_system_prompt(OperationMode.PLAN)
        messages = [{"role": "system", "content": system_prompt}]
        
        # Agregar contexto si existe
        if context:
            messages.append({"role": "system", "content": context})
        
        # Agregar historial relevante
        for msg in conversation.messages[-10:]:
            messages.append(msg.to_ollama_format())
        
        # Agregar la solicitud
        messages.append({
            "role": "user",
            "content": f"Crea un plan para: {user_request}",
        })
        
        try:
            response = self._call_model(messages)
        except OllamaClientError:
            return None
        
        # Extraer plan
        plan_data = self._extract_plan_from_response(response)
        if not plan_data:
            return None
        
        plan_content = plan_data.get("plan", plan_data)
        
        # Construir el plan
        steps = []
        for i, step_data in enumerate(plan_content.get("steps", [])[:MAX_PLAN_STEPS], 1):
            # Normalizar args: null/None -> {}
            step_args = step_data.get("args")
            if step_args is None:
                step_args = {}
            # Normalizar tool: "none"/"null" -> None
            step_tool = step_data.get("tool")
            if isinstance(step_tool, str) and step_tool.lower() in ("none", "null", ""):
                step_tool = None
            step = PlanStep(
                id=step_data.get("id", i),
                description=step_data.get("description", f"Paso {i}"),
                tool=step_tool,
                args=step_args,
                requires_approval=step_data.get("requires_approval", False),
            )
            steps.append(step)
        
        plan = Plan(
            title=plan_content.get("title", "Plan de ejecución"),
            description=plan_content.get("description", ""),
            steps=steps,
            context=user_request,
            status=PlanStatus.DRAFT,
        )
        
        self._current_plan = plan
        return plan
    
    def approve_plan(self) -> bool:
        """Aprueba el plan actual."""
        if not self._current_plan:
            return False
        
        if self._current_plan.status != PlanStatus.DRAFT:
            return False
        
        self._current_plan.status = PlanStatus.APPROVED
        self._current_plan.updated_at = datetime.now()
        return True
    
    def cancel_plan(self) -> bool:
        """Cancela el plan actual."""
        if not self._current_plan:
            return False
        
        self._current_plan.status = PlanStatus.CANCELLED
        self._current_plan.updated_at = datetime.now()
        self._plan_history.append(self._current_plan)
        self._current_plan = None
        return True
    
    def update_step(
        self,
        step_id: int,
        description: Optional[str] = None,
        tool: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        requires_approval: Optional[bool] = None,
    ) -> bool:
        """
        Actualiza un paso del plan.
        
        Args:
            step_id: ID del paso
            description: Nueva descripción
            tool: Nueva herramienta
            args: Nuevos argumentos
            requires_approval: Si requiere aprobación
            
        Returns:
            True si se actualizó correctamente
        """
        if not self._current_plan:
            return False
        
        for step in self._current_plan.steps:
            if step.id == step_id:
                if description is not None:
                    step.description = description
                if tool is not None:
                    step.tool = tool
                if args is not None:
                    step.args = args
                if requires_approval is not None:
                    step.requires_approval = requires_approval
                
                self._current_plan.updated_at = datetime.now()
                return True
        
        return False
    
    def add_step(
        self,
        description: str,
        tool: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        requires_approval: bool = False,
        after_step_id: Optional[int] = None,
    ) -> Optional[PlanStep]:
        """
        Agrega un paso al plan.
        
        Args:
            description: Descripción del paso
            tool: Herramienta a usar
            args: Argumentos de la herramienta
            requires_approval: Si requiere aprobación
            after_step_id: ID del paso después del cual insertar
            
        Returns:
            El paso creado o None
        """
        if not self._current_plan:
            return None
        
        if len(self._current_plan.steps) >= MAX_PLAN_STEPS:
            return None
        
        # Calcular nuevo ID
        max_id = max((s.id for s in self._current_plan.steps), default=0)
        new_step = PlanStep(
            id=max_id + 1,
            description=description,
            tool=tool,
            args=args or {},
            requires_approval=requires_approval,
        )
        
        if after_step_id is None:
            self._current_plan.steps.append(new_step)
        else:
            for i, step in enumerate(self._current_plan.steps):
                if step.id == after_step_id:
                    self._current_plan.steps.insert(i + 1, new_step)
                    break
            else:
                self._current_plan.steps.append(new_step)
        
        self._current_plan.updated_at = datetime.now()
        return new_step
    
    def remove_step(self, step_id: int) -> bool:
        """
        Elimina un paso del plan.
        
        Args:
            step_id: ID del paso a eliminar
            
        Returns:
            True si se eliminó correctamente
        """
        if not self._current_plan:
            return False
        
        for i, step in enumerate(self._current_plan.steps):
            if step.id == step_id:
                if step.status not in (StepStatus.PENDING, StepStatus.AWAITING_APPROVAL):
                    return False  # No eliminar pasos ya ejecutados
                
                self._current_plan.steps.pop(i)
                self._current_plan.updated_at = datetime.now()
                return True
        
        return False
    
    def complete_plan(self) -> None:
        """Marca el plan como completado."""
        if self._current_plan:
            self._current_plan.status = PlanStatus.COMPLETED
            self._current_plan.updated_at = datetime.now()
            self._plan_history.append(self._current_plan)
            self._current_plan = None
    
    def fail_plan(self, error: str) -> None:
        """Marca el plan como fallido."""
        if self._current_plan:
            self._current_plan.status = PlanStatus.FAILED
            self._current_plan.updated_at = datetime.now()
            self._plan_history.append(self._current_plan)
            self._current_plan = None
    
    def get_plan_history(self) -> List[Plan]:
        """Retorna el historial de planes."""
        return list(self._plan_history)
    
    def clear_history(self) -> None:
        """Limpia el historial de planes."""
        self._plan_history.clear()
