"""REST API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile
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

def _load_gitignore_patterns(directory: Path) -> list[str]:
    """Return gitignore patterns found in directory (simple glob patterns only)."""
    gi = directory / ".gitignore"
    patterns: list[str] = []
    if gi.is_file():
        try:
            for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line.rstrip("/"))
        except OSError:
            pass
    return patterns


def _matches_gitignore(name: str, patterns: list[str]) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(name, p) for p in patterns)


@router.get("/files")
async def list_files(
    path: str = "",
    show_hidden: bool = False,
    use_gitignore: bool = True,
) -> Dict[str, Any]:
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

    gi_patterns = _load_gitignore_patterns(target) if use_gitignore else []

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                is_hidden = entry.name.startswith(".")
                if is_hidden and not show_hidden:
                    continue
                if use_gitignore and _matches_gitignore(entry.name, gi_patterns):
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                stat = entry.stat(follow_symlinks=False)
                items.append({
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

    parent = str(target.parent) if target != target.parent else None

    return {
        "path": str(target),
        "parent": parent,
        "items": items,
    }


# =============================================================================
# File CRUD
# =============================================================================

class FileCreateBody(BaseModel):
    path: str
    content: str = ""

class DirCreateBody(BaseModel):
    path: str

class RenameBody(BaseModel):
    path: str
    new_name: str

class DeleteBody(BaseModel):
    path: str

class DuplicateBody(BaseModel):
    path: str


@router.post("/files/create")
async def create_file(body: FileCreateBody) -> Dict[str, Any]:
    """Crea un nuevo archivo de texto."""
    try:
        target = Path(body.path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
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
    try:
        target = Path(body.path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
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
    try:
        src = Path(body.path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
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
async def delete_entry(path: str) -> Dict[str, Any]:
    """Elimina un archivo o directorio (recursivo)."""
    try:
        target = Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
    if not target.exists():
        raise HTTPException(status_code=404, detail="No encontrado")
    try:
        import shutil
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado")
    return {"deleted": str(target)}


@router.post("/files/duplicate")
async def duplicate_entry(body: DuplicateBody) -> Dict[str, Any]:
    """Duplica un archivo o directorio con sufijo '_copia'."""
    try:
        src = Path(body.path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
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


@router.post("/files/move")
async def move_entry(body: MoveBody) -> Dict[str, Any]:
    """Mueve un archivo o directorio a otro directorio."""
    try:
        src = Path(body.src_path).expanduser().resolve()
        dst_dir = Path(body.dst_dir).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
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


@router.post("/files/upload")
async def upload_files(
    dir: str,
    files: list[UploadFile] = FastAPIFile(...),
) -> Dict[str, Any]:
    """Sube uno o más archivos a un directorio del workspace."""
    try:
        target_dir = Path(dir).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="El directorio no existe")

    saved = []
    for uf in files:
        name = Path(uf.filename or "upload").name  # strip any path traversal
        dest = target_dir / name
        # avoid collisions
        counter = 1
        stem, suffix = dest.stem, dest.suffix
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
async def search_files(path: str = "", q: str = "") -> Dict[str, Any]:
    """Busca archivos por nombre (fuzzy) dentro de un directorio."""
    if not q:
        return {"items": []}
    if not path:
        path = str(Path.home())

    try:
        root = Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if not root.is_dir():
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    q_lower = q.lower()
    results: list[Dict[str, Any]] = []
    MAX_RESULTS = 50

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
    return {"items": results}


# =============================================================================
# File Grep (search in content)
# =============================================================================

@router.get("/files/grep")
async def grep_files(
    path: str = "",
    q: str = "",
    case_sensitive: bool = False,
) -> Dict[str, Any]:
    """Busca texto en el contenido de archivos del workspace."""
    if not q:
        return {"groups": []}
    if not path:
        path = str(Path.home())

    try:
        root = Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if not root.is_dir():
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    import mimetypes, re as _re

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
            # Try by extension whitelist
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
                                "line": line[:200],  # truncate long lines
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
    return {"groups": groups, "total_files": len(groups)}


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
