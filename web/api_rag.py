"""Router FastAPI para el RAG semántico y la Knowledge Base externa."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["rag"])


# =============================================================================
# Pydantic Models
# =============================================================================

class DocumentCreate(BaseModel):
    text: str = Field(..., description="Contenido textual del documento")
    title: str = Field("", description="Título descriptivo")
    source: str = Field("", description="Origen (nombre de archivo, referencia, etc.)")
    tags: List[str] = Field(default_factory=list, description="Etiquetas para filtrado")


class URLIngest(BaseModel):
    url: str = Field(..., description="URL a descargar e indexar")
    title: str = Field("", description="Título manual (opcional)")
    tags: List[str] = Field(default_factory=list)


class KBQuery(BaseModel):
    query: str = Field(..., description="Texto de búsqueda semántica")
    top_k: int = Field(5, ge=1, le=20, description="Número de resultados")


# =============================================================================
# /api/rag — Estado del indexador
# =============================================================================

@router.get("/api/rag/status")
async def get_rag_status(workspace_root: str = "") -> Dict[str, Any]:
    """
    Estado del sistema RAG semántico para un workspace.

    Query params:
        workspace_root: Ruta del workspace (usa el por defecto si se omite)
    """
    from config import DEFAULT_WORKSPACE_ROOT
    ws = workspace_root or DEFAULT_WORKSPACE_ROOT

    from rag.semantic_rag import get_semantic_rag
    srag = get_semantic_rag(ws)
    return {"workspace": ws, "rag": srag.status()}


@router.post("/api/sessions/{session_id}/rag/reindex")
async def reindex_workspace(
    session_id: str,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Lanza una re-indexación del workspace de la sesión en background.

    Query params:
        force: Si True, re-indexa todos los archivos aunque no hayan cambiado
    """
    from web.state import SessionManager
    session = SessionManager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from rag.semantic_rag import get_semantic_rag
    srag = get_semantic_rag(session.workspace_root)

    if not srag.semantic_available:
        raise HTTPException(
            status_code=503,
            detail="RAG semántico no disponible (ChromaDB o modelo de embeddings no encontrado)",
        )

    srag.trigger_reindex(force=force)
    return {
        "status": "reindex_started",
        "workspace": session.workspace_root,
        "force": force,
    }


# =============================================================================
# /api/kb — Knowledge Base externa
# =============================================================================

@router.get("/api/kb/documents")
async def list_kb_documents() -> Dict[str, Any]:
    """Lista todos los documentos en la Knowledge Base."""
    from rag.knowledge_base import get_knowledge_base
    kb = get_knowledge_base()
    docs = kb.list_documents()
    return {"documents": docs, "total": len(docs), "chunk_count": kb.count()}


@router.post("/api/kb/documents")
async def add_kb_document(data: DocumentCreate) -> Dict[str, Any]:
    """Añade un documento de texto/Markdown a la Knowledge Base."""
    from rag.knowledge_base import get_knowledge_base
    kb = get_knowledge_base()
    result = kb.add_document(
        text=data.text,
        title=data.title,
        source=data.source,
        tags=data.tags,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error", "Error desconocido"))
    return result


@router.post("/api/kb/ingest-url")
async def ingest_url(data: URLIngest) -> Dict[str, Any]:
    """
    Descarga una URL, extrae el texto y lo indexa en la Knowledge Base.
    Soporta HTML (extrae texto limpio) y texto plano/markdown.
    """
    from rag.knowledge_base import get_knowledge_base
    import asyncio

    kb = get_knowledge_base()
    # ingest_url puede tardar (descarga HTTP + embeddings) → ejecutar en thread
    result = await asyncio.to_thread(
        kb.ingest_url,
        data.url,
        data.title,
        data.tags,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error", "Error desconocido"))
    return result


@router.delete("/api/kb/documents/{doc_id}")
async def delete_kb_document(doc_id: str) -> Dict[str, Any]:
    """Elimina un documento y todos sus chunks de la Knowledge Base."""
    from rag.knowledge_base import get_knowledge_base
    kb = get_knowledge_base()
    result = kb.delete_document(doc_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("error"))
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@router.post("/api/kb/query")
async def query_kb(data: KBQuery) -> Dict[str, Any]:
    """
    Búsqueda semántica directa en la Knowledge Base.
    Retorna los chunks más relevantes con su score de similitud.
    """
    from rag.knowledge_base import get_knowledge_base
    import asyncio

    kb = get_knowledge_base()
    results = await asyncio.to_thread(kb.query, data.query, data.top_k)
    return {"query": data.query, "results": results, "count": len(results)}
