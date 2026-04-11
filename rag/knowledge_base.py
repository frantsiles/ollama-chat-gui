"""
KnowledgeBase — gestión de documentos externos en ChromaDB.

Permite ingestar texto arbitrario, archivos Markdown y URLs,
almacenándolos en la colección 'knowledge_base' del VectorStore.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests as http_requests

from config import KB_CHUNK_CHARS, KB_MAX_DOCUMENT_CHARS, KB_MAX_DOCUMENTS
from rag.embeddings import EmbeddingError, get_embedding_client
from rag.vector_store import Chunk, VectorStore, get_vector_store

logger = logging.getLogger(__name__)

# Timeout para requests HTTP de ingesta de URLs
_HTTP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk_text(text: str, max_chars: int = KB_CHUNK_CHARS) -> List[str]:
    """Trocea texto en chunks por párrafos."""
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


def _chunk_id(doc_id: str, idx: int) -> str:
    return hashlib.md5(f"{doc_id}:{idx}".encode()).hexdigest()[:16]


def _extract_text_from_html(html: str) -> str:
    """Extrae texto limpio de HTML usando BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
        soup = BeautifulSoup(html, "html.parser")
        # Eliminar scripts, estilos y nav
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        # Limpiar líneas vacías múltiples
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except ImportError:
        # Fallback sin BS4: eliminar tags con regex
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """
    Gestiona documentos externos en la colección 'knowledge_base' de ChromaDB.

    Un "documento" puede ser:
    - Texto/Markdown arbitrario
    - Contenido descargado de una URL

    Cada documento se trocea en chunks y se indexa semánticamente.
    """

    def __init__(self, workspace_root: str = "global") -> None:
        self._workspace_root = workspace_root
        self._store: VectorStore = get_vector_store(workspace_root)
        self._emb_client = get_embedding_client()

    # ------------------------------------------------------------------
    # Ingesta
    # ------------------------------------------------------------------

    def add_document(
        self,
        text: str,
        title: str = "",
        source: str = "",
        tags: Optional[List[str]] = None,
        doc_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Añade un documento de texto/Markdown a la KB.

        Args:
            text: Contenido textual del documento
            title: Título descriptivo
            source: Origen (URL, nombre de archivo, etc.)
            tags: Etiquetas para filtrado
            doc_id: ID explícito (se genera uno si no se provee)

        Returns:
            Dict con info del documento indexado (id, chunks, status)
        """
        if not self._store.available:
            return {"error": "ChromaDB no disponible", "status": "error"}

        if not self._emb_client.available:
            return {"error": "Modelo de embeddings no disponible", "status": "error"}

        # Validaciones
        text = text[:KB_MAX_DOCUMENT_CHARS]
        if not text.strip():
            return {"error": "Texto vacío", "status": "error"}

        # Límite de documentos
        current_count = len({
            s.get("doc_id") for s in self._store.list_sources(target="kb")
            if s.get("doc_id")
        })
        if current_count >= KB_MAX_DOCUMENTS:
            return {
                "error": f"Límite de {KB_MAX_DOCUMENTS} documentos alcanzado",
                "status": "error",
            }

        doc_id = doc_id or str(uuid.uuid4())
        now = datetime.now().isoformat()
        chunks_text = _chunk_text(text)

        chunks_to_upsert: List[Chunk] = []
        for idx, chunk_text in enumerate(chunks_text):
            try:
                vec = self._emb_client.embed(chunk_text)
            except EmbeddingError as exc:
                logger.warning("Error embeddando chunk %d de doc %s: %s", idx, doc_id, exc)
                continue

            chunks_to_upsert.append(
                Chunk(
                    id=_chunk_id(doc_id, idx),
                    text=chunk_text,
                    embedding=vec,
                    metadata={
                        "doc_id": doc_id,
                        "source": source or doc_id,
                        "title": title or source or doc_id,
                        "tags": ",".join(tags or []),
                        "created_at": now,
                        "chunk_index": idx,
                        "type": "kb_document",
                    },
                )
            )

        if not chunks_to_upsert:
            return {"error": "No se generaron chunks válidos", "status": "error"}

        # Borrar versión anterior si existe (upsert por doc_id)
        try:
            existing = self._store._get_kb_collection()
            if existing:
                ids_resp = existing.get(where={"doc_id": doc_id})
                old_ids = ids_resp.get("ids", [])
                if old_ids:
                    existing.delete(ids=old_ids)
        except Exception:
            pass

        n = self._store.upsert_chunks(chunks_to_upsert, target="kb")

        return {
            "status": "ok",
            "doc_id": doc_id,
            "title": title or source or doc_id,
            "source": source,
            "chunks_indexed": n,
            "created_at": now,
        }

    def ingest_url(
        self,
        url: str,
        title: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Descarga una URL, extrae el texto y lo ingesta en la KB.

        Args:
            url: URL a descargar (http/https)
            title: Título manual (si vacío, se usa el title del HTML)
            tags: Etiquetas para filtrado

        Returns:
            Dict con info del documento indexado
        """
        if not _is_valid_url(url):
            return {"error": f"URL inválida: {url}", "status": "error"}

        try:
            resp = http_requests.get(
                url,
                timeout=_HTTP_TIMEOUT,
                headers={"User-Agent": "ollama-chat-gui/2.0 (knowledge-base-ingester)"},
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
        except http_requests.RequestException as exc:
            return {"error": f"Error descargando URL: {exc}", "status": "error"}

        # Extraer texto
        if "text/html" in content_type:
            text = _extract_text_from_html(resp.text)
            # Intentar extraer título del HTML si no se proporcionó
            if not title:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    tag = soup.find("title")
                    title = tag.get_text(strip=True) if tag else url
                except Exception:
                    title = url
        else:
            # Texto plano, markdown, etc.
            text = resp.text

        if not text.strip():
            return {"error": "No se pudo extraer texto de la URL", "status": "error"}

        doc_id = hashlib.md5(url.encode()).hexdigest()[:16]
        result = self.add_document(
            text=text,
            title=title or url,
            source=url,
            tags=tags,
            doc_id=doc_id,
        )
        result["url"] = url
        return result

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Búsqueda semántica en la KB.

        Returns:
            Lista de dicts con text, score, metadata del resultado
        """
        if not self._store.available or not self._emb_client.available:
            return []

        try:
            vec = self._emb_client.embed(query_text)
        except EmbeddingError:
            return []

        results = self._store.query(vec, top_k=top_k, target="kb")
        return [
            {
                "text": r.text,
                "score": round(r.score, 4),
                "doc_id": r.metadata.get("doc_id", ""),
                "title": r.metadata.get("title", ""),
                "source": r.metadata.get("source", ""),
                "tags": r.metadata.get("tags", "").split(",") if r.metadata.get("tags") else [],
            }
            for r in results
        ]

    # ------------------------------------------------------------------
    # Listado / eliminación
    # ------------------------------------------------------------------

    def list_documents(self) -> List[Dict[str, Any]]:
        """Lista los documentos únicos en la KB (agrupados por doc_id)."""
        sources = self._store.list_sources(target="kb")
        # Agrupar por doc_id
        doc_map: Dict[str, Dict[str, Any]] = {}
        for s in sources:
            doc_id = s.get("doc_id", s.get("source", "unknown"))
            if doc_id not in doc_map:
                doc_map[doc_id] = {
                    "doc_id": doc_id,
                    "title": s.get("title", ""),
                    "source": s.get("source", ""),
                    "tags": s.get("tags", "").split(",") if s.get("tags") else [],
                    "created_at": s.get("created_at", ""),
                    "chunk_count": 0,
                }
            doc_map[doc_id]["chunk_count"] += s.get("chunk_count", 0)
        return list(doc_map.values())

    def delete_document(self, doc_id: str) -> Dict[str, Any]:
        """
        Elimina un documento y todos sus chunks de la KB.

        Returns:
            Dict con status y chunks eliminados
        """
        if not self._store.available:
            return {"error": "ChromaDB no disponible", "status": "error"}

        try:
            col = self._store._get_kb_collection()
            if col is None:
                return {"error": "Colección KB no disponible", "status": "error"}

            ids_resp = col.get(where={"doc_id": doc_id})
            ids = ids_resp.get("ids", [])
            if not ids:
                return {"error": f"Documento '{doc_id}' no encontrado", "status": "not_found"}
            col.delete(ids=ids)
            return {"status": "ok", "doc_id": doc_id, "chunks_deleted": len(ids)}
        except Exception as exc:
            logger.error("Error eliminando doc %s: %s", doc_id, exc)
            return {"error": str(exc), "status": "error"}

    def count(self) -> int:
        """Total de chunks en la KB."""
        return self._store.count(target="kb")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_KB_INSTANCE: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """Retorna la instancia global de KnowledgeBase."""
    global _KB_INSTANCE
    if _KB_INSTANCE is None:
        _KB_INSTANCE = KnowledgeBase()
    return _KB_INSTANCE
