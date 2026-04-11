"""
Abstracción sobre ChromaDB para el RAG semántico.

Dos colecciones:
- workspace_{workspace_id}  : chunks indexados del workspace local
- knowledge_base            : documentos externos (URLs, markdown, texto)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import CHROMA_DB_PATH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """Un fragmento de texto con su embedding y metadatos."""
    id: str
    text: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryResult:
    """Resultado de una búsqueda semántica."""
    chunk_id: str
    text: str
    score: float          # similitud cosine (0-1, 1 = idéntico)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _workspace_collection_name(workspace_root: str) -> str:
    """Nombre de colección única por workspace (ChromaDB limita a [a-zA-Z0-9_-])."""
    h = hashlib.md5(workspace_root.encode()).hexdigest()[:12]
    return f"ws_{h}"


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------

class VectorStore:
    """
    Wrapper de ChromaDB con dos colecciones independientes.

    Características:
    - Persistencia en disco configurable via CHROMA_DB_PATH
    - Método `upsert_chunks` con IDs deterministas (no duplica si se llama 2 veces)
    - Scores normalizados (ChromaDB retorna distancias, se convierten a similitud)
    - Manejo limpio de errores si ChromaDB no está instalado
    """

    _KNOWLEDGE_BASE_COLLECTION = "knowledge_base"

    def __init__(
        self,
        persist_dir: Path = CHROMA_DB_PATH,
        workspace_root: Optional[str] = None,
    ) -> None:
        self._persist_dir = persist_dir
        self._workspace_root = workspace_root
        self._client = None
        self._ws_collection = None
        self._kb_collection = None
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Inicialización lazy
    # ------------------------------------------------------------------

    def _init(self) -> bool:
        """Inicializa ChromaDB. Retorna True si tuvo éxito."""
        if self._client is not None:
            return True
        try:
            import chromadb  # type: ignore
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            logger.info("ChromaDB inicializado en %s", self._persist_dir)
            return True
        except ImportError:
            logger.warning("chromadb no está instalado. RAG semántico no disponible.")
            return False
        except Exception as exc:
            logger.error("Error al inicializar ChromaDB: %s", exc)
            return False

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = self._init()
        return self._available

    def _get_ws_collection(self):
        """Obtiene (o crea) la colección del workspace actual."""
        if not self.available:
            return None
        if self._ws_collection is None:
            name = _workspace_collection_name(self._workspace_root or "default")
            self._ws_collection = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._ws_collection

    def _get_kb_collection(self):
        """Obtiene (o crea) la colección de knowledge base."""
        if not self.available:
            return None
        if self._kb_collection is None:
            self._kb_collection = self._client.get_or_create_collection(
                name=self._KNOWLEDGE_BASE_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        return self._kb_collection

    # ------------------------------------------------------------------
    # Operaciones sobre workspace
    # ------------------------------------------------------------------

    def upsert_chunks(self, chunks: List[Chunk], target: str = "workspace") -> int:
        """
        Inserta o actualiza chunks en la colección indicada.

        Args:
            chunks: Lista de Chunk a insertar/actualizar
            target: "workspace" o "kb"

        Returns:
            Número de chunks procesados
        """
        collection = (
            self._get_ws_collection() if target == "workspace"
            else self._get_kb_collection()
        )
        if collection is None or not chunks:
            return 0

        try:
            collection.upsert(
                ids=[c.id for c in chunks],
                embeddings=[c.embedding for c in chunks],
                documents=[c.text for c in chunks],
                metadatas=[c.metadata for c in chunks],
            )
            return len(chunks)
        except Exception as exc:
            logger.error("Error en upsert_chunks: %s", exc)
            return 0

    def delete_by_source(self, source_path: str, target: str = "workspace") -> int:
        """
        Elimina todos los chunks asociados a una ruta/fuente.

        Args:
            source_path: Valor del campo 'source' en los metadatos
            target: "workspace" o "kb"

        Returns:
            Número de chunks eliminados
        """
        collection = (
            self._get_ws_collection() if target == "workspace"
            else self._get_kb_collection()
        )
        if collection is None:
            return 0

        try:
            results = collection.get(where={"source": source_path})
            ids = results.get("ids", [])
            if ids:
                collection.delete(ids=ids)
            return len(ids)
        except Exception as exc:
            logger.error("Error en delete_by_source: %s", exc)
            return 0

    def query(
        self,
        embedding: List[float],
        top_k: int = 6,
        target: str = "workspace",
        where: Optional[Dict[str, Any]] = None,
    ) -> List[QueryResult]:
        """
        Búsqueda por similitud cosine.

        Args:
            embedding: Vector de consulta
            top_k: Número máximo de resultados
            target: "workspace", "kb" o "all" (busca en ambas)
            where: Filtro de metadatos adicional (ChromaDB where clause)

        Returns:
            Lista de QueryResult ordenada por score descendente
        """
        collections = []
        if target in ("workspace", "all"):
            c = self._get_ws_collection()
            if c:
                collections.append(c)
        if target in ("kb", "all"):
            c = self._get_kb_collection()
            if c:
                collections.append(c)

        if not collections:
            return []

        results: List[QueryResult] = []

        for collection in collections:
            try:
                count = collection.count()
                if count == 0:
                    continue

                actual_k = min(top_k, count)
                kwargs: Dict[str, Any] = {
                    "query_embeddings": [embedding],
                    "n_results": actual_k,
                    "include": ["documents", "distances", "metadatas"],
                }
                if where:
                    kwargs["where"] = where

                raw = collection.query(**kwargs)

                docs = raw.get("documents", [[]])[0]
                distances = raw.get("distances", [[]])[0]
                metas = raw.get("metadatas", [[]])[0]
                ids = raw.get("ids", [[]])[0]

                for doc, dist, meta, chunk_id in zip(docs, distances, metas, ids):
                    # ChromaDB cosine distance: 0 = idéntico, 2 = opuesto
                    # Convertir a similitud [0, 1]
                    score = max(0.0, 1.0 - dist / 2.0)
                    results.append(
                        QueryResult(
                            chunk_id=chunk_id,
                            text=doc,
                            score=score,
                            metadata=meta or {},
                        )
                    )
            except Exception as exc:
                logger.error("Error en query collection: %s", exc)

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def list_sources(self, target: str = "workspace") -> List[Dict[str, Any]]:
        """
        Lista fuentes únicas indexadas en la colección.

        Returns:
            Lista de dicts con 'source', 'chunk_count', y metadatos extra
        """
        collection = (
            self._get_ws_collection() if target == "workspace"
            else self._get_kb_collection()
        )
        if collection is None:
            return []

        try:
            all_items = collection.get(include=["metadatas"])
            metas = all_items.get("metadatas", [])
            source_map: Dict[str, Dict[str, Any]] = {}
            for meta in metas:
                if not meta:
                    continue
                src = meta.get("source", "unknown")
                if src not in source_map:
                    source_map[src] = {**meta, "chunk_count": 0}
                source_map[src]["chunk_count"] += 1
            return list(source_map.values())
        except Exception as exc:
            logger.error("Error en list_sources: %s", exc)
            return []

    def count(self, target: str = "workspace") -> int:
        """Número de chunks en la colección."""
        collection = (
            self._get_ws_collection() if target == "workspace"
            else self._get_kb_collection()
        )
        if collection is None:
            return 0
        try:
            return collection.count()
        except Exception:
            return 0

    def delete_collection(self, target: str = "workspace") -> bool:
        """Elimina completamente una colección (útil para reindexar desde cero)."""
        if not self.available:
            return False
        try:
            if target == "workspace":
                name = _workspace_collection_name(self._workspace_root or "default")
                self._client.delete_collection(name)
                self._ws_collection = None
            else:
                self._client.delete_collection(self._KNOWLEDGE_BASE_COLLECTION)
                self._kb_collection = None
            return True
        except Exception as exc:
            logger.error("Error eliminando colección: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Singleton por workspace
# ---------------------------------------------------------------------------
_STORE_REGISTRY: Dict[str, VectorStore] = {}


def get_vector_store(workspace_root: str) -> VectorStore:
    """Retorna (o crea) el VectorStore singleton para el workspace indicado."""
    if workspace_root not in _STORE_REGISTRY:
        _STORE_REGISTRY[workspace_root] = VectorStore(workspace_root=workspace_root)
    return _STORE_REGISTRY[workspace_root]
