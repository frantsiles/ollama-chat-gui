"""
WorkspaceIndexer — indexación incremental del workspace en ChromaDB.

Características:
- Reutiliza la lógica de escaneo y chunking de LocalRAG
- Indexación incremental: solo re-indexa archivos cuyo mtime cambió
- Ejecuta en thread background sin bloquear el chat
- Expone progress callbacks opcionales
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config import (
    MAX_RAG_CHUNK_CHARS,
    MAX_RAG_FILE_CHARS,
    MAX_RAG_FILES,
    RAG_IGNORED_DIRS,
    TEXT_FILE_EXTENSIONS,
)
from rag.embeddings import EmbeddingClient, EmbeddingError, get_embedding_client
from rag.vector_store import Chunk, VectorStore, get_vector_store

logger = logging.getLogger(__name__)

# Tipo para el callback de progreso: (indexed, total, current_file)
ProgressCallback = Callable[[int, int, str], None]


# ---------------------------------------------------------------------------
# Estado del indexador por workspace
# ---------------------------------------------------------------------------

@dataclass
class IndexerStatus:
    """Estado actual del indexador para un workspace."""
    workspace_root: str
    is_running: bool = False
    indexed_files: int = 0
    total_files: int = 0
    indexed_chunks: int = 0
    last_run: Optional[str] = None
    error: Optional[str] = None
    # mtime cache: {str(path): mtime_float}
    _mtime_index: Dict[str, float] = field(default_factory=dict)


# Registro global de estados por workspace
_STATUS_REGISTRY: Dict[str, IndexerStatus] = {}
# Lock global para evitar indexaciones concurrentes del mismo workspace
_LOCKS: Dict[str, threading.Lock] = {}


def _get_lock(workspace_root: str) -> threading.Lock:
    if workspace_root not in _LOCKS:
        _LOCKS[workspace_root] = threading.Lock()
    return _LOCKS[workspace_root]


def get_indexer_status(workspace_root: str) -> IndexerStatus:
    if workspace_root not in _STATUS_REGISTRY:
        _STATUS_REGISTRY[workspace_root] = IndexerStatus(workspace_root=workspace_root)
    return _STATUS_REGISTRY[workspace_root]


# ---------------------------------------------------------------------------
# Helpers de chunking/tokenización (espejo de LocalRAG)
# ---------------------------------------------------------------------------

def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_FILE_EXTENSIONS:
        return True
    name_lower = path.name.lower()
    return name_lower in {
        "readme", "readme.md", "license", "licence",
        "pyproject.toml", "requirements.txt", "package.json",
        "makefile", "dockerfile", "docker-compose.yml",
        ".gitignore", ".env.example",
    }


def _iter_candidate_files(workspace_root: Path) -> List[Path]:
    files: List[Path] = []
    try:
        for path in workspace_root.rglob("*"):
            if len(files) >= MAX_RAG_FILES:
                break
            if any(part in RAG_IGNORED_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            if not _is_text_file(path):
                continue
            files.append(path)
    except OSError:
        pass
    return files


def _read_file(path: Path, max_chars: int = MAX_RAG_FILE_CHARS) -> Optional[str]:
    try:
        raw = path.read_bytes()
        for enc in ("utf-8", "latin-1"):
            try:
                return raw.decode(enc)[:max_chars]
            except UnicodeDecodeError:
                continue
        return None
    except OSError:
        return None


def _chunk_text(text: str, max_chars: int = MAX_RAG_CHUNK_CHARS) -> List[str]:
    chunks: List[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[i:i + max_chars])
            continue
        if not current:
            current = paragraph
        elif len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _chunk_id(source: str, chunk_index: int, text: str) -> str:
    """ID determinista para un chunk: no duplica si el texto no cambió."""
    digest = hashlib.md5(f"{source}:{chunk_index}:{text}".encode()).hexdigest()[:16]
    return digest


# ---------------------------------------------------------------------------
# WorkspaceIndexer
# ---------------------------------------------------------------------------

class WorkspaceIndexer:
    """
    Indexa archivos del workspace de forma incremental en ChromaDB.

    Uso:
        indexer = WorkspaceIndexer(workspace_root, store, emb_client)
        indexer.index_workspace()               # bloqueante
        indexer.index_workspace_async()         # background thread
    """

    def __init__(
        self,
        workspace_root: Path,
        store: Optional[VectorStore] = None,
        emb_client: Optional[EmbeddingClient] = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.store = store or get_vector_store(str(self.workspace_root))
        self.emb_client = emb_client or get_embedding_client()
        self.status = get_indexer_status(str(self.workspace_root))

    # ------------------------------------------------------------------
    # Indexación principal
    # ------------------------------------------------------------------

    def index_workspace(
        self,
        force: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> IndexerStatus:
        """
        Indexa (o actualiza) todos los archivos del workspace.

        Args:
            force: Si True, re-indexa todos los archivos aunque no hayan cambiado
            progress_cb: Callback opcional con (indexed, total, current_file)

        Returns:
            Estado final del indexador
        """
        lock = _get_lock(str(self.workspace_root))
        if not lock.acquire(blocking=False):
            logger.info("Indexador ya en ejecución para %s", self.workspace_root)
            return self.status

        try:
            return self._do_index(force=force, progress_cb=progress_cb)
        finally:
            lock.release()

    def _do_index(
        self,
        force: bool,
        progress_cb: Optional[ProgressCallback],
    ) -> IndexerStatus:
        status = self.status
        status.is_running = True
        status.error = None

        if not self.store.available:
            status.is_running = False
            status.error = "ChromaDB no disponible"
            return status

        if not self.emb_client.available:
            status.is_running = False
            status.error = f"Modelo de embeddings '{self.emb_client.model}' no disponible"
            return status

        files = _iter_candidate_files(self.workspace_root)
        status.total_files = len(files)
        status.indexed_files = 0
        status.indexed_chunks = 0

        logger.info("Indexando %d archivos en %s", len(files), self.workspace_root)

        for i, path in enumerate(files):
            rel = str(path.relative_to(self.workspace_root))

            # Comprobar mtime
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue

            if not force and status._mtime_index.get(str(path)) == mtime:
                # Sin cambios, saltar
                if progress_cb:
                    progress_cb(i + 1, len(files), rel)
                continue

            # Leer y trocear
            text = _read_file(path)
            if not text:
                continue

            chunks_text = _chunk_text(text)
            if not chunks_text:
                continue

            # Generar embeddings y construir Chunk objects
            chunks_to_upsert: List[Chunk] = []
            for idx, chunk_text in enumerate(chunks_text):
                try:
                    vec = self.emb_client.embed(chunk_text)
                except EmbeddingError as exc:
                    logger.warning("Error embeddando chunk de %s: %s", rel, exc)
                    break

                chunk_id = _chunk_id(rel, idx, chunk_text)
                chunks_to_upsert.append(
                    Chunk(
                        id=chunk_id,
                        text=chunk_text,
                        embedding=vec,
                        metadata={
                            "source": rel,
                            "workspace": str(self.workspace_root),
                            "mtime": mtime,
                            "chunk_index": idx,
                        },
                    )
                )

            if chunks_to_upsert:
                # Eliminar chunks viejos del mismo archivo antes de upsert
                self.store.delete_by_source(rel, target="workspace")
                n = self.store.upsert_chunks(chunks_to_upsert, target="workspace")
                status.indexed_chunks += n
                status._mtime_index[str(path)] = mtime

            status.indexed_files += 1

            if progress_cb:
                progress_cb(status.indexed_files, len(files), rel)

        from datetime import datetime
        status.last_run = datetime.now().isoformat()
        status.is_running = False

        logger.info(
            "Indexación completada: %d archivos, %d chunks",
            status.indexed_files,
            status.indexed_chunks,
        )
        return status

    # ------------------------------------------------------------------
    # Indexación de un archivo individual
    # ------------------------------------------------------------------

    def reindex_file(self, path: Path) -> int:
        """
        Re-indexa un archivo específico.

        Returns:
            Número de chunks indexados (0 si falló)
        """
        if not self.store.available or not self.emb_client.available:
            return 0

        try:
            rel = str(path.relative_to(self.workspace_root))
        except ValueError:
            rel = str(path)

        text = _read_file(path)
        if not text:
            self.store.delete_by_source(rel, target="workspace")
            return 0

        chunks_text = _chunk_text(text)
        chunks_to_upsert: List[Chunk] = []

        for idx, chunk_text in enumerate(chunks_text):
            try:
                vec = self.emb_client.embed(chunk_text)
            except EmbeddingError:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            chunk_id = _chunk_id(rel, idx, chunk_text)
            chunks_to_upsert.append(
                Chunk(
                    id=chunk_id,
                    text=chunk_text,
                    embedding=vec,
                    metadata={
                        "source": rel,
                        "workspace": str(self.workspace_root),
                        "mtime": mtime,
                        "chunk_index": idx,
                    },
                )
            )

        self.store.delete_by_source(rel, target="workspace")
        if chunks_to_upsert:
            return self.store.upsert_chunks(chunks_to_upsert, target="workspace")
        return 0

    # ------------------------------------------------------------------
    # Indexación asíncrona (background thread)
    # ------------------------------------------------------------------

    def index_workspace_async(
        self,
        force: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        done_cb: Optional[Callable[[IndexerStatus], None]] = None,
    ) -> threading.Thread:
        """
        Lanza la indexación en un thread background.

        Args:
            force: Si True, re-indexa todo
            progress_cb: Callback de progreso (seguro para llamar desde thread)
            done_cb: Callback al terminar con el IndexerStatus final

        Returns:
            El Thread lanzado (daemon=True)
        """
        def _run() -> None:
            result = self.index_workspace(force=force, progress_cb=progress_cb)
            if done_cb:
                done_cb(result)

        t = threading.Thread(target=_run, daemon=True, name=f"indexer-{self.workspace_root.name}")
        t.start()
        return t


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_INDEXER_REGISTRY: Dict[str, WorkspaceIndexer] = {}


def get_indexer(workspace_root: str) -> WorkspaceIndexer:
    """Retorna (o crea) el WorkspaceIndexer singleton para el workspace."""
    if workspace_root not in _INDEXER_REGISTRY:
        _INDEXER_REGISTRY[workspace_root] = WorkspaceIndexer(
            workspace_root=Path(workspace_root)
        )
    return _INDEXER_REGISTRY[workspace_root]
