"""
SemanticRAG — punto de entrada principal para el RAG semántico.

Reemplaza LocalRAG como interfaz de recuperación de contexto:
- Búsqueda por similitud vectorial en workspace + KB
- Sugerencias proactivas basadas en el contexto de conversación
- Fallback transparente a LocalRAG si ChromaDB/embeddings no disponibles
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    EMBEDDING_ENABLED,
    MAX_RAG_CONTEXT_CHARS,
    RAG_PROACTIVE_COOLDOWN_TURNS,
    RAG_PROACTIVE_SCORE_THRESHOLD,
    RAG_SEMANTIC_TOP_K,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tipos de resultado
# ---------------------------------------------------------------------------

@dataclass
class ProactiveSuggestion:
    """Sugerencia proactiva de archivo/sección relevante."""
    path: str           # Ruta relativa al workspace
    score: float        # Similitud cosine (0-1)
    snippet: str        # Primeros chars del chunk más relevante
    reason: str = ""    # Explicación human-readable


# ---------------------------------------------------------------------------
# SemanticRAG
# ---------------------------------------------------------------------------

class SemanticRAG:
    """
    Sistema de RAG semántico para el workspace.

    Estrategia de retrieval:
    1. Intentar búsqueda semántica (ChromaDB + Ollama embeddings)
    2. Si no disponible → fallback a LocalRAG (bag-of-words)

    Sugerencias proactivas:
    - Se generan a partir del contexto reciente de la conversación
    - Respetan un cooldown configurable para no spamear
    - Solo se emiten si el score supera el threshold configurado
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self._ws_root_str = str(self.workspace_root)

        # Componentes lazy-inicializados
        self._store = None
        self._emb_client = None
        self._local_rag = None
        self._semantic_available: Optional[bool] = None

        # Estado para cooldown de sugerencias proactivas
        # clave: frozenset de paths sugeridos, valor: turns restantes de cooldown
        self._suggestion_cooldown: Dict[frozenset, int] = {}
        self._turn_counter: int = 0

    # ------------------------------------------------------------------
    # Inicialización lazy
    # ------------------------------------------------------------------

    def _init_semantic(self) -> bool:
        """Intenta inicializar los componentes semánticos."""
        if not EMBEDDING_ENABLED:
            return False
        try:
            from rag.embeddings import get_embedding_client
            from rag.vector_store import get_vector_store
            self._emb_client = get_embedding_client()
            self._store = get_vector_store(self._ws_root_str)
            return self._emb_client.available and self._store.available
        except Exception as exc:
            logger.warning("SemanticRAG: no se pudo inicializar modo semántico: %s", exc)
            return False

    @property
    def semantic_available(self) -> bool:
        if self._semantic_available is None:
            self._semantic_available = self._init_semantic()
            if self._semantic_available:
                logger.info("SemanticRAG: modo semántico activo (ChromaDB + %s)", 
                           self._emb_client.model if self._emb_client else "?")
            else:
                logger.info("SemanticRAG: usando fallback LocalRAG (bag-of-words)")
        return self._semantic_available

    def _get_local_rag(self):
        if self._local_rag is None:
            from rag.local_rag import LocalRAG
            self._local_rag = LocalRAG(self.workspace_root)
        return self._local_rag

    # ------------------------------------------------------------------
    # Retrieval principal
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = RAG_SEMANTIC_TOP_K,
        max_context_chars: int = MAX_RAG_CONTEXT_CHARS,
        include_kb: bool = True,
    ) -> Tuple[Optional[str], List[str]]:
        """
        Recupera contexto relevante para una query.

        Args:
            query: Texto de consulta
            top_k: Número máximo de chunks
            max_context_chars: Límite total de caracteres del contexto
            include_kb: Si True, también busca en la Knowledge Base externa

        Returns:
            Tupla (contexto_formateado, lista_de_fuentes)
            contexto_formateado es None si no se encontró nada relevante
        """
        if self.semantic_available:
            return self._retrieve_semantic(query, top_k, max_context_chars, include_kb)
        else:
            return self._get_local_rag().retrieve(query, max_chunks=top_k,
                                                   max_context_chars=max_context_chars)

    def _retrieve_semantic(
        self,
        query: str,
        top_k: int,
        max_context_chars: int,
        include_kb: bool,
    ) -> Tuple[Optional[str], List[str]]:
        from rag.embeddings import EmbeddingError

        try:
            vec = self._emb_client.embed(query)
        except EmbeddingError as exc:
            logger.warning("Error generando embedding para query: %s", exc)
            return self._get_local_rag().retrieve(query, max_chunks=top_k,
                                                   max_context_chars=max_context_chars)

        target = "all" if include_kb else "workspace"
        results = self._store.query(vec, top_k=top_k, target=target)

        if not results:
            return None, []

        context_blocks: List[str] = []
        source_paths: List[str] = []
        total_chars = 0

        for r in results:
            source = r.metadata.get("source", r.chunk_id)
            score_label = f"{r.score:.2f}"

            # Indicar origen (workspace vs KB)
            origin = r.metadata.get("type", "workspace")
            prefix = (
                f"[Fuente: {source} | similitud: {score_label}]"
                if origin != "kb_document"
                else f"[KB: {r.metadata.get('title', source)} | similitud: {score_label}]"
            )

            block = f"{prefix}\n{r.text}"
            projected = total_chars + len(block) + 2

            if projected > max_context_chars:
                break

            context_blocks.append(block)
            total_chars = projected

            if source not in source_paths:
                source_paths.append(source)

        if not context_blocks:
            return None, []

        context = (
            "Contexto RAG semántico recuperado:\n\n"
            + "\n\n".join(context_blocks)
        )
        return context, source_paths

    # ------------------------------------------------------------------
    # Sugerencias proactivas
    # ------------------------------------------------------------------

    def get_proactive_suggestions(
        self,
        recent_messages: List[str],
        top_k: int = 3,
    ) -> List[ProactiveSuggestion]:
        """
        Genera sugerencias proactivas de archivos relevantes para el contexto actual.

        Args:
            recent_messages: Lista de los últimos N mensajes (texto plano)
            top_k: Máximo de sugerencias a retornar

        Returns:
            Lista de ProactiveSuggestion (vacía si no hay nada relevante o en cooldown)
        """
        if not self.semantic_available or not recent_messages:
            return []

        self._turn_counter += 1

        # Actualizar cooldowns
        to_remove = [k for k, v in self._suggestion_cooldown.items() if v <= 0]
        for k in to_remove:
            del self._suggestion_cooldown[k]
        for k in self._suggestion_cooldown:
            self._suggestion_cooldown[k] -= 1

        # Construir contexto de conversación reciente
        context_text = " ".join(recent_messages[-4:])[:3000]

        from rag.embeddings import EmbeddingError
        try:
            vec = self._emb_client.embed(context_text)
        except EmbeddingError:
            return []

        # Buscar solo en workspace (no KB) para sugerencias de archivos
        results = self._store.query(vec, top_k=top_k * 2, target="workspace")

        suggestions: List[ProactiveSuggestion] = []
        seen_paths: set = set()

        for r in results:
            if r.score < RAG_PROACTIVE_SCORE_THRESHOLD:
                break  # results están ordenados, los siguientes tampoco pasarán

            source = r.metadata.get("source", "")
            if not source or source in seen_paths:
                continue
            seen_paths.add(source)

            snippet = r.text[:200].replace("\n", " ")
            suggestions.append(
                ProactiveSuggestion(
                    path=source,
                    score=round(r.score, 4),
                    snippet=snippet,
                    reason=self._build_reason(source, r.score),
                )
            )

            if len(suggestions) >= top_k:
                break

        if not suggestions:
            return []

        # Comprobar cooldown para este set de archivos
        path_set = frozenset(s.path for s in suggestions)
        if path_set in self._suggestion_cooldown:
            return []  # En cooldown, no repetir

        # Registrar cooldown
        self._suggestion_cooldown[path_set] = RAG_PROACTIVE_COOLDOWN_TURNS

        return suggestions

    def _build_reason(self, path: str, score: float) -> str:
        """Genera una explicación human-readable para la sugerencia."""
        pct = int(score * 100)
        parts = path.split("/")
        name = parts[-1] if parts else path
        if score >= 0.90:
            return f"`{name}` es muy relevante para el tema actual ({pct}% similitud)"
        elif score >= 0.80:
            return f"`{name}` puede contener información útil para este contexto ({pct}%)"
        else:
            return f"`{name}` podría estar relacionado con lo que discutimos ({pct}%)"

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def should_activate(self, user_prompt: str) -> bool:
        """
        En modo semántico siempre activamos (el score filtra la relevancia).
        En fallback LocalRAG, delegamos al trigger de keywords.
        """
        if self.semantic_available:
            return True
        return self._get_local_rag().should_activate(user_prompt)

    def trigger_reindex(self, force: bool = False) -> None:
        """Lanza una re-indexación del workspace en background."""
        if not self.semantic_available:
            return
        from rag.indexer import get_indexer
        indexer = get_indexer(self._ws_root_str)
        indexer.index_workspace_async(force=force)

    def ensure_indexed(self) -> None:
        """
        Inicia indexación en background si el workspace aún no está indexado.
        Se llama al iniciar una sesión; no bloquea el chat.
        """
        if not self.semantic_available:
            return
        chunk_count = self._store.count(target="workspace")
        if chunk_count == 0:
            logger.info("SemanticRAG: workspace sin indexar, lanzando indexación background...")
            self.trigger_reindex()
        else:
            logger.info("SemanticRAG: %d chunks ya indexados, omitiendo re-indexación", chunk_count)

    def status(self) -> Dict[str, Any]:
        """Retorna el estado actual del sistema semántico."""
        from rag.indexer import get_indexer_status
        idxr_status = get_indexer_status(self._ws_root_str)
        return {
            "semantic_available": self.semantic_available,
            "embedding_model": self._emb_client.model if self._emb_client else None,
            "workspace_chunks": self._store.count("workspace") if self._store else 0,
            "kb_chunks": self._store.count("kb") if self._store else 0,
            "indexer": {
                "is_running": idxr_status.is_running,
                "indexed_files": idxr_status.indexed_files,
                "total_files": idxr_status.total_files,
                "last_run": idxr_status.last_run,
                "error": idxr_status.error,
            },
        }


# ---------------------------------------------------------------------------
# Registry singleton por workspace
# ---------------------------------------------------------------------------
_SRAG_REGISTRY: Dict[str, SemanticRAG] = {}


def get_semantic_rag(workspace_root: str) -> SemanticRAG:
    """Retorna (o crea) la instancia de SemanticRAG para el workspace."""
    if workspace_root not in _SRAG_REGISTRY:
        _SRAG_REGISTRY[workspace_root] = SemanticRAG(Path(workspace_root))
    return _SRAG_REGISTRY[workspace_root]
