"""Constructor de mensajes para el LLM.

Responsabilidad única: producir la lista de mensajes que se envía al modelo en
cada llamada. Esto incluye:
  - System prompt (con memoria inyectada cuando aplica)
  - Aplicación de la ventana de contexto (truncamiento + sumario)
  - Snapshot del workspace (listado de archivos)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from config import MAX_CONTEXT_MESSAGES, MAX_CONTEXT_MESSAGES_KEEP
from core.models import Conversation, Message, MessageRole
from llm.prompts import PromptManager


class ContextBuilder:
    """Construye los mensajes para el LLM con ventana de contexto y workspace."""

    def __init__(
        self,
        mode: str,
        workspace_root: Path,
        current_cwd: Path,
        memory_context: str = "",
        context_summary: str = "",
        max_workspace_entries: int = 60,
    ) -> None:
        self._mode = mode
        self._workspace_root = workspace_root
        self._current_cwd = current_cwd
        self._memory_context = memory_context
        self._context_summary = context_summary
        self._max_entries = max_workspace_entries

    # ------------------------------------------------------------------
    # Getters / setters mutables
    # ------------------------------------------------------------------

    @property
    def context_summary(self) -> str:
        return self._context_summary

    @context_summary.setter
    def context_summary(self, value: str) -> None:
        self._context_summary = value

    @property
    def memory_context(self) -> str:
        return self._memory_context

    @memory_context.setter
    def memory_context(self, value: str) -> None:
        self._memory_context = value

    def set_cwd(self, cwd: Path) -> None:
        self._current_cwd = cwd

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    def build(
        self,
        conversation: Conversation,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Construye la lista completa de mensajes para el LLM."""
        if system_prompt is None:
            system_prompt = PromptManager.get_system_prompt_with_memory(
                self._mode, self._memory_context
            )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        for msg in self._apply_window(conversation.messages):
            messages.append(msg.to_ollama_format())
        return messages

    def build_workspace_snapshot(self) -> str:
        """Devuelve el bloque de texto con el contexto del workspace actual."""
        entries: List[str] = []
        try:
            for item in self._current_cwd.glob("*"):
                if len(entries) >= self._max_entries:
                    break
                entries.append(f"{item.name}{'/' if item.is_dir() else ''}")
        except OSError:
            pass

        return PromptManager.build_workspace_context(
            workspace_root=str(self._workspace_root),
            current_cwd=str(self._current_cwd),
            entries=sorted(entries),
        )

    def maybe_summarize(self, conversation: Conversation) -> None:
        """Actualiza el sumario si la conversación supera el umbral."""
        if len(conversation.messages) < MAX_CONTEXT_MESSAGES:
            return
        old_messages = conversation.messages[:-MAX_CONTEXT_MESSAGES_KEEP]
        summary = self._build_lightweight_summary(old_messages)
        if summary:
            self._context_summary = summary

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _apply_window(self, messages: List[Message]) -> List[Message]:
        """Aplica ventana: si hay muchos mensajes, mantiene últimos N + sumario."""
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

    @staticmethod
    def _build_lightweight_summary(messages: List[Message]) -> str:
        """Resumen textual ligero de mensajes antiguos (sin LLM)."""
        parts: List[str] = []
        for msg in messages:
            if msg.role == MessageRole.USER:
                snippet = msg.content[:300].replace("\n", " ")
                parts.append(f"• Usuario: {snippet}")
            elif msg.role == MessageRole.ASSISTANT:
                first_line = msg.content.split("\n")[0][:200]
                parts.append(f"• Asistente: {first_line}")
        return "\n".join(parts[-15:])
