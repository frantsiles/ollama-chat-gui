"""REST API endpoints para memoria a largo plazo."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import MEMORY_ENABLED
from core.memory import MemoryStore
from web.state import SessionManager

router = APIRouter(prefix="/memory", tags=["memory"])


def _get_store() -> MemoryStore:
    """Obtiene el MemoryStore vinculado a la DB de persistencia."""
    if not MEMORY_ENABLED:
        raise HTTPException(status_code=404, detail="Memory system disabled")
    db = SessionManager._db
    if not db:
        raise HTTPException(status_code=503, detail="Persistence not initialized")
    return MemoryStore(db)


# =============================================================================
# Pydantic Models
# =============================================================================

class MemoryCreate(BaseModel):
    content: str
    category: str = "fact"

class ProfileTraitCreate(BaseModel):
    content: str
    trait_type: str = "preference"


# =============================================================================
# Workspace Memories
# =============================================================================

@router.get("/workspace/{workspace_root:path}")
async def list_workspace_memories(workspace_root: str) -> Dict[str, Any]:
    """Lista memorias activas para un workspace."""
    store = _get_store()
    memories = store.get_workspace_memories(workspace_root)
    return {"memories": memories, "count": len(memories)}


@router.post("/workspace/{workspace_root:path}")
async def add_workspace_memory(
    workspace_root: str, data: MemoryCreate
) -> Dict[str, Any]:
    """Agrega una memoria de workspace manualmente."""
    store = _get_store()
    mid = store.add_workspace_memory(workspace_root, data.content, data.category)
    return {"id": mid, "status": "created"}


@router.delete("/workspace/item/{memory_id}")
async def delete_workspace_memory(memory_id: str) -> Dict[str, str]:
    """Elimina (soft-delete) una memoria de workspace."""
    store = _get_store()
    if store.delete_workspace_memory(memory_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Memory not found")


# =============================================================================
# User Profile
# =============================================================================

@router.get("/profile")
async def list_profile_traits() -> Dict[str, Any]:
    """Lista rasgos activos del perfil de usuario."""
    store = _get_store()
    traits = store.get_profile_traits()
    return {"traits": traits, "count": len(traits)}


@router.post("/profile")
async def add_profile_trait(data: ProfileTraitCreate) -> Dict[str, Any]:
    """Agrega un rasgo de perfil manualmente."""
    store = _get_store()
    tid = store.add_profile_trait(data.content, data.trait_type)
    return {"id": tid, "status": "created"}


@router.delete("/profile/{trait_id}")
async def delete_profile_trait(trait_id: str) -> Dict[str, str]:
    """Elimina (soft-delete) un rasgo del perfil."""
    store = _get_store()
    if store.delete_profile_trait(trait_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Trait not found")
