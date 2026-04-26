"""REST API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import ApprovalLevel, OLLAMA_BASE_URL, OperationMode
from llm.client import OllamaClient, OllamaClientError
from web.state import SessionManager
from web.api_rag import router as rag_router
from web.api_memory import router as memory_router

router = APIRouter(prefix="/api", tags=["api"])
router.include_router(rag_router)
router.include_router(memory_router)


# =============================================================================
# Pydantic Models
# =============================================================================

class ConfigUpdate(BaseModel):
    """Actualización de configuración."""
    model: Optional[str] = None
    mode: Optional[str] = None
    temperature: Optional[float] = None
    workspace_root: Optional[str] = None
    approval_level: Optional[str] = None
    max_agent_steps: Optional[int] = None
    agent_task_timeout: Optional[int] = None


class SessionCreate(BaseModel):
    """Crear nueva sesión."""
    workspace_root: Optional[str] = None


class ApprovalAction(BaseModel):
    """Acción de aprobación."""
    approved: bool


# =============================================================================
# Models Endpoints
# =============================================================================

@router.get("/models")
async def get_models() -> Dict[str, Any]:
    """Obtiene la lista de modelos disponibles."""
    try:
        client = OllamaClient(base_url=OLLAMA_BASE_URL)
        models = client.list_models()
        
        # Obtener capacidades de cada modelo
        model_list = []
        for model in models:
            caps = client.get_model_capabilities(model)
            model_list.append({
                "name": model,
                "capabilities": list(caps),
            })
        
        return {"models": model_list}
    except OllamaClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/models/{model_name}/info")
async def get_model_info(model_name: str) -> Dict[str, Any]:
    """Obtiene información detallada de un modelo."""
    try:
        client = OllamaClient(base_url=OLLAMA_BASE_URL)
        info = client.get_model_info(model_name)
        return {"model": model_name, "info": info}
    except OllamaClientError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =============================================================================
# Session Endpoints
# =============================================================================

@router.post("/sessions")
async def create_session(data: SessionCreate) -> Dict[str, Any]:
    """Crea una nueva sesión."""
    session = SessionManager.get_or_create()
    
    if data.workspace_root:
        path = Path(data.workspace_root).expanduser().resolve()
        if path.exists() and path.is_dir():
            session.workspace_root = str(path)
            session.current_cwd = str(path)
    
    return {"session_id": session.id, "session": session.to_dict()}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """Obtiene información de una sesión."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": session.to_dict()}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> Dict[str, str]:
    """Elimina una sesión."""
    if SessionManager.delete(session_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str) -> Dict[str, Any]:
    """Obtiene los mensajes de una sesión."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"messages": session.get_messages_for_display()}


@router.delete("/sessions/{session_id}/messages")
async def clear_messages(session_id: str) -> Dict[str, str]:
    """Limpia los mensajes de una sesión."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.clear()
    return {"status": "cleared"}


# =============================================================================
# Config Endpoints
# =============================================================================

@router.get("/sessions/{session_id}/config")
async def get_config(session_id: str) -> Dict[str, Any]:
    """Obtiene la configuración de una sesión."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "model": session.model,
        "mode": session.mode,
        "temperature": session.temperature,
        "workspace_root": session.workspace_root,
        "current_cwd": session.current_cwd,
        "approval_level": session.approval_level,
        "max_agent_steps": session.max_agent_steps,
        "agent_task_timeout": session.agent_task_timeout,
        "modes": [OperationMode.CHAT, OperationMode.AGENT, OperationMode.PLAN],
        "approval_levels": [ApprovalLevel.NONE, ApprovalLevel.WRITE_ONLY, ApprovalLevel.ALL],
    }


@router.patch("/sessions/{session_id}/config")
async def update_config(session_id: str, data: ConfigUpdate) -> Dict[str, Any]:
    """Actualiza la configuración de una sesión."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if data.model is not None:
        session.model = data.model
    if data.mode is not None:
        if data.mode in (OperationMode.CHAT, OperationMode.AGENT, OperationMode.PLAN):
            session.mode = data.mode
    if data.temperature is not None:
        session.temperature = max(0.0, min(2.0, data.temperature))
    if data.workspace_root is not None:
        path = Path(data.workspace_root).expanduser().resolve()
        if path.exists() and path.is_dir():
            session.workspace_root = str(path)
            session.current_cwd = str(path)
    if data.approval_level is not None:
        if data.approval_level in (ApprovalLevel.NONE, ApprovalLevel.WRITE_ONLY, ApprovalLevel.ALL):
            session.approval_level = data.approval_level
    if data.max_agent_steps is not None:
        session.max_agent_steps = max(1, min(500, data.max_agent_steps))
    if data.agent_task_timeout is not None:
        session.agent_task_timeout = max(30, min(3600, data.agent_task_timeout))

    return {"config": session.to_dict()}


# =============================================================================
# Approval Endpoints
# =============================================================================

@router.get("/sessions/{session_id}/approval")
async def get_pending_approval(session_id: str) -> Dict[str, Any]:
    """Obtiene la aprobación pendiente."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"pending": session.pending_approval}


@router.post("/sessions/{session_id}/approval")
async def handle_approval(session_id: str, action: ApprovalAction) -> Dict[str, str]:
    """Maneja una acción de aprobación."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if not session.pending_approval:
        raise HTTPException(status_code=400, detail="No pending approval")
    
    # La aprobación se maneja via WebSocket para continuar el flujo
    return {"status": "pending", "message": "Use WebSocket to handle approval"}


# =============================================================================
# Plan Endpoints
# =============================================================================

@router.get("/sessions/{session_id}/plan")
async def get_current_plan(session_id: str) -> Dict[str, Any]:
    """Obtiene el plan actual."""
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"plan": session.current_plan}


# =============================================================================
# File Explorer
# =============================================================================

@router.get("/files")
async def list_files(path: str = "") -> Dict[str, Any]:
    """Lista el contenido de un directorio para el explorador de archivos."""

    if not path:
        path = str(Path.home())

    try:
        target = Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                stat = entry.stat(follow_symlinks=False)
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "dir" if is_dir else "file",
                    "size": stat.st_size if not is_dir else None,
                    "hidden": entry.name.startswith("."),
                })
            except PermissionError:
                pass
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")

    parent = str(target.parent) if target != target.parent else None

    return {
        "path": str(target),
        "parent": parent,
        "items": items,
    }


# =============================================================================
# File Content Reader
# =============================================================================

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

@router.get("/file-content")
async def read_file_content(path: str) -> Dict[str, Any]:
    """Lee el contenido de un archivo de texto para el visor."""
    import mimetypes

    try:
        target = Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="La ruta no es un archivo")

    size = target.stat().st_size
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande ({size // 1024} KB). Límite: {MAX_FILE_SIZE // 1024} KB"
        )

    mime, _ = mimetypes.guess_type(str(target))
    is_binary = mime and not (
        mime.startswith("text/") or
        mime in {"application/json", "application/xml", "application/javascript",
                 "application/x-yaml", "application/toml", "application/x-sh"}
    )

    if is_binary:
        raise HTTPException(status_code=415, detail="Archivo binario no soportado")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")

    ext = target.suffix.lstrip(".").lower()

    return {
        "path": str(target),
        "name": target.name,
        "ext": ext,
        "size": size,
        "content": content,
        "lines": content.count("\n") + 1,
    }


# =============================================================================
# Health Check
# =============================================================================

@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


# =============================================================================
# Métricas
# =============================================================================

@router.get("/metrics")
async def get_metrics() -> Dict[str, Any]:
    """Retorna métricas de rendimiento del agente."""
    from web.metrics import MetricsCollector
    return {"metrics": MetricsCollector.summary()}
