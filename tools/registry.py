"""Registro central de herramientas."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from core.models import ToolCall, ToolResult as ModelToolResult
from tools.base import BaseTool, ToolError, ToolResult
from tools.command import CommandValidator, RunCommandTool
from tools.filesystem import (
    CreateDirectoryTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)


# Patrón para extraer JSON de bloques de código
TOOL_JSON_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.IGNORECASE | re.DOTALL,
)


class ToolRegistry:
    """
    Registro central de herramientas.
    
    Maneja el registro, validación y ejecución de todas las herramientas
    disponibles para el agente.
    """
    
    # Herramientas disponibles (clase -> nombre)
    AVAILABLE_TOOLS: Dict[str, Type[BaseTool]] = {
        "read_file": ReadFileTool,
        "write_file": WriteFileTool,
        "list_directory": ListDirectoryTool,
        "create_directory": CreateDirectoryTool,
        "search_files": SearchFilesTool,
        "run_command": RunCommandTool,
    }
    
    def __init__(self, workspace_root: Path, current_cwd: Path):
        """
        Inicializa el registro.
        
        Args:
            workspace_root: Raíz del workspace
            current_cwd: Directorio de trabajo actual
        """
        self.workspace_root = workspace_root.resolve()
        self.current_cwd = current_cwd.resolve()
        self._instances: Dict[str, BaseTool] = {}
    
    def update_cwd(self, new_cwd: Path) -> None:
        """Actualiza el directorio de trabajo actual."""
        self.current_cwd = new_cwd.resolve()
        # Invalidar instancias para que se recreen con el nuevo cwd
        self._instances.clear()
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """
        Obtiene una instancia de herramienta por nombre.
        
        Args:
            name: Nombre de la herramienta
            
        Returns:
            Instancia de la herramienta o None si no existe
        """
        if name not in self.AVAILABLE_TOOLS:
            return None
        
        if name not in self._instances:
            tool_class = self.AVAILABLE_TOOLS[name]
            self._instances[name] = tool_class(
                workspace_root=self.workspace_root,
                current_cwd=self.current_cwd,
            )
        
        return self._instances[name]
    
    def list_tools(self) -> List[str]:
        """Lista los nombres de todas las herramientas disponibles."""
        return list(self.AVAILABLE_TOOLS.keys())
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Retorna las definiciones de todas las herramientas."""
        definitions = []
        for name in self.AVAILABLE_TOOLS:
            tool = self.get_tool(name)
            if tool:
                definitions.append(tool.to_dict())
        return definitions
    
    def get_tools_prompt(self) -> str:
        """Genera el texto de herramientas disponibles para el prompt."""
        lines = ["Herramientas disponibles:"]
        for name in sorted(self.AVAILABLE_TOOLS.keys()):
            tool = self.get_tool(name)
            if tool:
                lines.append(f"- {tool.get_signature()}: {tool.description}")
        return "\n".join(lines)
    
    def is_tool_write_operation(self, tool_call: ToolCall) -> bool:
        """
        Determina si una llamada a tool es una operación de escritura.
        
        Args:
            tool_call: Llamada a herramienta
            
        Returns:
            True si modifica el sistema
        """
        tool = self.get_tool(tool_call.tool)
        if not tool:
            return True  # Asumir write si no existe
        
        # Caso especial para run_command
        if tool_call.tool == "run_command":
            command = tool_call.args.get("command", "")
            return CommandValidator.is_write_command(command)
        
        return tool.is_write_operation
    
    def validate_tool_call(self, tool_call: ToolCall) -> Optional[str]:
        """
        Valida una llamada a herramienta.
        
        Args:
            tool_call: Llamada a validar
            
        Returns:
            Mensaje de error si es inválida, None si es válida
        """
        tool = self.get_tool(tool_call.tool)
        if not tool:
            return f"Herramienta no soportada: {tool_call.tool}"
        
        return tool.validate_args(tool_call.args)
    
    def execute(self, tool_call: ToolCall) -> ModelToolResult:
        """
        Ejecuta una llamada a herramienta.
        
        Args:
            tool_call: Llamada a ejecutar
            
        Returns:
            Resultado de la ejecución
        """
        tool = self.get_tool(tool_call.tool)
        if not tool:
            return ModelToolResult(
                tool_call=tool_call,
                success=False,
                output="",
                error=f"Herramienta no soportada: {tool_call.tool}",
            )
        
        # Validar argumentos
        validation_error = tool.validate_args(tool_call.args)
        if validation_error:
            return ModelToolResult(
                tool_call=tool_call,
                success=False,
                output="",
                error=validation_error,
            )
        
        # Ejecutar
        result = tool.execute(**tool_call.args)
        
        # Manejar cambio de cwd para run_command
        new_cwd = None
        if isinstance(tool, RunCommandTool) and tool.new_cwd:
            new_cwd = str(tool.new_cwd)
            self.update_cwd(tool.new_cwd)
        
        return ModelToolResult(
            tool_call=tool_call,
            success=result.success,
            output=result.output,
            error=result.error,
            new_cwd=new_cwd,
        )
    
    @staticmethod
    def extract_tool_call(text: str) -> Optional[ToolCall]:
        """
        Extrae una llamada a herramienta del texto del modelo.
        
        Args:
            text: Texto de respuesta del modelo
            
        Returns:
            ToolCall si se encontró, None si no
        """
        candidates = ToolRegistry._extract_json_candidates(text)
        
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            
            if not isinstance(data, dict):
                continue
            
            tool_name = data.get("tool")
            args = data.get("args", {})
            
            if not isinstance(tool_name, str):
                continue
            
            if tool_name not in ToolRegistry.AVAILABLE_TOOLS:
                continue
            
            if not isinstance(args, dict):
                continue
            
            return ToolCall(
                tool=tool_name,
                args=args,
                reasoning=data.get("reasoning", ""),
            )
        
        return None
    
    @staticmethod
    def _extract_json_candidates(text: str) -> List[str]:
        """Extrae posibles JSON del texto."""
        stripped = text.strip()
        if not stripped:
            return []
        
        candidates: List[str] = []
        
        # Buscar en bloques de código
        for match in TOOL_JSON_PATTERN.findall(text):
            candidate = match.strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        
        # Si el texto completo parece JSON
        if stripped.startswith("{") and stripped.endswith("}"):
            if stripped not in candidates:
                candidates.append(stripped)
        
        # Buscar JSON embebido
        decoder = json.JSONDecoder()
        for i, char in enumerate(text):
            if char != "{":
                continue
            try:
                parsed, consumed = decoder.raw_decode(text[i:])
                if isinstance(parsed, dict):
                    candidate = text[i:i + consumed].strip()
                    if candidate not in candidates:
                        candidates.append(candidate)
            except json.JSONDecodeError:
                continue
        
        return candidates
    
    @staticmethod
    def looks_like_tool_call(text: str) -> bool:
        """Determina si el texto parece contener una llamada a tool."""
        normalized = text.lower()
        
        if '"tool"' in normalized and '"args"' in normalized:
            return True
        
        if "{" not in normalized:
            return False
        
        return any(
            tool_name in normalized
            for tool_name in ToolRegistry.AVAILABLE_TOOLS
        )
