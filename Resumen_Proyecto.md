# Resumen del Proyecto: Ollama Chat GUI

## Descripción

Agente de IA local con interfaz web construido sobre Ollama. Permite interactuar con modelos de lenguaje locales en tres modos (Chat, Agent, Plan), con herramientas de sistema de archivos, RAG semántico del workspace y base de conocimiento externa persistente.

## Estado actual

**Versión:** 2.0.0  
**Interfaz principal:** Web (FastAPI + WebSocket) en `http://localhost:8000`  
**Interfaz legacy:** Streamlit (`app_new.py`), mantenida pero no activamente desarrollada.

## Arquitectura en capas

```
Entrada de usuario
     │
     ▼
web/websocket.py  ←→  web/api.py + web/api_rag.py
     │
     ▼
core/agent.py  (modos: Chat / Agent ReAct / Plan)
     │              │
     ▼              ▼
llm/client.py    tools/registry.py
(Ollama API)     (6 herramientas)
     │
     ▼
rag/semantic_rag.py
  ├─ embeddings.py   (Ollama /api/embeddings)
  ├─ vector_store.py  (ChromaDB)
  ├─ indexer.py       (background thread)
  ├─ knowledge_base.py (docs externos)
  └─ local_rag.py     (fallback keywords)
```

## Módulos clave

### `core/`
- **`agent.py`** — Agente con tres modos. En modo Agent corre un ciclo ReAct (máx 12 pasos). Incluye gestión de contexto con ventana deslizante y resumen automático de conversaciones largas.
- **`models.py`** — Tipos de datos: `Message`, `ToolCall`, `ToolResult`, `Plan`, `PlanStep`, `Conversation`, `AgentState`.
- **`planner.py`** — Crea planes estructurados vía LLM y gestiona su ciclo de vida.

### `llm/`
- **`client.py`** — HTTP client para Ollama (`/api/chat`, `/api/generate`, `/api/embeddings`, `/api/tags`, `/api/show`).
- **`prompts.py`** — System prompts diferenciados por modo + templates de contexto de workspace y resultados de tools.

### `tools/`
Seis herramientas disponibles para el agente: `read_file`, `write_file`, `list_directory`, `create_directory`, `search_files`, `run_command`. Todas sandboxeadas al workspace root.

### `security/`
- **`sandbox.py`** — Valida paths (sin salida del workspace) y bloquea comandos peligrosos (`sudo`, `rm -rf /`, `mkfs`, fork bombs, `shutdown`, escritura en `/dev/*`).
- **`approval.py`** — Sistema de aprobación en tres niveles: ninguna, solo escritura, todas.

### `rag/` — Sistema RAG (actualizado)

| Archivo | Clase principal | Responsabilidad |
|---|---|---|
| `local_rag.py` | `LocalRAG` | RAG por keywords (bag-of-words), usado como fallback |
| `embeddings.py` | `EmbeddingClient` | Embeddings via Ollama, caché LRU 512 entradas |
| `vector_store.py` | `VectorStore` | ChromaDB con colecciones `workspace_{hash}` y `knowledge_base` |
| `indexer.py` | `WorkspaceIndexer` | Indexación incremental en background (mtime tracking) |
| `knowledge_base.py` | `KnowledgeBase` | CRUD de docs externos: texto, Markdown, URL (scraping HTML) |
| `semantic_rag.py` | `SemanticRAG` | Punto de entrada unificado: retrieval semántico + sugerencias proactivas + fallback |

**Flujo RAG por mensaje:**
1. `ensure_indexed()` — lanza indexación en background si el workspace tiene 0 chunks
2. `retrieve(query)` — embeds la query, busca en `workspace + KB`, inyecta contexto al LLM
3. Después de responder: `get_proactive_suggestions(recent_msgs)` — sugiere archivos relevantes vía WebSocket

**Degradación elegante:** si ChromaDB o el modelo de embeddings no están disponibles, el sistema cae automáticamente a `LocalRAG` sin interrumpir el chat.

### `web/`
- **`server.py`** — App FastAPI con CORS y archivos estáticos.
- **`api.py`** — Endpoints REST: sesiones, configuración, aprobación, planes, health check, métricas.
- **`api_rag.py`** — Endpoints RAG y KB: status, reindex, CRUD documentos, ingesta URL, búsqueda semántica.
- **`websocket.py`** — Handler de WebSocket: chat en tiempo real, streaming de pasos, cancelación, sugerencias proactivas.
- **`state.py`** — Sesiones en memoria con locks por sesión (evita ejecuciones concurrentes).
- **`persistence.py`** — SQLite para persistir sesiones entre reinicios.
- **`metrics.py`** — Métricas de rendimiento por sesión y modo.

## Configuración destacada (`config.py`)

Todas las variables son override-ables por entorno (ver `.env.example`):

- `OLLAMA_BASE_URL` / `OLLAMA_DEFAULT_MODEL` — conexión a Ollama
- `MAX_AGENT_STEPS = 12` — límite de pasos ReAct
- `MAX_CONTEXT_MESSAGES = 20` — umbral para activar compresión de contexto
- `EMBEDDING_ENABLED` / `EMBEDDING_MODEL` — RAG semántico
- `CHROMA_DB_PATH` — persistencia ChromaDB
- `RAG_PROACTIVE_SCORE_THRESHOLD = 0.75` — score mínimo para sugerencias
- `KB_MAX_DOCUMENTS = 500` / `KB_MAX_DOCUMENT_CHARS = 50_000` — límites de la Knowledge Base

## Dependencias principales

| Paquete | Uso |
|---|---|
| `fastapi` + `uvicorn` | Servidor web principal |
| `streamlit` | UI legacy |
| `requests` | HTTP client (Ollama + ingesta URLs) |
| `chromadb` | Vector store persistente |
| `beautifulsoup4` | Parsing HTML para ingesta de URLs |
| `pydantic` | Modelos de datos en la API REST |

## Convenciones de desarrollo

- Cada módulo principal expone un **singleton via factory function** (`get_semantic_rag`, `get_vector_store`, `get_embedding_client`, etc.) para reutilizar instancias entre requests.
- La **degradación elegante** es un principio: si un componente opcional falla, el sistema continúa con capacidades reducidas sin romper el chat.
- Toda nueva configuración va en `config.py` y se documenta en `.env.example`.
- Toda nueva funcionalidad se refleja en `AGENTS.md` y `README.md`.

## Comandos útiles

```bash
# Iniciar
source .venv/bin/activate && python app_web.py

# Linting
ruff check .

# Compilación sin errores
python -m py_compile core/*.py llm/*.py tools/*.py security/*.py rag/*.py web/*.py

# Instalar modelo de embeddings
ollama pull nomic-embed-text

# Ver estado del RAG
curl http://localhost:8000/api/rag/status

# Listar documentos en la KB
curl http://localhost:8000/api/kb/documents
```
