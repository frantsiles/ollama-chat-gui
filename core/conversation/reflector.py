"""Revisión crítica de respuestas: opcional, opt-in.

Responsabilidad única: dada una respuesta candidata, llamar al LLM como revisor
crítico y devolver una versión corregida si detecta problemas. Si el revisor
falla por cualquier motivo, devuelve la respuesta original.

Activación controlada por el flag REFLECTION_ENABLED en config.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from config import REFLECTION_ENABLED, REFLECTION_TEMPERATURE
from core.models import Conversation
from llm.prompts import REFLECTION_PROMPT


class ResponseReflector:
    """Revisor crítico opcional de la respuesta final."""

    def __init__(
        self,
        llm_call: Callable[[List[Dict[str, Any]], float, str], str],
        enabled: Optional[bool] = None,
    ) -> None:
        """
        Args:
            llm_call: callable(messages, temperature, fmt) → respuesta del modelo.
            enabled: override explícito del flag. Si es None usa REFLECTION_ENABLED.
        """
        self._llm_call = llm_call
        self._enabled = REFLECTION_ENABLED if enabled is None else enabled

    def review(
        self,
        response: str,
        conversation: Conversation,
        on_correction: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Revisa la respuesta. Retorna la corregida o la original.

        Args:
            response: respuesta candidata a revisar.
            conversation: conversación actual (para contexto del revisor).
            on_correction: callback opcional invocado con la descripción del
                           cambio cuando se hace una corrección.
        """
        if not self._enabled:
            return response

        messages = [
            {"role": "system", "content": REFLECTION_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Contexto de la conversación:\n{self._build_context(conversation)}\n\n"
                    f"Respuesta a revisar:\n{response}"
                ),
            },
        ]

        try:
            raw = self._llm_call(messages, REFLECTION_TEMPERATURE, "json").strip()
            raw = self._strip_markdown_fences(raw)
            data = json.loads(raw)
            if data.get("status") == "needs_fix" and data.get("corrected_response"):
                if on_correction:
                    issues = ", ".join(data.get("issues", []))
                    on_correction(f"Reflexión: corregida ({issues})")
                return data["corrected_response"]
        except Exception:
            pass  # Reflexión fallida → respuesta original

        return response

    @staticmethod
    def _build_context(conversation: Conversation) -> str:
        """Construye el contexto resumido para el revisor (últimos 4 mensajes)."""
        recent = [
            f"{m.role.value}: {m.content[:500]}"
            for m in conversation.messages[-4:]
            if m.content
        ]
        return "\n".join(recent)

    @staticmethod
    def _strip_markdown_fences(raw: str) -> str:
        """Quita bloques ```...``` si el modelo envuelve la respuesta."""
        if raw.startswith("```"):
            lines = raw.splitlines()
            return "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return raw
