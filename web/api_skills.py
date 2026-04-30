"""Skills API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tools.skills_manager import SkillsManager
from web.state import SessionManager

router = APIRouter(prefix="/skills", tags=["skills"])


def _manager() -> SkillsManager:
    session = SessionManager.get_or_create()
    workspace = Path(session.workspace_root) if session.workspace_root else Path.cwd()
    return SkillsManager(workspace)


# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------

class SkillCreate(BaseModel):
    name: str
    description: str
    content: str


class SkillUpdate(BaseModel):
    description: str
    content: str


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
async def list_skills() -> Dict[str, Any]:
    return {"skills": [s.to_dict() for s in _manager().list_skills()]}


@router.post("", status_code=201)
async def create_skill(data: SkillCreate) -> Dict[str, Any]:
    mgr = _manager()
    if mgr.get_skill(data.name):
        raise HTTPException(status_code=409, detail=f"Skill '{data.name}' ya existe")
    skill = mgr.create_skill(data.name, data.description, data.content)
    return {"skill": skill.to_dict()}


@router.put("/{name}")
async def update_skill(name: str, data: SkillUpdate) -> Dict[str, Any]:
    skill = _manager().update_skill(name, data.description, data.content)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' no encontrado")
    return {"skill": skill.to_dict()}


@router.delete("/{name}")
async def delete_skill(name: str) -> Dict[str, str]:
    if not _manager().delete_skill(name):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' no encontrado")
    return {"status": "deleted"}


@router.get("/{name}")
async def get_skill(name: str) -> Dict[str, Any]:
    skill = _manager().get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' no encontrado")
    return {"skill": skill.to_dict()}
