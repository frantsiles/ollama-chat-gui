"""Herramientas para operaciones de sistema de archivos."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import List

from config import MAX_READ_CHARS, MAX_SCAN_RESULTS, RAG_IGNORED_DIRS
from tools.base import BaseTool, ToolError, ToolParameter, ToolResult


class PathResolver:
    """Utilidad para resolver y validar rutas dentro del workspace."""
    
    @staticmethod
    def resolve(
        workspace_root: Path,
        base_dir: Path,
        target: str,
    ) -> Path:
        """
        Resuelve una ruta asegurando que esté dentro del workspace.
        
        Args:
            workspace_root: Raíz del workspace
            base_dir: Directorio base para rutas relativas
            target: Ruta objetivo (relativa o absoluta)
            
        Returns:
            Path resuelto y validado
            
        Raises:
            ToolError: Si la ruta está fuera del workspace
        """
        if not target or not target.strip():
            target = "."
        
        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = base_dir / target_path
        
        resolved = target_path.resolve()
        workspace = workspace_root.resolve()
        
        try:
            if os.path.commonpath([str(workspace), str(resolved)]) != str(workspace):
                raise ToolError("Ruta fuera del workspace permitido.")
        except ValueError:
            # En Windows, commonpath puede fallar si las rutas están en diferentes drives
            raise ToolError("Ruta fuera del workspace permitido.")
        
        return resolved


class ReadFileTool(BaseTool):
    """Herramienta para leer contenido de archivos."""
    
    name = "read_file"
    description = "Lee el contenido de un archivo de texto"
    is_write_operation = False
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="path",
                description="Ruta al archivo (relativa al directorio actual)",
                type="string",
                required=True,
            ),
        ]
    
    def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            file_path = PathResolver.resolve(
                self.workspace_root, self.current_cwd, path
            )
            
            if not file_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"El archivo '{path}' no existe.",
                )
            
            if not file_path.is_file():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"'{path}' no es un archivo.",
                )
            
            # Leer con múltiples encodings
            raw = file_path.read_bytes()
            text = None
            for encoding in ("utf-8", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if text is None:
                return ToolResult(
                    success=False,
                    output="",
                    error="No se pudo decodificar el archivo como texto.",
                )
            
            # Truncar si es muy largo
            trimmed = text[:MAX_READ_CHARS]
            suffix = ""
            if len(text) > MAX_READ_CHARS:
                suffix = "\n...[contenido recortado]..."
            
            rel_path = file_path.relative_to(self.workspace_root)
            return ToolResult(
                success=True,
                output=f"Contenido de `{rel_path}`:\n\n{trimmed}{suffix}",
                metadata={"path": str(rel_path), "size": len(text)},
            )
            
        except ToolError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error leyendo archivo: {e}")


class WriteFileTool(BaseTool):
    """Herramienta para escribir contenido en archivos."""
    
    name = "write_file"
    description = "Escribe contenido en un archivo (crea si no existe)"
    is_write_operation = True
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="path",
                description="Ruta al archivo",
                type="string",
                required=True,
            ),
            ToolParameter(
                name="content",
                description="Contenido a escribir",
                type="string",
                required=True,
            ),
            ToolParameter(
                name="append",
                description="Si es true, agrega al final en lugar de sobrescribir",
                type="boolean",
                required=False,
                default=False,
            ),
        ]
    
    def execute(
        self,
        path: str,
        content: str,
        append: bool = False,
        **kwargs,
    ) -> ToolResult:
        try:
            file_path = PathResolver.resolve(
                self.workspace_root, self.current_cwd, path
            )
            
            # Crear directorios padre si no existen
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            mode = "a" if append else "w"
            with file_path.open(mode, encoding="utf-8") as f:
                f.write(content)
            
            rel_path = file_path.relative_to(self.workspace_root)
            action = "append" if append else "overwrite"
            
            return ToolResult(
                success=True,
                output=f"Escritura exitosa en `{rel_path}` (modo: {action}, chars: {len(content)}).",
                metadata={"path": str(rel_path), "mode": action, "chars": len(content)},
            )
            
        except ToolError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error escribiendo archivo: {e}")


class ListDirectoryTool(BaseTool):
    """Herramienta para listar contenido de directorios."""
    
    name = "list_directory"
    description = "Lista archivos y carpetas en un directorio"
    is_write_operation = False
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="path",
                description="Ruta al directorio",
                type="string",
                required=False,
                default=".",
            ),
            ToolParameter(
                name="recursive",
                description="Si es true, lista recursivamente",
                type="boolean",
                required=False,
                default=False,
            ),
        ]
    
    def execute(
        self,
        path: str = ".",
        recursive: bool = False,
        **kwargs,
    ) -> ToolResult:
        try:
            dir_path = PathResolver.resolve(
                self.workspace_root, self.current_cwd, path
            )
            
            if not dir_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"El directorio '{path}' no existe.",
                )
            
            if not dir_path.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"'{path}' no es un directorio.",
                )
            
            iterator = dir_path.rglob("*") if recursive else dir_path.glob("*")
            entries: List[str] = []
            
            for item in iterator:
                if len(entries) >= MAX_SCAN_RESULTS:
                    break
                
                # Saltar directorios ignorados
                if any(part in RAG_IGNORED_DIRS for part in item.parts):
                    continue
                
                try:
                    rel = item.relative_to(self.workspace_root)
                    suffix = "/" if item.is_dir() else ""
                    entries.append(f"{rel}{suffix}")
                except ValueError:
                    continue
            
            if not entries:
                rel_dir = dir_path.relative_to(self.workspace_root)
                return ToolResult(
                    success=True,
                    output=f"Directorio `{rel_dir}` está vacío.",
                    metadata={"path": str(rel_dir), "count": 0},
                )
            
            rel_dir = dir_path.relative_to(self.workspace_root)
            listing = "\n".join(f"- {entry}" for entry in sorted(entries))
            
            return ToolResult(
                success=True,
                output=(
                    f"Contenido de `{rel_dir}` "
                    f"(mostrando hasta {MAX_SCAN_RESULTS} resultados):\n{listing}"
                ),
                metadata={"path": str(rel_dir), "count": len(entries)},
            )
            
        except ToolError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error listando directorio: {e}")


class CreateDirectoryTool(BaseTool):
    """Herramienta para crear directorios."""
    
    name = "create_directory"
    description = "Crea un directorio (y sus padres si es necesario)"
    is_write_operation = True
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="path",
                description="Ruta del directorio a crear",
                type="string",
                required=True,
            ),
        ]
    
    def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            dir_path = PathResolver.resolve(
                self.workspace_root, self.current_cwd, path
            )
            
            dir_path.mkdir(parents=True, exist_ok=True)
            rel_path = dir_path.relative_to(self.workspace_root)
            
            return ToolResult(
                success=True,
                output=f"Directorio creado: `{rel_path}`",
                metadata={"path": str(rel_path)},
            )
            
        except ToolError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error creando directorio: {e}")


class SearchFilesTool(BaseTool):
    """Herramienta para buscar archivos por patrón."""
    
    name = "search_files"
    description = "Busca archivos que coincidan con un patrón glob"
    is_write_operation = False
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="pattern",
                description="Patrón glob (ej: '*.py', '**/*.md')",
                type="string",
                required=True,
            ),
            ToolParameter(
                name="path",
                description="Directorio donde buscar",
                type="string",
                required=False,
                default=".",
            ),
        ]
    
    def execute(
        self,
        pattern: str,
        path: str = ".",
        **kwargs,
    ) -> ToolResult:
        try:
            search_dir = PathResolver.resolve(
                self.workspace_root, self.current_cwd, path
            )
            
            if not search_dir.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"El directorio '{path}' no existe.",
                )
            
            if not search_dir.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"'{path}' no es un directorio.",
                )
            
            matches: List[str] = []
            for item in search_dir.rglob("*"):
                if len(matches) >= MAX_SCAN_RESULTS:
                    break
                
                if any(part in RAG_IGNORED_DIRS for part in item.parts):
                    continue
                
                if item.is_file() and fnmatch.fnmatch(item.name, pattern):
                    try:
                        rel = item.relative_to(self.workspace_root)
                        matches.append(str(rel))
                    except ValueError:
                        continue
            
            if not matches:
                return ToolResult(
                    success=True,
                    output=f"No se encontraron archivos que coincidan con '{pattern}'.",
                    metadata={"pattern": pattern, "count": 0},
                )
            
            listing = "\n".join(f"- {m}" for m in sorted(matches))
            return ToolResult(
                success=True,
                output=(
                    f"Archivos que coinciden con '{pattern}' "
                    f"(mostrando hasta {MAX_SCAN_RESULTS}):\n{listing}"
                ),
                metadata={"pattern": pattern, "count": len(matches)},
            )
            
        except ToolError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error buscando archivos: {e}")
