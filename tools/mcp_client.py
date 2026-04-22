"""Cliente MCP para conectar con servidores externos de herramientas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


@dataclass
class MCPServerConfig:
    """Configuración de un servidor MCP."""
    name: str
    type: str  # "stdio" | "sse"
    command: Optional[str] = None        # Para tipo stdio: ejecutable
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None            # Para tipo sse: endpoint SSE
    enabled: bool = True
    description: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServerConfig":
        return cls(
            name=data["name"],
            type=data.get("type", "stdio"),
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url"),
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "url": self.url,
            "enabled": self.enabled,
            "description": self.description,
        }


@dataclass
class MCPToolDefinition:
    """Herramienta descubierta en un servidor MCP."""
    name: str
    description: str
    server_name: str
    input_schema: Dict[str, Any] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        """Nombre único con prefijo del servidor: 'servidor__herramienta'."""
        return f"{self.server_name}__{self.name}"

    def to_ollama_tool(self) -> Dict[str, Any]:
        """Convierte al formato de Ollama function calling."""
        schema = self.input_schema or {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.full_name,
                "description": f"[{self.server_name}] {self.description}",
                "parameters": schema,
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "description": self.description,
            "server_name": self.server_name,
            "input_schema": self.input_schema,
        }


class MCPClient:
    """Cliente para un único servidor MCP.

    Abre la conexión, lista herramientas y ejecuta llamadas.
    Cada operación abre una conexión fresca (stateless) para evitar
    problemas con event loops y procesos huérfanos.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config

    async def list_tools(self) -> List[MCPToolDefinition]:
        """Conecta al servidor y retorna las herramientas disponibles."""
        if not MCP_AVAILABLE:
            raise RuntimeError(
                "El paquete 'mcp' no está instalado. Ejecuta: pip install mcp"
            )

        tools: List[MCPToolDefinition] = []

        if self.config.type == "stdio":
            params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env or None,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    for t in result.tools:
                        tools.append(MCPToolDefinition(
                            name=t.name,
                            description=t.description or "",
                            server_name=self.config.name,
                            input_schema=getattr(t, "inputSchema", {}) or {},
                        ))

        elif self.config.type == "sse":
            if not self.config.url:
                raise ValueError(f"Servidor MCP '{self.config.name}' tipo SSE requiere 'url'")
            async with sse_client(self.config.url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    for t in result.tools:
                        tools.append(MCPToolDefinition(
                            name=t.name,
                            description=t.description or "",
                            server_name=self.config.name,
                            input_schema=getattr(t, "inputSchema", {}) or {},
                        ))
        else:
            raise ValueError(f"Tipo de servidor MCP no soportado: '{self.config.type}'")

        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Ejecuta una herramienta en el servidor y retorna el resultado como texto."""
        if not MCP_AVAILABLE:
            raise RuntimeError("El paquete 'mcp' no está instalado.")

        def _extract_text(result) -> str:
            if hasattr(result, "content"):
                parts = [item.text for item in result.content if hasattr(item, "text")]
                return "\n".join(parts) if parts else str(result)
            return str(result)

        if self.config.type == "stdio":
            params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env or None,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return _extract_text(result)

        elif self.config.type == "sse":
            async with sse_client(self.config.url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return _extract_text(result)

        return f"Error: tipo de servidor '{self.config.type}' no soportado"
