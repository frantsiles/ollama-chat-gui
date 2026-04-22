"""Gestor de servidores MCP y sus herramientas."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.mcp_client import MCPClient, MCPServerConfig, MCPToolDefinition, MCP_AVAILABLE


class MCPManager:
    """Gestiona múltiples servidores MCP y el inventario de sus herramientas.

    Patrón de uso:
        manager = MCPManager.get_instance()
        await manager.connect_server("mi-servidor")
        tools = manager.get_ollama_tools()
        result = await manager.execute_tool("mi-servidor__herramienta", {"arg": "val"})
    """

    _instance: Optional["MCPManager"] = None

    def __init__(self, config_file: Optional[str] = None) -> None:
        self._config_file = config_file
        self._servers: Dict[str, MCPServerConfig] = {}
        # Herramientas descubiertas: full_name -> MCPToolDefinition
        self._tools: Dict[str, MCPToolDefinition] = {}

        if config_file and Path(config_file).exists():
            self._load_config(config_file)

    @classmethod
    def get_instance(cls) -> "MCPManager":
        """Retorna la instancia singleton (debe inicializarse primero con init())."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def init(cls, config_file: str) -> "MCPManager":
        """Inicializa el singleton con archivo de configuración."""
        cls._instance = cls(config_file=config_file)
        return cls._instance

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self, path: str) -> None:
        try:
            with open(path, "r") as f:
                data = json.load(f)
            for server_data in data.get("servers", []):
                cfg = MCPServerConfig.from_dict(server_data)
                self._servers[cfg.name] = cfg
        except Exception as exc:
            print(f"[MCP] No se pudo cargar configuración desde '{path}': {exc}")

    def save_config(self) -> None:
        """Persiste la configuración de servidores en disco."""
        if not self._config_file:
            return
        try:
            data = {"servers": [s.to_dict() for s in self._servers.values()]}
            Path(self._config_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_file, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[MCP] Error guardando configuración: {exc}")

    # ------------------------------------------------------------------
    # Server management
    # ------------------------------------------------------------------

    def add_server(self, config: MCPServerConfig) -> None:
        """Agrega o actualiza un servidor."""
        self._servers[config.name] = config
        self.save_config()

    def remove_server(self, name: str) -> bool:
        """Elimina un servidor y sus herramientas descubiertas."""
        if name not in self._servers:
            return False
        del self._servers[name]
        self._tools = {k: v for k, v in self._tools.items() if v.server_name != name}
        self.save_config()
        return True

    def list_servers(self) -> List[Dict[str, Any]]:
        """Lista todos los servidores con su estado de conexión."""
        result = []
        for name, cfg in self._servers.items():
            server_tools = [t for t in self._tools.values() if t.server_name == name]
            result.append({
                **cfg.to_dict(),
                "connected": bool(server_tools),
                "tool_count": len(server_tools),
                "tools": [t.to_dict() for t in server_tools],
            })
        return result

    # ------------------------------------------------------------------
    # Connection & tool discovery
    # ------------------------------------------------------------------

    async def connect_server(self, name: str) -> List[MCPToolDefinition]:
        """Conecta al servidor y descubre sus herramientas."""
        cfg = self._servers.get(name)
        if not cfg:
            raise ValueError(f"Servidor MCP '{name}' no encontrado en la configuración")

        client = MCPClient(cfg)
        tools = await client.list_tools()

        # Limpiar herramientas anteriores del servidor y reemplazar
        self._tools = {k: v for k, v in self._tools.items() if v.server_name != name}
        for tool in tools:
            self._tools[tool.full_name] = tool

        return tools

    async def connect_all_enabled(self) -> Dict[str, Any]:
        """Conecta a todos los servidores habilitados. Retorna resumen."""
        summary: Dict[str, Any] = {}
        for name, cfg in self._servers.items():
            if not cfg.enabled:
                summary[name] = {"status": "disabled"}
                continue
            try:
                tools = await self.connect_server(name)
                summary[name] = {"status": "ok", "tools": len(tools)}
            except Exception as exc:
                summary[name] = {"status": "error", "error": str(exc)}
        return summary

    # ------------------------------------------------------------------
    # Tool access
    # ------------------------------------------------------------------

    def get_all_tools(self) -> List[MCPToolDefinition]:
        return list(self._tools.values())

    def get_ollama_tools(self) -> List[Dict[str, Any]]:
        """Retorna todas las herramientas MCP en formato Ollama function calling."""
        return [t.to_ollama_tool() for t in self._tools.values()]

    @property
    def has_tools(self) -> bool:
        return bool(self._tools)

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(self, full_name: str, arguments: Dict[str, Any]) -> str:
        """Ejecuta una herramienta MCP identificada por su nombre completo.

        Args:
            full_name: Formato 'servidor__herramienta'.
            arguments: Argumentos a pasar a la herramienta.
        """
        if "__" not in full_name:
            return f"Nombre de herramienta MCP inválido: '{full_name}' (esperado 'servidor__herramienta')"

        server_name, tool_name = full_name.split("__", 1)
        cfg = self._servers.get(server_name)
        if not cfg:
            return f"Servidor MCP '{server_name}' no encontrado"

        client = MCPClient(cfg)
        try:
            return await client.call_tool(tool_name, arguments)
        except Exception as exc:
            return f"Error ejecutando '{full_name}': {exc}"

    def execute_tool_sync(self, full_name: str, arguments: Dict[str, Any]) -> str:
        """Versión síncrona de execute_tool para usar desde código no-async."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run, self.execute_tool(full_name, arguments)
                    )
                    return future.result(timeout=60)
            else:
                return loop.run_until_complete(self.execute_tool(full_name, arguments))
        except Exception as exc:
            return f"Error ejecutando herramienta MCP '{full_name}': {exc}"
