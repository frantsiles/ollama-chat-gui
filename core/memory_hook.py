"""Hook de extracción de memorias post-respuesta.

Responsabilidad única: dada una interacción completa (mensaje del usuario y
respuesta del asistente), invocar al MemoryStore para extraer hechos
relevantes que valga la pena recordar en futuras sesiones.

Tolera fallos silenciosamente — la extracción de memoria nunca debe romper el
flujo principal de la conversación.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


class MemoryExtractionHook:
    """Wrapper sobre MemoryStore para extraer memorias tras una interacción."""

    def __init__(
        self,
        memory_store: Any,
        llm_call: Callable[[List[Dict[str, Any]]], str],
        workspace_root: str,
    ) -> None:
        """
        Args:
            memory_store: instancia de MemoryStore con método `extract_memories`.
            llm_call: callable(messages) → respuesta JSON del modelo.
            workspace_root: raíz del workspace (key para agrupar memorias).
        """
        self._store = memory_store
        self._llm_call = llm_call
        self._workspace_root = workspace_root

    def maybe_extract(
        self,
        user_message: str,
        assistant_response: str,
    ) -> None:
        """Intenta extraer memorias. Errores se silencian."""
        if not self._store:
            return
        try:
            self._store.extract_memories(
                llm_call=self._llm_call,
                workspace_root=self._workspace_root,
                user_message=user_message,
                assistant_response=assistant_response,
            )
        except Exception:
            pass  # nunca romper el flujo principal por la memoria

    @classmethod
    def disabled(cls) -> "MemoryExtractionHook":
        """Hook no-op (cuando no hay MemoryStore disponible)."""
        return _NullMemoryHook()


class _NullMemoryHook(MemoryExtractionHook):
    """Hook vacío: no hace nada. Útil cuando la memoria está desactivada."""

    def __init__(self) -> None:
        # Sin super().__init__ para evitar requerir args
        self._store = None

    def maybe_extract(self, user_message: str, assistant_response: str) -> None:
        return
