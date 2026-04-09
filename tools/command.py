"""Herramienta para ejecución de comandos del sistema."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    BLOCKED_COMMAND_PATTERNS,
    COMMAND_TIMEOUT_SECONDS,
    MAX_COMMAND_OUTPUT_CHARS,
    WRITE_COMMAND_OPERATORS,
    WRITE_COMMAND_PREFIXES,
    WRITE_GIT_SUBCOMMANDS,
)
from tools.base import BaseTool, ToolError, ToolParameter, ToolResult


class CommandValidator:
    """Validador de seguridad para comandos."""
    
    @staticmethod
    def validate(command: str) -> Optional[str]:
        """
        Valida un comando por seguridad.
        
        Args:
            command: Comando a validar
            
        Returns:
            Mensaje de error si es inválido, None si es válido
        """
        stripped = command.strip()
        
        if not stripped:
            return "Debes indicar un comando."
        
        if len(stripped) > 1200:
            return "Comando demasiado largo para ejecución segura."
        
        # Permitir cd simple
        if stripped in {"cd", "c..", "cd.."}:
            return None
        
        if stripped.startswith("cd "):
            try:
                tokens = shlex.split(stripped)
            except ValueError:
                return "Comando `cd` inválido."
            if tokens and tokens[0] == "cd" and len(tokens) <= 2:
                return None
        
        # Verificar patrones bloqueados
        for pattern, message in BLOCKED_COMMAND_PATTERNS:
            if pattern.search(stripped):
                return message
        
        return None
    
    @staticmethod
    def is_write_command(command: str) -> bool:
        """Determina si un comando modifica el sistema."""
        normalized = command.strip().lower()
        
        # Verificar operadores de escritura
        if any(op in normalized for op in WRITE_COMMAND_OPERATORS):
            return True
        
        try:
            tokens = shlex.split(command)
        except ValueError:
            return True  # Asumir que es write si no se puede parsear
        
        if not tokens:
            return False
        
        first = tokens[0].lower()
        
        # cd no es write
        if first == "cd":
            return False
        
        # Comandos que modifican
        if first in WRITE_COMMAND_PREFIXES:
            return True
        
        # Subcomandos de git que modifican
        if first == "git" and len(tokens) > 1:
            if tokens[1].lower() in WRITE_GIT_SUBCOMMANDS:
                return True
        
        return False


class RunCommandTool(BaseTool):
    """Herramienta para ejecutar comandos del sistema."""
    
    name = "run_command"
    description = "Ejecuta un comando en el workspace"
    is_write_operation = True  # Se determina dinámicamente
    
    def __init__(self, workspace_root: Path, current_cwd: Path):
        super().__init__(workspace_root, current_cwd)
        self._new_cwd: Optional[Path] = None
    
    @property
    def new_cwd(self) -> Optional[Path]:
        """Retorna el nuevo CWD si el comando fue cd."""
        return self._new_cwd
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="command",
                description="Comando a ejecutar",
                type="string",
                required=True,
            ),
        ]
    
    def _normalize_cd_command(self, command: str) -> str:
        """Normaliza variantes de cd."""
        stripped = command.strip()
        if stripped in {"c..", "cd.."}:
            return "cd .."
        return command
    
    def _handle_cd(self, command: str) -> ToolResult:
        """Maneja el comando cd especialmente."""
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Comando cd inválido: {e}",
            )
        
        if tokens[0] != "cd":
            raise ValueError("No es un comando cd")
        
        if len(tokens) > 2:
            return ToolResult(
                success=False,
                output="",
                error="El comando `cd` solo permite una ruta.",
            )
        
        target = tokens[1] if len(tokens) > 1 else "."
        target_path = Path(target).expanduser()
        
        if not target_path.is_absolute():
            target_path = self.current_cwd / target_path
        
        resolved = target_path.resolve()
        workspace = self.workspace_root.resolve()
        
        # Verificar que esté dentro del workspace
        try:
            if os.path.commonpath([str(workspace), str(resolved)]) != str(workspace):
                return ToolResult(
                    success=False,
                    output="",
                    error="Ruta fuera del workspace permitido.",
                )
        except ValueError:
            return ToolResult(
                success=False,
                output="",
                error="Ruta fuera del workspace permitido.",
            )
        
        if not resolved.exists() or not resolved.is_dir():
            return ToolResult(
                success=False,
                output="",
                error="La ruta indicada no existe o no es una carpeta.",
            )
        
        self._new_cwd = resolved
        
        try:
            rel = resolved.relative_to(workspace)
            rel_str = str(rel) if str(rel) != "." else "."
        except ValueError:
            rel_str = str(resolved)
        
        return ToolResult(
            success=True,
            output=f"CWD actualizado a `{rel_str}` ({resolved})",
            metadata={"new_cwd": str(resolved)},
        )
    
    def execute(self, command: str, **kwargs) -> ToolResult:
        self._new_cwd = None
        
        # Validar comando
        error = CommandValidator.validate(command)
        if error:
            return ToolResult(success=False, output="", error=error)
        
        # Normalizar
        command = self._normalize_cd_command(command)
        
        # Manejar cd especialmente
        try:
            tokens = shlex.split(command)
            if tokens and tokens[0] == "cd":
                return self._handle_cd(command)
        except ValueError:
            pass
        
        # Ejecutar comando normal
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.current_cwd,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"El comando superó el timeout de {COMMAND_TIMEOUT_SECONDS}s.",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error ejecutando comando: {e}",
            )
        
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        
        combined = (
            f"CWD: {self.current_cwd}\n"
            f"Comando: {command}\n"
            f"Exit code: {result.returncode}\n\n"
            f"STDOUT:\n{stdout or '[vacío]'}\n\n"
            f"STDERR:\n{stderr or '[vacío]'}"
        )
        
        if len(combined) > MAX_COMMAND_OUTPUT_CHARS:
            combined = combined[:MAX_COMMAND_OUTPUT_CHARS] + "\n...[salida recortada]..."
        
        return ToolResult(
            success=result.returncode == 0,
            output=combined,
            error=stderr if result.returncode != 0 else None,
            metadata={
                "exit_code": result.returncode,
                "cwd": str(self.current_cwd),
            },
        )
    
    def is_write_for_command(self, command: str) -> bool:
        """Determina si un comando específico es de escritura."""
        return CommandValidator.is_write_command(command)
