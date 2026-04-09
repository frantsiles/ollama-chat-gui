"""Clase base abstracta para herramientas del agente."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


class ToolError(Exception):
    """Error durante la ejecución de una herramienta."""
    pass


@dataclass
class ToolParameter:
    """Definición de un parámetro de herramienta."""
    name: str
    description: str
    type: str  # string, boolean, integer, etc.
    required: bool = True
    default: Any = None


@dataclass
class ToolResult:
    """Resultado de ejecución de una herramienta."""
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseTool(ABC):
    """Clase base abstracta para todas las herramientas."""
    
    # Propiedades que cada tool debe definir
    name: str = ""
    description: str = ""
    is_write_operation: bool = False  # True si modifica el sistema
    
    def __init__(self, workspace_root: Path, current_cwd: Path):
        """
        Inicializa la herramienta.
        
        Args:
            workspace_root: Raíz del workspace (límite de seguridad)
            current_cwd: Directorio de trabajo actual
        """
        self.workspace_root = workspace_root.resolve()
        self.current_cwd = current_cwd.resolve()
    
    @abstractmethod
    def get_parameters(self) -> List[ToolParameter]:
        """Retorna la lista de parámetros que acepta la herramienta."""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        Ejecuta la herramienta con los argumentos dados.
        
        Returns:
            ToolResult con el resultado de la ejecución
        """
        pass
    
    def validate_args(self, args: Dict[str, Any]) -> Optional[str]:
        """
        Valida los argumentos antes de ejecutar.
        
        Args:
            args: Diccionario de argumentos
            
        Returns:
            Mensaje de error si la validación falla, None si es válido
        """
        params = {p.name: p for p in self.get_parameters()}
        
        # Verificar parámetros requeridos
        for name, param in params.items():
            if param.required and name not in args:
                return f"Parámetro requerido '{name}' no proporcionado."
        
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serializa la definición de la herramienta."""
        return {
            "name": self.name,
            "description": self.description,
            "is_write_operation": self.is_write_operation,
            "parameters": [
                {
                    "name": p.name,
                    "description": p.description,
                    "type": p.type,
                    "required": p.required,
                    "default": p.default,
                }
                for p in self.get_parameters()
            ],
        }
    
    def get_signature(self) -> str:
        """Retorna la firma de la herramienta para el prompt."""
        params = self.get_parameters()
        param_strs = []
        for p in params:
            if p.required:
                param_strs.append(p.name)
            elif p.default is not None:
                param_strs.append(f"{p.name}={p.default!r}")
            else:
                param_strs.append(f"{p.name}=None")
        
        return f"{self.name}({', '.join(param_strs)})"
    
    def __str__(self) -> str:
        return f"Tool({self.name})"
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
