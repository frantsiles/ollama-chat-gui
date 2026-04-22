"""FastAPI server principal."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from web.api import router as api_router
from web.websocket import websocket_handler

# =============================================================================
# App Configuration
# =============================================================================

app = FastAPI(
    title="Ollama Chat GUI",
    description="AI Agent with Chat, Agent, and Plan modes",
    version="2.0.0",
)

# CORS para desarrollo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Routes
# =============================================================================

# API REST
app.include_router(api_router)


# WebSocket
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Endpoint WebSocket para chat en tiempo real."""
    await websocket_handler(websocket, session_id)


# Archivos estáticos
STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Página principal
@app.get("/")
async def root():
    """Sirve la página principal."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Ollama Chat GUI API", "docs": "/docs"}


# =============================================================================
# Startup/Shutdown Events
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Evento de inicio."""

    from config import PERSISTENCE_DB_PATH
    from web.state import SessionManager
    SessionManager.init_persistence(PERSISTENCE_DB_PATH)
    print("🚀 Ollama Chat GUI started")
    print(f"📁 Static files: {STATIC_DIR}")
    print(f"💾 Persistence DB: {PERSISTENCE_DB_PATH}")


@app.on_event("shutdown")
async def shutdown_event():
    """Evento de cierre."""
    print("👋 Ollama Chat GUI shutting down")

# =============================================================================
# Server Startup Logic
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True, workers=1)

