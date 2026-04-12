"""Sistema de memoria a largo plazo con dos capas.

Capa A — Workspace memories: hechos técnicos del proyecto (por workspace).
Capa B — User profile: preferencias de comunicación globales.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from uuid import uuid4

from config import (
    MEMORY_AUTO_EXTRACT,
    MEMORY_ENABLED,
    MEMORY_MAX_PROFILE_ITEMS,
    MEMORY_MAX_WORKSPACE_ITEMS,
)

logger = logging.getLogger("memory")


class MemoryStore:
    """
    Gestiona memoria persistente de dos capas.

    Requiere un PersistenceDB ya inicializado para leer/escribir.
    La extracción automática usa el LLM para clasificar qué recordar.
    """

    def __init__(self, db: Any) -> None:
        """
        Args:
            db: Instancia de PersistenceDB (web.persistence).
        """
        self._db = db

    # ------------------------------------------------------------------
    # Workspace memories (Capa A)
    # ------------------------------------------------------------------

    def get_workspace_memories(self, workspace_root: str) -> List[Dict[str, Any]]:
        """Retorna memorias activas para un workspace."""
        if not MEMORY_ENABLED or not self._db:
            return []
        return self._db.load_workspace_memories(
            workspace_root, limit=MEMORY_MAX_WORKSPACE_ITEMS
        )

    def add_workspace_memory(
        self,
        workspace_root: str,
        content: str,
        category: str = "fact",
    ) -> str:
        """Agrega una memoria de workspace. Retorna el ID."""
        mid = str(uuid4())[:12]
        if self._db:
            self._db.save_workspace_memory(mid, workspace_root, content, category)
        return mid

    def delete_workspace_memory(self, memory_id: str) -> bool:
        if self._db:
            return self._db.delete_workspace_memory(memory_id)
        return False

    # ------------------------------------------------------------------
    # User profile (Capa B)
    # ------------------------------------------------------------------

    def get_profile_traits(self) -> List[Dict[str, Any]]:
        """Retorna rasgos activos del perfil de usuario."""
        if not MEMORY_ENABLED or not self._db:
            return []
        return self._db.load_profile_traits(limit=MEMORY_MAX_PROFILE_ITEMS)

    def add_profile_trait(
        self,
        content: str,
        trait_type: str = "preference",
    ) -> str:
        """Agrega un rasgo de perfil. Retorna el ID."""
        tid = str(uuid4())[:12]
        if self._db:
            self._db.save_profile_trait(tid, content, trait_type)
        return tid

    def delete_profile_trait(self, trait_id: str) -> bool:
        if self._db:
            return self._db.delete_profile_trait(trait_id)
        return False

    # ------------------------------------------------------------------
    # Auto-extracción vía LLM
    # ------------------------------------------------------------------

    def extract_memories(
        self,
        llm_call,
        workspace_root: str,
        user_message: str,
        assistant_response: str,
    ) -> Dict[str, List[str]]:
        """
        Analiza la conversación reciente y extrae memorias nuevas.

        Args:
            llm_call: Callable(messages) -> str  (wrapper del LLM).
            workspace_root: Ruta del workspace actual.
            user_message: Último mensaje del usuario.
            assistant_response: Última respuesta del asistente.

        Returns:
            {"workspace": [...], "profile": [...]} con las memorias extraídas.
        """
        if not MEMORY_ENABLED or not MEMORY_AUTO_EXTRACT:
            return {"workspace": [], "profile": []}

        from llm.prompts import MEMORY_EXTRACTION_PROMPT

        messages = [
            {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Mensaje del usuario:\n{user_message[:2000]}\n\n"
                    f"Respuesta del asistente:\n{assistant_response[:2000]}"
                ),
            },
        ]

        try:
            raw = llm_call(messages).strip()
            # Quitar bloque markdown si lo envuelve
            if raw.startswith("```"):
                lines = raw.splitlines()
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            data = json.loads(raw)
        except Exception:
            logger.debug("No se pudieron extraer memorias de la conversación")
            return {"workspace": [], "profile": []}

        result: Dict[str, List[str]] = {"workspace": [], "profile": []}

        # Persistir memorias de workspace
        for item in data.get("workspace", []):
            if isinstance(item, dict):
                content = item.get("content", "")
                category = item.get("category", "fact")
            elif isinstance(item, str):
                content = item
                category = "fact"
            else:
                continue
            if content.strip():
                self.add_workspace_memory(workspace_root, content.strip(), category)
                result["workspace"].append(content.strip())

        # Persistir rasgos de perfil
        for item in data.get("profile", []):
            if isinstance(item, dict):
                content = item.get("content", "")
                trait_type = item.get("trait_type", "preference")
            elif isinstance(item, str):
                content = item
                trait_type = "preference"
            else:
                continue
            if content.strip():
                self.add_profile_trait(content.strip(), trait_type)
                result["profile"].append(content.strip())

        return result

    # ------------------------------------------------------------------
    # Helpers para inyección en prompt
    # ------------------------------------------------------------------

    def build_memory_context(self, workspace_root: str) -> str:
        """
        Construye el bloque de contexto de memoria para inyectar en el prompt.

        Retorna string vacío si no hay memorias.
        """
        if not MEMORY_ENABLED:
            return ""

        sections: List[str] = []

        # Perfil global
        traits = self.get_profile_traits()
        if traits:
            lines = [f"• {t['content']}" for t in traits]
            sections.append(
                "[Perfil del usuario — aplica a todas las sesiones, "
                "NO interfiere si el usuario usa role-play o supuestos]\n"
                + "\n".join(lines)
            )

        # Memorias del workspace
        memories = self.get_workspace_memories(workspace_root)
        if memories:
            lines = [f"• [{m['category']}] {m['content']}" for m in memories]
            sections.append(
                "[Contexto del proyecto — específico de este workspace]\n"
                + "\n".join(lines)
            )

        return "\n\n".join(sections)
