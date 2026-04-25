"""Submódulos del motor de conversación.

Cada componente tiene una responsabilidad única:
- parser:           extrae intención de tool desde texto libre
- reflector:        revisión crítica opcional de la respuesta final
- context_builder:  construye los mensajes para el LLM (system, ventana, workspace)
- natural_loop:     orquesta el ciclo modelo → parser → tool → modelo
"""

from core.conversation.context_builder import ContextBuilder
from core.conversation.natural_loop import LoopResult, NaturalConversationLoop
from core.conversation.parser import NaturalResponseParser
from core.conversation.reflector import ResponseReflector

__all__ = [
    "ContextBuilder",
    "LoopResult",
    "NaturalConversationLoop",
    "NaturalResponseParser",
    "ResponseReflector",
]
