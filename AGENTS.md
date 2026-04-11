# AGENTS.md

This file provides guidance to AI assistants when working with code in this repository.

## Project purpose and scope
- Local-first AI agent with Ollama models.
- Three operation modes: Chat, Agent (ReAct), and Plan.
- Modular architecture with clear separation of concerns.
- Keep changes aligned with local usage; model inference runs against local Ollama endpoint.

## Setup and common commands
### Environment setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run the NEW web UI (recommended)
```bash
python app_web.py
# Or directly with uvicorn:
uvicorn web.server:app --reload --port 8000
```

### Run Streamlit UI (legacy)
```bash
streamlit run app_new.py
```

### Run the legacy app (deprecated)
```bash
streamlit run app.py
```

### One-command startup
```bash
./run.sh
```

### Lint and validation
```bash
ruff check .
python -m py_compile app_new.py config.py
python -m py_compile core/*.py llm/*.py tools/*.py security/*.py rag/*.py ui/*.py
```

## Runtime configuration
- Optional `.env` values (see `.env.example`):
  - `OLLAMA_BASE_URL` (default `http://localhost:11434`)
  - `OLLAMA_DEFAULT_MODEL` (default empty)
  - `WORKSPACE_ROOT` — workspace root (defaults to cwd)
  - `EMBEDDING_ENABLED` — enable semantic RAG (default `true`)
  - `EMBEDDING_MODEL` — Ollama embedding model (default `nomic-embed-text`)
  - `CHROMA_DB_PATH` — ChromaDB persistence directory
  - `CHAT_DB_PATH` — SQLite sessions database
  - `RAG_PROACTIVE_SCORE_THRESHOLD` — min cosine score for proactive suggestions (default `0.75`)
  - `RAG_SEMANTIC_TOP_K` — chunks retrieved per query (default `6`)

## Architecture map

```
ollama-chat-gui/
├── app_web.py              # Entry point: Web UI (FastAPI, recommended)
├── app_new.py              # Entry point: Streamlit UI (legacy)
├── app.py                  # Legacy monolith (deprecated)
├── config.py               # Centralized configuration (all env overridable)
├── core/                   # Core agent logic
│   ├── agent.py            # Agent: Chat / ReAct / Plan modes
│   ├── planner.py          # Plan creation and management
│   ├── session.py          # Conversation session management
│   └── models.py           # Data models (Message, Plan, ToolCall, etc.)
├── llm/                    # LLM integration
│   ├── client.py           # Ollama HTTP client (chat + embeddings)
│   └── prompts.py          # System prompts per mode + context templates
├── tools/                  # Modular tool system
│   ├── base.py             # BaseTool ABC
│   ├── filesystem.py       # read_file, write_file, list_directory, etc.
│   ├── command.py          # run_command tool
│   └── registry.py         # Tool registration, validation and dispatch
├── security/               # Security layer
│   ├── sandbox.py          # Path validation, blocked command patterns
│   └── approval.py         # Approval system (none / write-only / all)
├── rag/                    # RAG system
│   ├── local_rag.py        # Keyword RAG (bag-of-words, used as fallback)
│   ├── embeddings.py       # EmbeddingClient: Ollama /api/embeddings + LRU cache
│   ├── vector_store.py     # VectorStore: ChromaDB wrapper (workspace + KB collections)
│   ├── indexer.py          # WorkspaceIndexer: incremental background indexing
│   ├── knowledge_base.py   # KnowledgeBase: external docs CRUD (text, URL ingestion)
│   └── semantic_rag.py     # SemanticRAG: unified entry point + proactive suggestions
├── web/                    # FastAPI backend
│   ├── server.py           # FastAPI app + CORS + static files
│   ├── api.py              # General REST endpoints
│   ├── api_rag.py          # RAG + KB REST endpoints
│   ├── websocket.py        # WebSocket handler (real-time chat)
│   ├── state.py            # In-memory session management
│   ├── persistence.py      # SQLite persistence
│   └── metrics.py          # Request/performance metrics
└── ui/                     # Streamlit UI (legacy)
    ├── app.py
    ├── state.py
    └── components/
        ├── sidebar.py
        ├── chat.py
        ├── mode_selector.py
        ├── plan_view.py
        └── approval.py
```

### Operation Modes
1. **Chat Mode**: Simple conversation without tools
2. **Agent Mode**: Automatic ReAct cycle with tool execution
3. **Plan Mode**: Creates plan first, waits for approval, then executes

### Key Components

#### 1) Core Agent (`core/agent.py`)
- `Agent` class handles all three modes
- `chat()` - simple chat without tools
- `run()` - ReAct cycle with automatic tool execution
- `execute_plan_step()` - step-by-step plan execution

#### 2) Tool System (`tools/`)
- `BaseTool` ABC defines tool interface
- Each tool is a separate class (ReadFileTool, WriteFileTool, etc.)
- `ToolRegistry` handles registration and dispatch
- Tools are sandboxed to workspace root

#### 3) Security (`security/`)
- `Sandbox` validates paths and commands
- `ApprovalManager` handles approval for write operations
- Three approval levels: none, write-only, all

#### 4) RAG system (`rag/`)
- `LocalRAG` — keyword-based fallback, always available
- `EmbeddingClient` — calls Ollama `/api/embeddings`, LRU cache, auto-detects model availability
- `VectorStore` — ChromaDB wrapper with two isolated collections: `workspace_{hash}` and `knowledge_base`
- `WorkspaceIndexer` — incremental indexing (mtime tracking), runs in background thread
- `KnowledgeBase` — external docs CRUD; supports raw text and URL ingestion (HTML parsing via BS4)
- `SemanticRAG` — unified entry point; semantic search + proactive suggestions with cooldown; transparent fallback to `LocalRAG`

#### 5) Web backend (`web/`)
- FastAPI app with CORS, static file serving and auto-generated `/docs`
- REST API for sessions, config, approval, plans, RAG status and KB management
- WebSocket at `/ws/{session_id}` for real-time chat with step streaming
- Sessions persisted in SQLite via `persistence.py`

#### 6) UI (`ui/`)
- `AppState` centralizes all session state
- Components are reusable and modular
- Clean separation between UI and business logic

## File-level change guidance
- **Add new tool**: Create class in `tools/`, add to `ToolRegistry.AVAILABLE_TOOLS`
- **Change prompts**: Edit `llm/prompts.py`
- **Modify agent behavior**: Edit `core/agent.py`
- **UI changes**: Edit files in `ui/components/`
- **Add configuration**: Add to `config.py`; if env-overridable, document in `.env.example`
- **Security rules**: Edit `security/sandbox.py` or `config.py`
- **RAG/embeddings**: Entry point is `rag/semantic_rag.py`; ChromaDB logic in `rag/vector_store.py`
- **Knowledge Base endpoints**: Edit `web/api_rag.py`
- **Add REST endpoint**: Add to `web/api.py` or `web/api_rag.py` depending on domain
- **WebSocket message types**: Add handler in `web/websocket.py`

## WebSocket message types
| Type (client → server) | Description |
|---|---|
| `chat` | Send a chat message (all modes) |
| `stream_chat` | Chat with token streaming |
| `approval` | Approve/reject a pending tool action |
| `plan` | Plan lifecycle actions (approve/reject/execute) |
| `cancel` | Cancel running agent |
| `ping` | Keep-alive |

| Type (server → client) | Description |
|---|---|
| `connected` | Initial state on WS connect |
| `start` | Agent started processing |
| `agent_step` | Step trace message |
| `response` | Final agent response |
| `plan_created` | New plan available for approval |
| `plan_approved` / `plan_rejected` | Plan decision |
| `plan_step_complete` | Step finished |
| `approval_required` | Tool needs user approval |
| `rag_suggestion` | Proactive file suggestions based on conversation context |
| `stream_start` / `stream_chunk` / `stream_end` | Streaming tokens |
| `cancelled` | Agent cancelled |
| `error` | Error message |

## Semantic RAG flow
1. On session start → `SemanticRAG.ensure_indexed()` triggers background indexing if workspace has 0 chunks
2. On each message → `SemanticRAG.retrieve(query)` embeds the query and searches `workspace + KB` collections
3. Retrieved context is injected as a system message before calling the LLM
4. After sending the response → `SemanticRAG.get_proactive_suggestions(recent_messages)` runs
5. If suggestions exceed score threshold and are not in cooldown → emits `rag_suggestion` WS event

## REST API endpoints (RAG & KB)
| Method | Path | Description |
|---|---|---|
| GET | `/api/rag/status` | Indexer status and chunk counts |
| POST | `/api/sessions/{id}/rag/reindex` | Trigger workspace reindex |
| GET | `/api/kb/documents` | List KB documents |
| POST | `/api/kb/documents` | Add text/markdown document |
| POST | `/api/kb/ingest-url` | Ingest URL into KB |
| DELETE | `/api/kb/documents/{doc_id}` | Delete KB document |
| POST | `/api/kb/query` | Semantic search in KB |

## Migration from legacy app.py
The new modular structure replaces the monolithic `app.py`. Key differences:
- Configuration moved to `config.py` (all values env-overridable)
- Tools are now classes in `tools/` instead of inline functions
- State management centralized; web sessions in `web/state.py`
- Three explicit modes instead of implicit behavior detection
- RAG upgraded from keyword-only to semantic (ChromaDB + Ollama embeddings) with keyword fallback
- Web UI replaces Streamlit as the primary interface (Streamlit kept as legacy)
