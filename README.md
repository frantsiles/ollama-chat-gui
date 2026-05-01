# open-agent-ia
[![CI](https://github.com/frantsiles/open-agent-ia/actions/workflows/ci.yml/badge.svg)](https://github.com/frantsiles/open-agent-ia/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/frantsiles/open-agent-ia)](LICENSE)

Agente de IA con interfaz web que soporta múltiples providers LLM: Ollama (local), LM Studio, OpenAI, Copilot, Groq y Anthropic Claude. Incluye tres modos de operación (Chat, Agent, Plan), herramientas de sistema de archivos, RAG semántico del workspace y base de conocimiento externa persistente.

## Características principales

- **Multi-provider**: cambia entre Ollama, LM Studio, OpenAI, Copilot, Groq o Anthropic sin reiniciar.
- **Local-first**: con Ollama o LM Studio toda la inferencia ocurre en tu máquina.
- **Tres modos**: Chat (conversación simple), Agent (ciclo ReAct + herramientas), Plan (planificación + aprobación + ejecución).
- **RAG semántico**: indexación vectorial del workspace con ChromaDB. Fallback automático a búsqueda por keywords.
- **Knowledge Base externa**: ingesta de URLs y documentos Markdown con búsqueda semántica persistente.
- **Sugerencias proactivas**: el sistema sugiere archivos relevantes del workspace sin que el usuario tenga que pedirlo.
- **API REST + WebSocket**: backend FastAPI con documentación interactiva en `/docs`.
- **Persistencia**: sesiones y conversaciones guardadas en SQLite.

## Requisitos

- Python 3.11+
- Al menos un provider LLM activo (ver sección de providers)

## Instalación

```bash
git clone https://github.com/frantsiles/open-agent-ia.git
cd open-agent-ia
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

```bash
python app_web.py
# → http://localhost:8000  (UI)
# → http://localhost:8000/docs  (API interactiva)

# O con hot-reload (desarrollo)
uvicorn web.server:app --reload --port 8000
```

## Providers LLM

El provider activo se selecciona desde el panel de configuración de la UI o con la variable de entorno `LLM_PROVIDER`.

### Ollama (local, default)

```bash
# Instalar: https://ollama.ai
ollama pull gemma3:latest
ollama pull nomic-embed-text   # Para RAG semántico
```

### LM Studio (local)

1. Descarga [LM Studio](https://lmstudio.ai) y carga un modelo.
2. Activa el servidor local (puerto 1234 por defecto).
3. En la UI selecciona **LM Studio** como provider.

```bash
LM_STUDIO_BASE_URL=http://localhost:1234/v1   # default
```

### OpenAI / Groq / GitHub Copilot

Cualquier API compatible con OpenAI funciona con el mismo adapter.

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1   # o el endpoint de Groq/Copilot
```

### Anthropic (Claude)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | Provider activo: `ollama` \| `lmstudio` \| `openai` \| `anthropic` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL del servidor Ollama |
| `OLLAMA_DEFAULT_MODEL` | _(vacío)_ | Modelo a preseleccionar |
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | URL de LM Studio |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | URL de la API OpenAI-compatible |
| `OPENAI_API_KEY` | _(vacío)_ | API key para OpenAI / Groq / Copilot |
| `ANTHROPIC_API_KEY` | _(vacío)_ | API key para Anthropic Claude |
| `WORKSPACE_ROOT` | directorio actual | Raíz del workspace del agente |
| `EMBEDDING_ENABLED` | `true` | Activar RAG semántico |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Modelo de embeddings (Ollama) |
| `CHROMA_DB_PATH` | `~/.local/share/open-agent-ia/chroma` | Persistencia ChromaDB |
| `CHAT_DB_PATH` | `~/.local/share/open-agent-ia/sessions.db` | Base de datos de sesiones |
| `MAX_AGENT_STEPS` | `100` | Ciclos máximos del agente por tarea |
| `AGENT_TASK_TIMEOUT` | `300` | Segundos antes de cancelar la tarea |
| `PYTHON_SANDBOX_TIMEOUT_SECONDS` | `30` | Límite por ejecución de código Python |

> **Migración desde ollama-chat-gui**: si tenías sesiones guardadas, mueve el directorio de datos:
> ```bash
> mv ~/.local/share/ollama-chat-gui ~/.local/share/open-agent-ia
> ```

## Modos de operación

### Chat
Conversación directa con el modelo, sin herramientas.

### Agent (ReAct)
El agente ejecuta un ciclo Razonar → Actuar → Observar de forma autónoma. Herramientas disponibles:
- `read_file` / `write_file` — lectura y escritura de archivos
- `list_directory` / `create_directory` — navegación del workspace
- `search_files` — búsqueda por patrón de archivos
- `run_command` — ejecución de comandos de shell
- `execute_python` — sandbox Python con timeout configurable

### Plan
El agente genera un plan estructurado con pasos discretos, espera aprobación y ejecuta cada paso en orden.

## RAG semántico y Knowledge Base

Al iniciar una sesión, el sistema indexa automáticamente el workspace en background. Cada mensaje activa una búsqueda semántica que inyecta contexto relevante al modelo.

```bash
# Añadir documentación externa
curl -X POST http://localhost:8000/api/kb/ingest-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com/guia", "tags": ["docs"]}'

# Forzar re-indexación del workspace
curl -X POST http://localhost:8000/api/sessions/{session_id}/rag/reindex?force=true
```

Si `chromadb` no está instalado o el modelo de embeddings no está disponible, el sistema cae automáticamente al RAG por keywords. El chat nunca se interrumpe.

## Seguridad del workspace

- Operaciones de archivos limitadas al `Workspace root` configurado.
- Comandos peligrosos (`sudo`, `rm -rf /`, `mkfs`, fork bombs) bloqueados.
- Sistema de aprobación configurable: ninguna / solo escritura / todas las acciones.

## Calidad de código

```bash
ruff check .
python -m py_compile config.py core/*.py llm/*.py llm/providers/*.py tools/*.py security/*.py rag/*.py web/*.py
```

## Arquitectura

```
open-agent-ia/
├── app_web.py              # Entrada principal
├── config.py               # Configuración centralizada
├── core/                   # Lógica del agente
│   ├── agent.py            # Agente (Chat / Agent / Plan)
│   ├── planner.py          # Gestión de planes
│   └── models.py           # Modelos de datos
├── llm/                    # Capa LLM (provider-agnostic)
│   ├── base.py             # LLMProvider ABC + LLMClientError
│   ├── client.py           # Factory create_client()
│   ├── providers/
│   │   ├── ollama.py       # Ollama nativo
│   │   ├── openai_compat.py# OpenAI / LM Studio / Groq / Copilot
│   │   └── anthropic.py    # Anthropic Claude
│   └── prompts.py          # System prompts por modo
├── tools/                  # Sistema de herramientas
│   ├── base.py             # BaseTool ABC
│   ├── filesystem.py       # Herramientas de archivos
│   ├── command.py          # run_command
│   ├── python_executor.py  # Sandbox Python
│   └── registry.py         # Registro y despacho
├── security/               # Capa de seguridad
│   ├── sandbox.py          # Validación de paths y comandos
│   └── approval.py         # Sistema de aprobación
├── rag/                    # Sistema RAG
│   ├── local_rag.py        # RAG por keywords (fallback)
│   ├── embeddings.py       # Cliente de embeddings
│   ├── vector_store.py     # ChromaDB wrapper
│   ├── indexer.py          # Indexador incremental background
│   ├── knowledge_base.py   # CRUD de Knowledge Base externa
│   └── semantic_rag.py     # RAG semántico + sugerencias proactivas
└── web/                    # Backend FastAPI
    ├── server.py           # App FastAPI + rutas
    ├── api.py              # Endpoints REST
    ├── websocket.py        # Handler WebSocket (chat en tiempo real)
    ├── state.py            # Gestión de sesiones
    ├── persistence.py      # SQLite
    └── metrics.py          # Métricas de rendimiento
```

## Transparencia

Este proyecto fue desarrollado con apoyo de IA para acelerar diseño, implementación y documentación. Las decisiones finales, validación y publicación se mantienen bajo control del autor del repositorio.
