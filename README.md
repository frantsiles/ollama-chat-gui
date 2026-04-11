# Ollama Chat GUI
[![CI](https://github.com/frantsiles/ollama-chat-gui/actions/workflows/ci.yml/badge.svg)](https://github.com/frantsiles/ollama-chat-gui/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/frantsiles/ollama-chat-gui)](LICENSE)

Agente de IA local con interfaz web, construido sobre Ollama. Soporta tres modos de operación (Chat, Agent, Plan), herramientas de sistema de archivos, RAG semántico del workspace y base de conocimiento externa persistente.

## Características principales

- **Local-first**: toda la inferencia y el almacenamiento vectorial ocurren en tu máquina.
- **Tres modos**: Chat (conversación simple), Agent (ciclo ReAct + herramientas), Plan (planificación + aprobación + ejecución).
- **RAG semántico**: indexación vectorial del workspace con ChromaDB y embeddings de Ollama. Fallback automático a búsqueda por keywords si los componentes semánticos no están disponibles.
- **Knowledge Base externa**: ingesta de URLs y documentos Markdown con búsqueda semántica persistente.
- **Sugerencias proactivas**: el sistema sugiere archivos relevantes del workspace basándose en el hilo de la conversación, sin que el usuario tenga que pedirlo.
- **API REST + WebSocket**: backend FastAPI con documentación interactiva en `/docs`.
- **Persistencia**: sesiones y conversaciones guardadas en SQLite.

## Requisitos

- Python 3.11+
- [Ollama](https://ollama.ai) instalado y ejecutándose
- Al menos un modelo de chat (ej: `gemma3:latest`) y, para RAG semántico, un modelo de embeddings:

```bash
ollama pull gemma3:latest
ollama pull nomic-embed-text   # Para RAG semántico (recomendado)
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

```bash
# Verificar que Ollama esté activo
ollama ps

# Levantar la Web UI (recomendado)
python app_web.py
# → http://localhost:8000  (UI)
# → http://localhost:8000/docs  (API interactiva)

# O directamente con uvicorn (con hot-reload)
uvicorn web.server:app --reload --port 8000

# UI Streamlit (legacy)
streamlit run app_new.py
```

## Variables de entorno

Copia `.env.example` a `.env` y ajusta según necesites:

| Variable | Default | Descripción |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL del servidor Ollama |
| `OLLAMA_DEFAULT_MODEL` | _(vacío)_ | Modelo a preseleccionar |
| `WORKSPACE_ROOT` | directorio actual | Raíz del workspace del agente |
| `EMBEDDING_ENABLED` | `true` | Activar RAG semántico |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Modelo de embeddings en Ollama |
| `CHROMA_DB_PATH` | `~/.local/share/ollama-chat-gui/chroma` | Directorio de persistencia ChromaDB |
| `CHAT_DB_PATH` | `~/.local/share/ollama-chat-gui/sessions.db` | Base de datos de sesiones |
| `RAG_PROACTIVE_SCORE_THRESHOLD` | `0.75` | Score mínimo para sugerencias proactivas |
| `RAG_SEMANTIC_TOP_K` | `6` | Chunks recuperados por query |

## Modos de operación

### Chat
Conversación directa con el modelo, sin herramientas. Útil para preguntas rápidas.

### Agent (ReAct)
El agente ejecuta un ciclo Razonar → Actuar → Observar de forma autónoma hasta completar la tarea (máx. 12 pasos). Herramientas disponibles:
- `read_file` — lee archivos del workspace
- `write_file` — crea/modifica archivos
- `list_directory` — lista contenido de directorios
- `create_directory` — crea directorios
- `search_files` — busca archivos por patrón
- `run_command` — ejecuta comandos de shell

### Plan
El agente genera primero un plan estructurado con pasos discretos, espera aprobación del usuario y luego ejecuta cada paso en orden.

## RAG semántico y Knowledge Base

### Cómo funciona

Al iniciar una sesión, el sistema indexa automáticamente el workspace en background (sin bloquear el chat). Cada mensaje activa una búsqueda semántica que inyecta contexto relevante al modelo.

Después de cada respuesta, el sistema analiza el contexto reciente de la conversación y emite sugerencias proactivas por WebSocket con los archivos del workspace más relacionados con el tema actual.

### Knowledge Base externa

Permite ampliar el conocimiento del agente con documentación externa sin depender del contenido del proyecto:

```bash
# Añadir una URL
curl -X POST http://localhost:8000/api/kb/ingest-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com/guia", "tags": ["docs"]}'

# Añadir texto/Markdown
curl -X POST http://localhost:8000/api/kb/documents \
  -H "Content-Type: application/json" \
  -d '{"text": "...", "title": "Mi documentación", "tags": ["referencia"]}'

# Consultar directamente
curl -X POST http://localhost:8000/api/kb/query \
  -H "Content-Type: application/json" \
  -d '{"query": "cómo configurar X", "top_k": 5}'

# Listar documentos
curl http://localhost:8000/api/kb/documents

# Forzar re-indexación del workspace
curl -X POST http://localhost:8000/api/sessions/{session_id}/rag/reindex?force=true
```

También disponibles en la documentación interactiva: `http://localhost:8000/docs`.

### Degradación elegante

Si `chromadb` no está instalado o `nomic-embed-text` no está disponible en Ollama, el sistema cae automáticamente al RAG por keywords original. El chat nunca se interrumpe.

## Seguridad del workspace

- Todas las operaciones de archivos están limitadas al `Workspace root` configurado.
- No se permiten rutas fuera del workspace.
- Comandos peligrosos (`sudo`, `rm -rf /`, `mkfs`, fork bombs, etc.) están bloqueados.
- Sistema de aprobación configurable (ninguna / solo escritura / todas las acciones).

## Calidad de código

```bash
ruff check .
python -m py_compile app_new.py config.py
python -m py_compile core/*.py llm/*.py tools/*.py security/*.py rag/*.py web/*.py
```

## Arquitectura

```
ollama-chat-gui/
├── app_web.py              # Entrada principal (Web UI)
├── app_new.py              # Entrada Streamlit (legacy)
├── config.py               # Configuración centralizada
├── core/                   # Lógica del agente
│   ├── agent.py            # Agente (Chat / Agent / Plan)
│   ├── planner.py          # Gestión de planes
│   ├── session.py          # Gestión de sesiones
│   └── models.py           # Modelos de datos
├── llm/                    # Integración con Ollama
│   ├── client.py           # HTTP client
│   └── prompts.py          # System prompts por modo
├── tools/                  # Sistema de herramientas
│   ├── base.py             # BaseTool ABC
│   ├── filesystem.py       # Herramientas de archivos
│   ├── command.py          # run_command
│   └── registry.py         # Registro y despacho
├── security/               # Capa de seguridad
│   ├── sandbox.py          # Validación de paths y comandos
│   └── approval.py         # Sistema de aprobación
├── rag/                    # Sistema RAG
│   ├── local_rag.py        # RAG por keywords (fallback)
│   ├── embeddings.py       # Cliente de embeddings (Ollama)
│   ├── vector_store.py     # ChromaDB wrapper (workspace + KB)
│   ├── indexer.py          # Indexador incremental background
│   ├── knowledge_base.py   # CRUD de Knowledge Base externa
│   └── semantic_rag.py     # RAG semántico + sugerencias proactivas
├── web/                    # Backend FastAPI
│   ├── server.py           # App FastAPI + rutas
│   ├── api.py              # Endpoints REST generales
│   ├── api_rag.py          # Endpoints REST RAG y Knowledge Base
│   ├── websocket.py        # Handler WebSocket (chat en tiempo real)
│   ├── state.py            # Gestión de sesiones en memoria
│   ├── persistence.py      # Persistencia SQLite
│   └── metrics.py          # Métricas de rendimiento
└── ui/                     # Streamlit UI (legacy)
    ├── app.py
    ├── state.py
    └── components/
```

## Transparencia

Este proyecto fue desarrollado con apoyo de IA (Oz en Warp) para acelerar diseño, implementación y documentación. Las decisiones finales, validación y publicación se mantienen bajo control del autor del repositorio.
