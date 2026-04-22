"""API REST para gestión de servidores y herramientas MCP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tools.mcp_client import MCPServerConfig, MCP_AVAILABLE
from tools.mcp_manager import MCPManager

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# =============================================================================
# Schemas
# =============================================================================

class ServerCreateRequest(BaseModel):
    name: str
    type: str = "stdio"           # "stdio" | "sse"
    command: Optional[str] = None
    args: List[str] = []
    env: Dict[str, str] = {}
    url: Optional[str] = None
    enabled: bool = True
    description: str = ""


class ServerUpdateRequest(BaseModel):
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/status")
async def mcp_status() -> Dict[str, Any]:
    """Retorna el estado general de MCP."""
    return {
        "available": MCP_AVAILABLE,
        "message": (
            "MCP listo" if MCP_AVAILABLE
            else "Instala el paquete 'mcp': pip install mcp"
        ),
    }


@router.get("/servers")
async def list_servers() -> List[Dict[str, Any]]:
    """Lista todos los servidores MCP configurados."""
    manager = MCPManager.get_instance()
    return manager.list_servers()


@router.post("/servers")
async def add_server(req: ServerCreateRequest) -> Dict[str, Any]:
    """Agrega un nuevo servidor MCP."""
    manager = MCPManager.get_instance()
    cfg = MCPServerConfig(
        name=req.name,
        type=req.type,
        command=req.command,
        args=req.args,
        env=req.env,
        url=req.url,
        enabled=req.enabled,
        description=req.description,
    )
    manager.add_server(cfg)
    return {"status": "ok", "server": cfg.to_dict()}


@router.patch("/servers/{name}")
async def update_server(name: str, req: ServerUpdateRequest) -> Dict[str, Any]:
    """Actualiza la configuración de un servidor existente."""
    manager = MCPManager.get_instance()
    servers = {s["name"]: s for s in manager.list_servers()}
    if name not in servers:
        raise HTTPException(status_code=404, detail=f"Servidor '{name}' no encontrado")

    existing = manager._servers[name]
    if req.command is not None:
        existing.command = req.command
    if req.args is not None:
        existing.args = req.args
    if req.env is not None:
        existing.env = req.env
    if req.url is not None:
        existing.url = req.url
    if req.enabled is not None:
        existing.enabled = req.enabled
    if req.description is not None:
        existing.description = req.description

    manager.save_config()
    return {"status": "ok", "server": existing.to_dict()}


@router.delete("/servers/{name}")
async def remove_server(name: str) -> Dict[str, Any]:
    """Elimina un servidor MCP y sus herramientas."""
    manager = MCPManager.get_instance()
    if not manager.remove_server(name):
        raise HTTPException(status_code=404, detail=f"Servidor '{name}' no encontrado")
    return {"status": "ok", "removed": name}


@router.post("/servers/{name}/connect")
async def connect_server(name: str) -> Dict[str, Any]:
    """Conecta al servidor y descubre sus herramientas."""
    if not MCP_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Paquete 'mcp' no instalado. Ejecuta: pip install mcp",
        )
    manager = MCPManager.get_instance()
    try:
        tools = await manager.connect_server(name)
        return {
            "status": "ok",
            "server": name,
            "tools": [t.to_dict() for t in tools],
            "tool_count": len(tools),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error conectando a '{name}': {exc}")


@router.post("/connect-all")
async def connect_all_servers() -> Dict[str, Any]:
    """Conecta a todos los servidores habilitados."""
    if not MCP_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Paquete 'mcp' no instalado. Ejecuta: pip install mcp",
        )
    manager = MCPManager.get_instance()
    summary = await manager.connect_all_enabled()
    return {"status": "ok", "results": summary}


@router.get("/tools")
async def list_tools() -> List[Dict[str, Any]]:
    """Lista todas las herramientas descubiertas en todos los servidores conectados."""
    manager = MCPManager.get_instance()
    return [t.to_dict() for t in manager.get_all_tools()]


@router.post("/tools/{full_name}/execute")
async def execute_tool(full_name: str, arguments: Dict[str, Any] = {}) -> Dict[str, Any]:
    """Ejecuta una herramienta MCP manualmente (para pruebas).

    full_name debe tener formato 'servidor__herramienta'.
    """
    if not MCP_AVAILABLE:
        raise HTTPException(status_code=503, detail="Paquete 'mcp' no instalado.")
    manager = MCPManager.get_instance()
    try:
        result = await manager.execute_tool(full_name, arguments)
        return {"status": "ok", "result": result}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
