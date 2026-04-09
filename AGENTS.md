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

### Run the NEW modular app
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
- `WORKSPACE_ROOT` can be set via environment variable; otherwise defaults to cwd.

## Architecture map (NEW modular structure)

```
ollama-chat-gui/
├── app_new.py              # NEW entry point
├── app.py                  # Legacy monolith (deprecated)
├── config.py               # Centralized configuration
├── core/                   # Core agent logic
│   ├── agent.py            # Agent with ReAct cycle
│   ├── planner.py          # Plan creation and management
│   ├── session.py          # Conversation session management
│   └── models.py           # Data models (Message, Plan, ToolCall, etc.)
├── llm/                    # LLM integration
│   ├── client.py           # Ollama HTTP client
│   └── prompts.py          # System prompts per mode
├── tools/                  # Modular tool system
│   ├── base.py             # BaseTool ABC
│   ├── filesystem.py       # read_file, write_file, list_directory, etc.
│   ├── command.py          # run_command tool
│   └── registry.py         # Tool registration and dispatch
├── security/               # Security layer
│   ├── sandbox.py          # Path validation, command blocking
│   └── approval.py         # Approval system for write operations
├── rag/                    # RAG system
│   └── local_rag.py        # Local workspace RAG
└── ui/                     # Streamlit UI
    ├── app.py              # Main UI orchestration
    ├── state.py            # Centralized session state management
    └── components/         # Reusable UI components
        ├── sidebar.py      # Configuration sidebar
        ├── chat.py         # Chat messages and input
        ├── mode_selector.py # Mode selection (Chat/Agent/Plan)
        ├── plan_view.py    # Plan display and interaction
        └── approval.py     # Approval dialogs
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

#### 4) UI (`ui/`)
- `AppState` centralizes all session state
- Components are reusable and modular
- Clean separation between UI and business logic

## File-level change guidance
- **Add new tool**: Create class in `tools/`, add to `ToolRegistry.AVAILABLE_TOOLS`
- **Change prompts**: Edit `llm/prompts.py`
- **Modify agent behavior**: Edit `core/agent.py`
- **UI changes**: Edit files in `ui/components/`
- **Add configuration**: Add to `config.py` and `ui/state.py`
- **Security rules**: Edit `security/sandbox.py` or `config.py`

## Migration from legacy app.py
The new modular structure replaces the monolithic `app.py`. Key differences:
- Configuration moved to `config.py`
- Tools are now classes in `tools/` instead of inline functions
- State management centralized in `ui/state.py`
- Three explicit modes instead of implicit behavior detection
