"""Sistema de RAG local para el workspace."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from config import (
    MAX_RAG_CHUNK_CHARS,
    MAX_RAG_CONTEXT_CHARS,
    MAX_RAG_FILE_CHARS,
    MAX_RAG_FILES,
    MAX_RAG_TOP_CHUNKS,
    RAG_IGNORED_DIRS,
    TEXT_FILE_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# Registro global de instancias (singleton por workspace)
# ---------------------------------------------------------------------------
_RAG_REGISTRY: dict[str, "LocalRAG"] = {}


def get_rag(workspace_root: Path) -> "LocalRAG":
    """
    Retorna la instancia de LocalRAG para el workspace dado.

    Crea una nueva instancia si no existe. Al reutilizar la misma instancia
    entre requests se aprovecha el caché de mtime sin re-escanear el disco.
    """
    key = str(workspace_root.resolve())
    if key not in _RAG_REGISTRY:
        _RAG_REGISTRY[key] = LocalRAG(workspace_root)
    return _RAG_REGISTRY[key]


# ---------------------------------------------------------------------------


class LocalRAG:
    """
    Sistema de RAG local para recuperar contexto del workspace.

    Usa búsqueda por tokens simples (bag of words) para encontrar
    chunks relevantes en los archivos del workspace.

    Incluye caché por mtime: si un archivo no ha cambiado desde la última
    lectura, se reutiliza el contenido en memoria sin volver a leer el disco.
    """

    # Términos que activan el RAG
    TRIGGER_TERMS = (
        "proyecto", "readme", "repo", "repository", "arquitectura",
        "repositorio", "análisis", "analisis", "analiza", "código",
        "codigo", "source", "fuente", "estructura", "codebase",
    )

    def __init__(self, workspace_root: Path):
        """
        Inicializa el sistema RAG.

        Args:
            workspace_root: Raíz del workspace
        """
        self.workspace_root = workspace_root.resolve()
        # caché por mtime: {str(path): (mtime_float, content_str)}
        self._mtime_cache: dict[str, tuple[float, str]] = {}
    
    def should_activate(self, user_prompt: str) -> bool:
        """
        Determina si el RAG debe activarse para este prompt.
        
        Args:
            user_prompt: Mensaje del usuario
            
        Returns:
            True si debe activarse
        """
        prompt_lower = user_prompt.lower()
        return any(term in prompt_lower for term in self.TRIGGER_TERMS)
    
    def _is_text_file(self, path: Path) -> bool:
        """Determina si un archivo es de texto."""
        if path.suffix.lower() in TEXT_FILE_EXTENSIONS:
            return True
        
        name_lower = path.name.lower()
        return name_lower in {
            "readme", "readme.md", "license", "licence",
            "pyproject.toml", "requirements.txt", "package.json",
            "makefile", "dockerfile", "docker-compose.yml",
            ".gitignore", ".env.example",
        }
    
    def _iter_candidate_files(self) -> List[Path]:
        """Itera sobre archivos candidatos para RAG."""
        files: List[Path] = []
        
        try:
            for path in self.workspace_root.rglob("*"):
                if len(files) >= MAX_RAG_FILES:
                    break
                
                # Saltar directorios ignorados
                if any(part in RAG_IGNORED_DIRS for part in path.parts):
                    continue
                
                if not path.is_file():
                    continue
                
                if not self._is_text_file(path):
                    continue
                
                files.append(path)
        except OSError:
            pass
        
        return files
    
    def _read_file_safely(self, path: Path, max_chars: int) -> Optional[str]:
        """
        Lee un archivo de texto de forma segura con caché por mtime.

        Si el archivo no ha cambiado desde la última lectura, devuelve
        el contenido cacheado sin acceder al disco.
        """
        try:
            mtime = path.stat().st_mtime
            key = str(path)
            cached = self._mtime_cache.get(key)
            if cached is not None and cached[0] == mtime:
                return cached[1][:max_chars]

            raw = path.read_bytes()
            for encoding in ("utf-8", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    self._mtime_cache[key] = (mtime, text)
                    return text[:max_chars]
                except UnicodeDecodeError:
                    continue

            return None
        except OSError:
            return None

    def clear_cache(self) -> None:
        """Vacía el caché de contenido de archivos."""
        self._mtime_cache.clear()
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokeniza texto en palabras."""
        return [
            t for t in re.findall(r"[a-zA-Z0-9_áéíóúñÁÉÍÓÚÑ]{3,}", text.lower())
        ]
    
    def _chunk_text(self, text: str, max_chars: int) -> List[str]:
        """Divide texto en chunks por párrafos."""
        chunks: List[str] = []
        current = ""
        
        for paragraph in text.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            # Si el párrafo es muy largo, dividirlo
            if len(paragraph) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                
                for i in range(0, len(paragraph), max_chars):
                    chunks.append(paragraph[i:i + max_chars])
                continue
            
            # Intentar agregar al chunk actual
            if not current:
                current = paragraph
                continue
            
            if len(current) + 2 + len(paragraph) <= max_chars:
                current = f"{current}\n\n{paragraph}"
            else:
                chunks.append(current)
                current = paragraph
        
        if current:
            chunks.append(current)
        
        return chunks
    
    def retrieve(
        self,
        query: str,
        max_chunks: int = MAX_RAG_TOP_CHUNKS,
        max_context_chars: int = MAX_RAG_CONTEXT_CHARS,
    ) -> Tuple[Optional[str], List[str]]:
        """
        Recupera contexto relevante del workspace.
        
        Args:
            query: Consulta del usuario
            max_chunks: Máximo de chunks a retornar
            max_context_chars: Máximo de caracteres de contexto
            
        Returns:
            Tupla (contexto_formateado, lista_de_fuentes)
        """
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return None, []
        
        # Recolectar chunks con score
        scored_chunks: List[Tuple[int, str, Path]] = []
        candidate_files = self._iter_candidate_files()
        
        for path in candidate_files:
            text = self._read_file_safely(path, MAX_RAG_FILE_CHARS)
            if not text:
                continue
            
            for chunk in self._chunk_text(text, MAX_RAG_CHUNK_CHARS):
                chunk_tokens = set(self._tokenize(chunk))
                overlap = len(query_tokens.intersection(chunk_tokens))
                
                if overlap <= 0:
                    continue
                
                # Bonus para README y archivos importantes
                bonus = 0
                name_lower = path.name.lower()
                if name_lower.startswith("readme"):
                    bonus = 3
                elif name_lower in {"pyproject.toml", "package.json"}:
                    bonus = 1
                
                score = overlap + bonus
                scored_chunks.append((score, chunk, path))
        
        if not scored_chunks:
            return None, []
        
        # Ordenar por score descendente
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored_chunks[:max_chunks]
        
        # Construir contexto
        context_blocks: List[str] = []
        source_paths: List[str] = []
        total_chars = 0
        
        for _, chunk, path in top_chunks:
            try:
                rel_path = str(path.relative_to(self.workspace_root))
            except ValueError:
                rel_path = str(path)
            
            block = f"[Fuente: {rel_path}]\n{chunk}"
            projected = total_chars + len(block) + 2
            
            if projected > max_context_chars:
                break
            
            context_blocks.append(block)
            total_chars = projected
            
            if rel_path not in source_paths:
                source_paths.append(rel_path)
        
        if not context_blocks:
            return None, []
        
        context = (
            "Contexto RAG recuperado del workspace:\n\n"
            + "\n\n".join(context_blocks)
        )
        
        return context, source_paths
    
    def get_file_context(
        self,
        file_path: str,
        max_chars: int = MAX_RAG_FILE_CHARS,
    ) -> Optional[str]:
        """
        Obtiene el contenido de un archivo específico.
        
        Args:
            file_path: Ruta relativa al archivo
            max_chars: Máximo de caracteres
            
        Returns:
            Contenido del archivo o None
        """
        try:
            full_path = self.workspace_root / file_path
            if not full_path.exists() or not full_path.is_file():
                return None
            
            return self._read_file_safely(full_path, max_chars)
        except (ValueError, OSError):
            return None
    
    def clear_cache(self) -> None:
        """Limpia la caché de archivos."""
        self._cache.clear()
