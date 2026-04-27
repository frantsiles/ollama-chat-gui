"""REST API endpoints."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, Optional

import json

from fastapi import APIRouter, HTTPException, Request, UploadFile, File as FastAPIFile
from fastapi.responses import StreamingResponse
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
    system_prompt: Optional[str] = None


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
        "system_prompt": session.system_prompt,
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
    if data.system_prompt is not None:
        session.system_prompt = data.system_prompt[:4000]  # razonable upper bound

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

_HOME = Path.home().resolve()


def _resolve_safe(path: str, workspace: str | None = None) -> Path:
    """Resolve path and ensure it stays within workspace (or home as fallback).

    Raises HTTP 400 for invalid paths, HTTP 403 for out-of-jail access.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if workspace:
        try:
            jail = Path(workspace).expanduser().resolve()
        except Exception:
            raise HTTPException(status_code=400, detail="Workspace inválido")
    else:
        jail = _HOME

    try:
        resolved.relative_to(jail)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: ruta fuera del workspace permitido",
        )
    return resolved


def _load_gitignore(directory: Path):
    """Return a pathspec.PathSpec built from directory's .gitignore (if present)."""
    import pathspec
    gi = directory / ".gitignore"
    if gi.is_file():
        try:
            lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
            return pathspec.PathSpec.from_lines("gitwildmatch", lines)
        except OSError:
            pass
    return pathspec.PathSpec.from_lines("gitwildmatch", [])


def _matches_gitignore(name: str, spec) -> bool:
    return bool(spec) and spec.match_file(name)


MAX_TREE_ITEMS = 300   # max items returned per directory level


@router.get("/files")
async def list_files(
    path: str = "",
    show_hidden: bool = False,
    use_gitignore: bool = True,
    workspace: str = "",
    offset: int = 0,
) -> Dict[str, Any]:
    """Lista el contenido de un directorio. Devuelve max MAX_TREE_ITEMS ítems por página."""

    if not path:
        path = str(Path.home())

    target = _resolve_safe(path, workspace or None)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    gi_spec = _load_gitignore(target) if use_gitignore else None

    all_items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                is_hidden = entry.name.startswith(".")
                if is_hidden and not show_hidden:
                    continue
                if use_gitignore and _matches_gitignore(entry.name, gi_spec):
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                stat = entry.stat(follow_symlinks=False)
                all_items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "dir" if is_dir else "file",
                    "size": stat.st_size if not is_dir else None,
                    "hidden": is_hidden,
                })
            except PermissionError:
                pass
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")

    total = len(all_items)
    page = all_items[offset: offset + MAX_TREE_ITEMS]
    parent = str(target.parent) if target != target.parent else None

    return {
        "path": str(target),
        "parent": parent,
        "items": page,
        "total": total,
        "offset": offset,
        "truncated": total > offset + MAX_TREE_ITEMS,
    }


# =============================================================================
# File CRUD
# =============================================================================

class FileCreateBody(BaseModel):
    path: str
    content: str = ""
    workspace: str = ""

class DirCreateBody(BaseModel):
    path: str
    workspace: str = ""

class RenameBody(BaseModel):
    path: str
    new_name: str
    workspace: str = ""

class DeleteBody(BaseModel):
    path: str

class DuplicateBody(BaseModel):
    path: str
    workspace: str = ""


@router.post("/files/create")
async def create_file(body: FileCreateBody) -> Dict[str, Any]:
    """Crea un nuevo archivo de texto."""
    target = _resolve_safe(body.path, body.workspace or None)
    if target.exists():
        raise HTTPException(status_code=409, detail="El archivo ya existe")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")
    return {"path": str(target), "name": target.name}


@router.post("/files/mkdir")
async def create_dir(body: DirCreateBody) -> Dict[str, Any]:
    """Crea un nuevo directorio."""
    target = _resolve_safe(body.path, body.workspace or None)
    if target.exists():
        raise HTTPException(status_code=409, detail="El directorio ya existe")
    try:
        target.mkdir(parents=True, exist_ok=False)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")
    return {"path": str(target), "name": target.name}


@router.post("/files/rename")
async def rename_entry(body: RenameBody) -> Dict[str, Any]:
    """Renombra un archivo o directorio."""
    src = _resolve_safe(body.path, body.workspace or None)
    if not src.exists():
        raise HTTPException(status_code=404, detail="No encontrado")
    if "/" in body.new_name or "\\" in body.new_name:
        raise HTTPException(status_code=400, detail="El nombre no puede contener separadores de ruta")
    dst = src.parent / body.new_name
    if dst.exists():
        raise HTTPException(status_code=409, detail="Ya existe un archivo con ese nombre")
    try:
        src.rename(dst)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")
    return {"old_path": str(src), "new_path": str(dst), "name": dst.name}


@router.delete("/files/delete")
async def delete_entry(path: str, workspace: str = "", trash: bool = True) -> Dict[str, Any]:
    """Elimina (o mueve a la papelera) un archivo o directorio."""
    import shutil
    from datetime import datetime

    target = _resolve_safe(path, workspace or None)
    if not target.exists():
        raise HTTPException(status_code=404, detail="No encontrado")

    if trash and workspace:
        ws = Path(workspace).expanduser().resolve()  # already validated via path check above
        trash_dir = ws / ".trash"
        try:
            trash_dir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trash_dest = trash_dir / f"{stamp}_{target.name}"
            shutil.move(str(target), str(trash_dest))
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permiso denegado")
        return {"deleted": str(target), "trash_path": str(trash_dest), "trashed": True}

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")
    return {"deleted": str(target), "trashed": False}


@router.post("/files/duplicate")
async def duplicate_entry(body: DuplicateBody) -> Dict[str, Any]:
    """Duplica un archivo o directorio con sufijo '_copia'."""
    src = _resolve_safe(body.path, body.workspace or None)
    if not src.exists():
        raise HTTPException(status_code=404, detail="No encontrado")

    import shutil
    # Build a non-colliding name: name_copia, name_copia2, ...
    if src.is_dir():
        base = src.name + "_copia"
        dst = src.parent / base
        counter = 2
        while dst.exists():
            dst = src.parent / f"{base}{counter}"
            counter += 1
        try:
            shutil.copytree(src, dst)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permiso denegado")
    else:
        stem = src.stem + "_copia"
        suffix = src.suffix
        dst = src.parent / (stem + suffix)
        counter = 2
        while dst.exists():
            dst = src.parent / f"{stem}{counter}{suffix}"
            counter += 1
        try:
            shutil.copy2(src, dst)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permiso denegado")

    return {"original": str(src), "copy": str(dst), "name": dst.name}


class MoveBody(BaseModel):
    src_path: str
    dst_dir: str   # destination directory (not full path)
    workspace: str = ""


@router.post("/files/move")
async def move_entry(body: MoveBody) -> Dict[str, Any]:
    """Mueve un archivo o directorio a otro directorio."""
    ws = body.workspace or None
    src = _resolve_safe(body.src_path, ws)
    dst_dir = _resolve_safe(body.dst_dir, ws)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Origen no encontrado")
    if not dst_dir.is_dir():
        raise HTTPException(status_code=400, detail="El destino no es un directorio")
    dst = dst_dir / src.name
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"Ya existe '{src.name}' en el destino")
    try:
        import shutil
        shutil.move(str(src), str(dst))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")
    return {"src": str(src), "dst": str(dst), "name": dst.name}


MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB per file


_SAFE_FILENAME = re.compile(r'[^\w.\- ]')


def _sanitize_filename(raw: str) -> str:
    """Return a safe filename: strip path separators, null bytes, leading dots/spaces."""
    name = Path(raw).name  # strip any directory component
    name = name.replace("\x00", "")  # null bytes
    name = _SAFE_FILENAME.sub("_", name)  # replace unsafe chars
    name = name.lstrip(". ")  # no leading dots or spaces
    return name or "upload"


@router.post("/files/upload")
async def upload_files(
    dir: str,
    workspace: str = "",
    files: list[UploadFile] = FastAPIFile(...),
) -> Dict[str, Any]:
    """Sube uno o más archivos a un directorio del workspace."""
    target_dir = _resolve_safe(dir, workspace or None)
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="El directorio no existe")

    saved = []
    for uf in files:
        name = _sanitize_filename(uf.filename or "upload")
        dest = target_dir / name
        # avoid collisions
        counter = 1
        stem, suffix = Path(name).stem, Path(name).suffix
        while dest.exists():
            dest = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        data = await uf.read()
        if len(data) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail=f"{name}: archivo demasiado grande (max 50 MB)")
        try:
            dest.write_bytes(data)
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"Permiso denegado: {name}")
        saved.append({"name": dest.name, "path": str(dest), "size": len(data)})

    return {"uploaded": saved}


# =============================================================================
# File Search (by name)
# =============================================================================

_IGNORE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
                '.mypy_cache', '.pytest_cache', 'dist', 'build', '.next',
                '.nuxt', 'coverage', '.tox'}

@router.get("/files/search")
async def search_files(path: str = "", q: str = "", workspace: str = "") -> Dict[str, Any]:
    """Busca archivos por nombre (fuzzy) dentro de un directorio."""
    if not q:
        return {"items": []}
    if not path:
        path = str(Path.home())

    root = _resolve_safe(path, workspace or None)

    if not root.is_dir():
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    q_lower = q.lower()
    results: list[Dict[str, Any]] = []
    MAX_RESULTS = 50

    def _do_walk():
        def _walk(d: Path, depth: int = 0):
            if depth > 12 or len(results) >= MAX_RESULTS:
                return
            try:
                for entry in sorted(d.iterdir(), key=lambda e: (e.is_dir(), e.name.lower())):
                    if len(results) >= MAX_RESULTS:
                        return
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in _IGNORE_DIRS:
                            continue
                        _walk(entry, depth + 1)
                    else:
                        if q_lower in entry.name.lower():
                            try:
                                rel = entry.relative_to(root)
                            except ValueError:
                                rel = entry
                            results.append({
                                "name": entry.name,
                                "path": str(entry),
                                "rel_path": str(rel),
                            })
            except PermissionError:
                pass
        _walk(root)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_walk)
    return {"items": results}


# =============================================================================
# File Grep (search in content)
# =============================================================================

@router.get("/files/grep")
async def grep_files(
    path: str = "",
    q: str = "",
    case_sensitive: bool = False,
    workspace: str = "",
) -> Dict[str, Any]:
    """Busca texto en el contenido de archivos del workspace."""
    if not q:
        return {"groups": []}
    if not path:
        path = str(Path.home())

    root = _resolve_safe(path, workspace or None)

    if not root.is_dir():
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    import mimetypes
    import re as _re

    pattern_flags = 0 if case_sensitive else _re.IGNORECASE
    try:
        pattern = _re.compile(_re.escape(q), pattern_flags)
    except _re.error:
        raise HTTPException(status_code=400, detail="Patrón inválido")

    MAX_FILE_SIZE_GREP = 512 * 1024  # 512 KB per file
    MAX_MATCHES_PER_FILE = 30
    MAX_FILES = 30
    groups: list[Dict[str, Any]] = []

    def _is_text(p: Path) -> bool:
        mime, _ = mimetypes.guess_type(str(p))
        if mime is None:
            return p.suffix.lower() in {
                '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json',
                '.md', '.txt', '.sh', '.yml', '.yaml', '.toml', '.ini', '.cfg',
                '.env', '.rs', '.go', '.java', '.c', '.cpp', '.h', '.hpp',
                '.rb', '.php', '.sql', '.xml', '.tf', '.lua', '.r', '.scala',
                '.kt', '.swift', '.vim', '.dockerfile', '', '.gitignore',
            }
        return mime.startswith("text/") or mime in {
            "application/json", "application/xml", "application/javascript",
            "application/x-yaml", "application/toml", "application/x-sh",
        }

    def _do_grep():
        def _walk_grep(d: Path, depth: int = 0):
            if depth > 12 or len(groups) >= MAX_FILES:
                return
            try:
                for entry in sorted(d.iterdir(), key=lambda e: (e.is_dir(), e.name.lower())):
                    if len(groups) >= MAX_FILES:
                        return
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in _IGNORE_DIRS:
                            continue
                        _walk_grep(entry, depth + 1)
                    elif entry.is_file(follow_symlinks=False):
                        try:
                            if entry.stat().st_size > MAX_FILE_SIZE_GREP:
                                continue
                            if not _is_text(entry):
                                continue
                            text = entry.read_text(encoding="utf-8", errors="replace")
                        except (PermissionError, OSError):
                            continue

                        matches = []
                        for i, line in enumerate(text.splitlines(), 1):
                            if len(matches) >= MAX_MATCHES_PER_FILE:
                                break
                            m = pattern.search(line)
                            if m:
                                matches.append({
                                    "line_no": i,
                                    "line": line[:200],
                                    "match_start": m.start(),
                                    "match_end": m.end(),
                                })
                        if matches:
                            try:
                                rel = entry.relative_to(root)
                            except ValueError:
                                rel = entry
                            groups.append({
                                "file_name": entry.name,
                                "file_path": str(entry),
                                "rel_path": str(rel),
                                "matches": matches,
                            })
            except PermissionError:
                pass
        _walk_grep(root)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_grep)
    return {"groups": groups, "total_files": len(groups)}


# =============================================================================
# File Grep – streaming SSE
# =============================================================================

@router.get("/files/grep/stream")
async def grep_files_stream(
    request: Request,
    path: str = "",
    q: str = "",
    case_sensitive: bool = False,
    workspace: str = "",
):
    """Grep streaming vía SSE: emite un evento JSON por archivo con coincidencias."""
    import mimetypes
    import re as _re

    def _is_text(p: Path) -> bool:
        mime, _ = mimetypes.guess_type(str(p))
        if mime is None:
            return p.suffix.lower() in {
                '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json',
                '.md', '.txt', '.sh', '.yml', '.yaml', '.toml', '.ini', '.cfg',
                '.env', '.rs', '.go', '.java', '.c', '.cpp', '.h', '.hpp',
                '.rb', '.php', '.sql', '.xml', '.tf', '.lua', '.r', '.scala',
                '.kt', '.swift', '.vim', '.dockerfile', '', '.gitignore',
            }
        return mime.startswith("text/") or mime in {
            "application/json", "application/xml", "application/javascript",
            "application/x-yaml", "application/toml", "application/x-sh",
        }

    async def generate():
        if not q:
            yield f'data: {json.dumps({"done": True, "total_files": 0, "total_matches": 0})}\n\n'
            return

        root_path = path or str(Path.home())
        try:
            root = _resolve_safe(root_path, workspace or None)
        except HTTPException:
            yield f'data: {json.dumps({"error": "Ruta no válida"})}\n\n'
            return

        if not root.is_dir():
            yield f'data: {json.dumps({"error": "La ruta no es un directorio"})}\n\n'
            return

        pattern_flags = 0 if case_sensitive else _re.IGNORECASE
        try:
            pattern = _re.compile(_re.escape(q), pattern_flags)
        except _re.error:
            yield f'data: {json.dumps({"error": "Patrón inválido"})}\n\n'
            return

        MAX_FILE_SIZE_GREP = 512 * 1024
        MAX_MATCHES_PER_FILE = 30
        BATCH = 20

        # Collect candidate file paths (fast, no I/O per file)
        all_paths: list[Path] = []

        def collect(d: Path, depth: int = 0):
            if depth > 12:
                return
            try:
                for entry in sorted(d.iterdir(), key=lambda e: (e.is_dir(), e.name.lower())):
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in _IGNORE_DIRS:
                            collect(entry, depth + 1)
                    elif entry.is_file(follow_symlinks=False):
                        all_paths.append(entry)
            except PermissionError:
                pass

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, collect, root)

        total_files = 0
        total_matches = 0

        for i in range(0, len(all_paths), BATCH):
            if await request.is_disconnected():
                return

            batch = all_paths[i : i + BATCH]

            def process_batch(paths: list[Path]) -> list[dict]:
                results = []
                for entry in paths:
                    try:
                        if entry.stat().st_size > MAX_FILE_SIZE_GREP:
                            continue
                        if not _is_text(entry):
                            continue
                        text = entry.read_text(encoding="utf-8", errors="replace")
                    except (PermissionError, OSError):
                        continue

                    matches = []
                    for line_no, line in enumerate(text.splitlines(), 1):
                        if len(matches) >= MAX_MATCHES_PER_FILE:
                            break
                        m = pattern.search(line)
                        if m:
                            matches.append({
                                "line_no": line_no,
                                "line": line[:200],
                                "match_start": m.start(),
                                "match_end": m.end(),
                            })
                    if matches:
                        try:
                            rel = entry.relative_to(root)
                        except ValueError:
                            rel = entry
                        results.append({
                            "file_name": entry.name,
                            "file_path": str(entry),
                            "rel_path": str(rel),
                            "matches": matches,
                        })
                return results

            for group in await loop.run_in_executor(None, process_batch, batch):
                total_files += 1
                total_matches += len(group["matches"])
                yield f'data: {json.dumps(group)}\n\n'

        yield f'data: {json.dumps({"done": True, "total_files": total_files, "total_matches": total_matches})}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =============================================================================
# File Content Reader
# =============================================================================

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

@router.get("/file-content")
async def read_file_content(path: str, workspace: str = "") -> Dict[str, Any]:
    """Lee el contenido de un archivo de texto para el visor."""
    import mimetypes

    target = _resolve_safe(path, workspace or None)

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
# Git helpers
# =============================================================================

async def _git(args: list[str], cwd: str, timeout: float = 8.0) -> tuple[int, str, str]:
    """Run a git command, return (returncode, stdout, stderr)."""
    import asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except FileNotFoundError:
        return -1, "", "git not found"
    except asyncio.TimeoutError:
        return -1, "", "timeout"


def _resolve_repo(path: str) -> Path:
    if not path:
        raise HTTPException(status_code=400, detail="path requerido")
    root = _resolve_safe(path)
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")
    return root


# =============================================================================
# Git Status  (for tree badge overlay — kept for backward compat)
# =============================================================================

@router.get("/git/status")
async def git_status(path: str = "") -> Dict[str, Any]:
    """Porcelain status map for tree badge overlay."""
    if not path:
        return {"files": {}, "is_git": False}
    root = _resolve_repo(path)
    rc, stdout, _ = await _git(["status", "--porcelain", "-u"], str(root))
    if rc == 128 or rc == -1:
        return {"files": {}, "is_git": rc != -1 and "not found" not in _}

    files: dict[str, str] = {}
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        xy, rel = line[:2], line[3:]
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip().strip('"')
        x, y = xy[0], xy[1]
        badge = x if x != " " else y
        if badge == "?":
            badge = "U"
        files[rel] = badge
    return {"files": files, "is_git": True}


# =============================================================================
# Git Info  (branch, remote, user, ahead/behind)
# =============================================================================

@router.get("/git/info")
async def git_info(path: str = "") -> Dict[str, Any]:
    """Full repo info: branch, remote, user identity, ahead/behind."""
    if not path:
        return {"is_git": False}
    root = _resolve_repo(path)

    # Check if git repo
    rc, _, _ = await _git(["rev-parse", "--git-dir"], str(root))
    if rc != 0:
        return {"is_git": False}

    async def _get(args: list[str]) -> str:
        _, out, _ = await _git(args, str(root))
        return out.strip()

    branch      = await _get(["rev-parse", "--abbrev-ref", "HEAD"])
    user_name   = await _get(["config", "user.name"])
    user_email  = await _get(["config", "user.email"])
    remote_url  = await _get(["config", "--get", "remote.origin.url"])

    # Ahead / behind vs origin
    ahead = behind = 0
    rc2, rev, _ = await _git(["rev-list", "--left-right", "--count",
                               f"HEAD...origin/{branch}"], str(root))
    if rc2 == 0:
        parts = rev.strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    # Last commit info
    rc3, log, _ = await _git(
        ["log", "-1", "--pretty=format:%H|%s|%an|%ar"],
        str(root),
    )
    last_commit: dict | None = None
    if rc3 == 0 and log:
        h, subj, author, rel_time = (log.split("|") + ["", "", "", ""])[:4]
        last_commit = {"hash": h[:8], "subject": subj, "author": author, "time": rel_time}

    # Stash count
    _, stash_out, _ = await _git(["stash", "list"], str(root))
    stash_count = len([l for l in stash_out.splitlines() if l])

    return {
        "is_git": True,
        "branch": branch,
        "user_name": user_name,
        "user_email": user_email,
        "remote_url": remote_url,
        "ahead": ahead,
        "behind": behind,
        "last_commit": last_commit,
        "stash_count": stash_count,
    }


# =============================================================================
# Git Changes  (staged + unstaged file list)
# =============================================================================

@router.get("/git/changes")
async def git_changes(path: str = "") -> Dict[str, Any]:
    """Staged and unstaged changes, plus untracked files."""
    if not path:
        return {"is_git": False, "staged": [], "unstaged": [], "untracked": []}
    root = _resolve_repo(path)

    rc, stdout, _ = await _git(["status", "--porcelain", "-u"], str(root))
    if rc != 0:
        return {"is_git": False, "staged": [], "unstaged": [], "untracked": []}

    staged, unstaged, untracked = [], [], []
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        x, y = line[0], line[1]
        rel = line[3:]
        if " -> " in rel:
            old, rel = rel.split(" -> ", 1)
        rel = rel.strip().strip('"')

        if x == "?" and y == "?":
            untracked.append({"path": rel, "x": "?", "y": "?"})
            continue
        if x != " " and x != "?":
            staged.append({"path": rel, "x": x, "y": y})
        if y != " " and y != "?":
            unstaged.append({"path": rel, "x": x, "y": y})

    return {"is_git": True, "staged": staged, "unstaged": unstaged, "untracked": untracked}


# =============================================================================
# Git Diff
# =============================================================================

@router.get("/git/diff")
async def git_diff(path: str = "", file: str = "", staged: bool = False) -> Dict[str, Any]:
    """Unified diff for a single file (staged or working-tree)."""
    if not path or not file:
        raise HTTPException(status_code=400, detail="path y file requeridos")
    root = _resolve_repo(path)
    args = ["diff", "--unified=4"]
    if staged:
        args.append("--cached")
    args.append("--")
    args.append(file)
    rc, diff_out, _ = await _git(args, str(root))
    return {"diff": diff_out, "file": file, "staged": staged}


# =============================================================================
# Git Log
# =============================================================================

@router.get("/git/log")
async def git_log(path: str = "", n: int = 20) -> Dict[str, Any]:
    """Recent commits."""
    if not path:
        return {"is_git": False, "commits": []}
    root = _resolve_repo(path)
    n = min(max(1, n), 100)
    rc, out, _ = await _git(
        ["log", f"-{n}", "--pretty=format:%H|%s|%an|%ae|%ar|%d"],
        str(root),
    )
    if rc != 0:
        return {"is_git": False, "commits": []}
    commits = []
    for line in out.splitlines():
        parts = (line.split("|") + [""] * 6)[:6]
        commits.append({
            "hash": parts[0][:8], "full_hash": parts[0],
            "subject": parts[1], "author": parts[2],
            "email": parts[3], "time": parts[4], "refs": parts[5].strip(),
        })
    return {"is_git": True, "commits": commits}


# =============================================================================
# Git Actions (init, stage, unstage, commit, push, pull, discard)
# =============================================================================

class GitPathBody(BaseModel):
    path: str
    files: list[str] = []

class GitCommitBody(BaseModel):
    path: str
    message: str
    amend: bool = False

class GitPushPullBody(BaseModel):
    path: str
    remote: str = "origin"
    branch: str = ""
    set_upstream: bool = False

class GitRemoteAddBody(BaseModel):
    path: str
    name: str = "origin"
    url: str = ""

class GitInitBody(BaseModel):
    path: str

class GitConfigBody(BaseModel):
    path: str          # repo path
    user_name: str = ""
    user_email: str = ""


@router.post("/git/init")
async def git_init(body: GitInitBody) -> Dict[str, Any]:
    root = _resolve_repo(body.path)
    rc, out, err = await _git(["init"], str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip() or "Error al inicializar")
    return {"message": out.strip() or "Repositorio inicializado", "path": str(root)}


@router.post("/git/stage")
async def git_stage(body: GitPathBody) -> Dict[str, Any]:
    root = _resolve_repo(body.path)
    files = body.files or ["."]
    rc, _, err = await _git(["add", "--"] + files, str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip())
    return {"staged": files}


@router.post("/git/unstage")
async def git_unstage(body: GitPathBody) -> Dict[str, Any]:
    root = _resolve_repo(body.path)
    files = body.files or ["."]
    rc, _, err = await _git(["restore", "--staged", "--"] + files, str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip())
    return {"unstaged": files}


@router.post("/git/discard")
async def git_discard(body: GitPathBody) -> Dict[str, Any]:
    """Discard working-tree changes (restore file to HEAD)."""
    root = _resolve_repo(body.path)
    files = body.files
    if not files:
        raise HTTPException(status_code=400, detail="Especifica al menos un archivo")
    rc, _, err = await _git(["restore", "--"] + files, str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip())
    return {"discarded": files}


@router.post("/git/commit")
async def git_commit(body: GitCommitBody) -> Dict[str, Any]:
    root = _resolve_repo(body.path)
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    args = ["commit", "-m", body.message]
    if body.amend:
        args.append("--amend")
    rc, out, err = await _git(args, str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip() or out.strip())
    return {"message": out.strip()}


@router.post("/git/remote/add")
async def git_remote_add(body: GitRemoteAddBody) -> Dict[str, Any]:
    if not body.url:
        raise HTTPException(status_code=400, detail="URL requerida")
    root = _resolve_repo(body.path)
    rc, out, err = await _git(["remote", "add", body.name, body.url], str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=(err or out).strip())
    return {"message": f"Remote '{body.name}' añadido"}


@router.post("/git/remote/set-url")
async def git_remote_set_url(body: GitRemoteAddBody) -> Dict[str, Any]:
    if not body.url:
        raise HTTPException(status_code=400, detail="URL requerida")
    root = _resolve_repo(body.path)
    rc, out, err = await _git(["remote", "set-url", body.name, body.url], str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=(err or out).strip())
    return {"message": f"URL de remote '{body.name}' actualizada"}


@router.post("/git/remote/remove")
async def git_remote_remove(body: GitRemoteAddBody) -> Dict[str, Any]:
    root = _resolve_repo(body.path)
    rc, out, err = await _git(["remote", "remove", body.name], str(root))
    if rc != 0:
        raise HTTPException(status_code=500, detail=(err or out).strip())
    return {"message": f"Remote '{body.name}' eliminado"}


@router.post("/git/push")
async def git_push(body: GitPushPullBody) -> Dict[str, Any]:
    root = _resolve_repo(body.path)
    # Detect current branch if needed for set-upstream
    branch = body.branch
    if body.set_upstream and not branch:
        rc_b, branch_out, _ = await _git(["rev-parse", "--abbrev-ref", "HEAD"], str(root))
        branch = branch_out.strip() if rc_b == 0 else "HEAD"

    args = ["push"]
    if body.set_upstream:
        args += ["--set-upstream", body.remote, branch]
    else:
        args.append(body.remote)
        if branch:
            args.append(branch)

    rc, out, err = await _git(args, str(root), timeout=30.0)
    if rc != 0:
        msg = (err or out).strip()
        # Detect no upstream branch error
        if "no upstream branch" in msg or "has no upstream branch" in msg:
            rc_b, branch_out, _ = await _git(["rev-parse", "--abbrev-ref", "HEAD"], str(root))
            cur_branch = branch_out.strip() if rc_b == 0 else "HEAD"
            raise HTTPException(status_code=422,
                                detail={"error": "no_upstream", "branch": cur_branch, "message": msg})
        # Detect remote repository not found
        if "repository" in msg.lower() and "not found" in msg.lower():
            raise HTTPException(status_code=422,
                                detail={"error": "repo_not_found", "message": msg})
        raise HTTPException(status_code=500, detail=msg)
    return {"message": (out or err).strip()}


@router.post("/git/pull")
async def git_pull(body: GitPushPullBody) -> Dict[str, Any]:
    root = _resolve_repo(body.path)
    args = ["pull", body.remote]
    if body.branch:
        args.append(body.branch)
    rc, out, err = await _git(args, str(root), timeout=30.0)
    if rc != 0:
        raise HTTPException(status_code=500, detail=(err or out).strip())
    return {"message": (out or err).strip()}


class GitHubCreateRepoBody(BaseModel):
    token: str
    name: str
    private: bool = True
    description: str = ""


@router.post("/github/create-repo")
async def github_create_repo(body: GitHubCreateRepoBody) -> Dict[str, Any]:
    """Create a new GitHub repository using the GitHub API."""
    import httpx
    if not body.token:
        raise HTTPException(status_code=400, detail="Token de GitHub requerido")
    if not body.name:
        raise HTTPException(status_code=400, detail="Nombre del repositorio requerido")

    payload = {"name": body.name, "private": body.private, "description": body.description, "auto_init": False}
    headers = {"Authorization": f"token {body.token}", "Accept": "application/vnd.github.v3+json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://api.github.com/user/repos", json=payload, headers=headers)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Error de red: {e}")

    if resp.status_code == 201:
        data = resp.json()
        return {"html_url": data["html_url"], "clone_url": data["clone_url"], "ssh_url": data["ssh_url"]}
    elif resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Token inválido o sin permisos")
    elif resp.status_code == 422:
        msg = resp.json().get("message", "El repositorio ya existe o nombre inválido")
        raise HTTPException(status_code=422, detail=msg)
    else:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:200])


@router.post("/git/config")
async def git_config_set(body: GitConfigBody) -> Dict[str, Any]:
    """Set local user.name and/or user.email."""
    root = _resolve_repo(body.path)
    updated = []
    if body.user_name:
        rc, _, err = await _git(["config", "user.name", body.user_name], str(root))
        if rc != 0:
            raise HTTPException(status_code=500, detail=err.strip())
        updated.append("user.name")
    if body.user_email:
        rc, _, err = await _git(["config", "user.email", body.user_email], str(root))
        if rc != 0:
            raise HTTPException(status_code=500, detail=err.strip())
        updated.append("user.email")
    return {"updated": updated}


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
