"""JSON schemas para structured outputs.

Estos schemas se pasan como `fmt` a los providers (Ollama ≥0.5 acepta un
schema completo en `format`; OpenAI-compatible lo mapea a response_format
json_schema). Constriñen la salida del modelo en las llamadas "de decisión"
—parser de intenciones, planes, reflexión, memorias— eliminando la mayoría
de los JSON malformados que antes había que reparar con regex.

Los providers que no soportan schema degradan automáticamente a modo
"json" legacy, por lo que los prompts siguen describiendo el formato.
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Parser de intenciones (NaturalResponseParser, fallback LLM)
# ---------------------------------------------------------------------------

PARSER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "needs_tool": {"type": "boolean"},
        "tool": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["needs_tool"],
}

# ---------------------------------------------------------------------------
# Modo Plan (create_plan)
# ---------------------------------------------------------------------------

PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["create_plan"]},
        "plan": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "description": {"type": "string"},
                            "tool": {"type": ["string", "null"]},
                            "args": {"type": "object"},
                            "requires_approval": {"type": "boolean"},
                        },
                        "required": ["id", "description"],
                    },
                },
            },
            "required": ["title", "steps"],
        },
    },
    "required": ["action", "plan"],
}

# ---------------------------------------------------------------------------
# Reflexión crítica (ResponseReflector)
# ---------------------------------------------------------------------------

REFLECTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "needs_fix"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "corrected_response": {"type": "string"},
    },
    "required": ["status"],
}

# ---------------------------------------------------------------------------
# Extracción de memorias (MemoryExtractionHook)
# ---------------------------------------------------------------------------

MEMORY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "workspace": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["fact", "decision", "pattern", "error_fix"],
                    },
                },
                "required": ["content", "category"],
            },
        },
        "profile": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "trait_type": {
                        "type": "string",
                        "enum": ["communication", "preference", "convention"],
                    },
                },
                "required": ["content", "trait_type"],
            },
        },
    },
    "required": ["workspace", "profile"],
}

# ---------------------------------------------------------------------------
# Reintento de paso fallido (PlanExecutor / STEP_RETRY_PROMPT)
# ---------------------------------------------------------------------------

STEP_RETRY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string"},
        "tool": {"type": "string"},
        "args": {"type": "object"},
        "reason": {"type": "string"},
    },
    "required": ["strategy"],
}
