"""Sandbox de seguridad para operaciones del agente."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from config import BLOCKED_COMMAND_PATTERNS


class SandboxError(Exception):
    """Error de violación del sandbox."""
    pass


class Sandbox:
    """
    Sandbox de seguridad para operaciones del agente.
    
    Proporciona validación de:
    - Rutas de archivos (dentro del workspace)
    - Comandos (patrones peligrosos)
    - Operaciones de escritura
    """
    
    def __init__(self, workspace_root: Path):
        """
        Inicializa el sandbox.
        
        Args:
            workspace_root: Raíz del workspace permitido
        """
        self.workspace_root = workspace_root.resolve()
    
    def validate_path(self, target: str, base_dir: Optional[Path] = None) -> Path:
        """
        Valida y resuelve una ruta dentro del workspace.
        
        Args:
            target: Ruta a validar
            base_dir: Directorio base para rutas relativas
            
        Returns:
            Path resuelto y validado
            
        Raises:
            SandboxError: Si la ruta está fuera del workspace
        """
        if not target or not target.strip():
            target = "."
        
        if base_dir is None:
            base_dir = self.workspace_root
        
        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = base_dir / target_path
        
        resolved = target_path.resolve()
        
        try:
            common = os.path.commonpath([str(self.workspace_root), str(resolved)])
            if common != str(self.workspace_root):
                raise SandboxError(
                    f"Ruta fuera del workspace permitido: {target}"
                )
        except ValueError:
            raise SandboxError(
                f"Ruta fuera del workspace permitido: {target}"
            )
        
        return resolved
    
    def validate_command(self, command: str) -> Tuple[bool, Optional[str]]:
        """
        Valida un comando por seguridad.
        
        Args:
            command: Comando a validar
            
        Returns:
            Tupla (es_válido, mensaje_error)
        """
        stripped = command.strip()
        
        if not stripped:
            return False, "Comando vacío."
        
        if len(stripped) > 1200:
            return False, "Comando demasiado largo."
        
        # Verificar patrones bloqueados
        for pattern, message in BLOCKED_COMMAND_PATTERNS:
            if pattern.search(stripped):
                return False, message
        
        return True, None
    
    def is_path_within_workspace(self, path: Path) -> bool:
        """Verifica si una ruta está dentro del workspace."""
        try:
            resolved = path.resolve()
            common = os.path.commonpath([str(self.workspace_root), str(resolved)])
            return common == str(self.workspace_root)
        except (ValueError, OSError):
            return False
    
    def get_relative_path(self, path: Path) -> str:
        """Obtiene la ruta relativa al workspace."""
        try:
            resolved = path.resolve()
            return str(resolved.relative_to(self.workspace_root))
        except ValueError:
            return str(path)
    
    def list_safe_entries(
        self,
        directory: Path,
        max_entries: int = 100,
        ignored_patterns: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Lista entradas de un directorio de forma segura.
        
        Args:
            directory: Directorio a listar
            max_entries: Máximo de entradas a retornar
            ignored_patterns: Patrones a ignorar
            
        Returns:
            Lista de nombres de entradas
        """
        if ignored_patterns is None:
            ignored_patterns = [".git", "__pycache__", ".venv", "node_modules"]
        
        if not self.is_path_within_workspace(directory):
            return []
        
        try:
            entries = []
            for item in directory.iterdir():
                if len(entries) >= max_entries:
                    break
                
                name = item.name
                if any(re.match(p, name) for p in ignored_patterns):
                    continue
                
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{name}{suffix}")
            
            return sorted(entries)
        except (PermissionError, OSError):
            return []
