# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project purpose and scope
- Local-first Streamlit chat UI for Ollama models.
- Main flows are chat streaming, model/capability selection, file attachments, and workspace-scoped file/command tools.
- Keep changes aligned with local usage; model inference is expected to run against a local Ollama endpoint.

## Setup and common commands
### Environment setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run the app
```bash
streamlit run app.py
```

### One-command startup (bootstraps venv + deps + app)
```bash
./run.sh
```

### Lint and validation
```bash
ruff check .
python -m py_compile app.py ollama_client.py
```

### CI-equivalent local check
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install ruff
ruff check .
python -m py_compile app.py ollama_client.py
```

### Single-file validation (closest current equivalent to single-test execution)
This repository does not currently include a test suite. For targeted verification of one module:
```bash
python -m py_compile app.py
```
or
```bash
python -m py_compile ollama_client.py
```

## Runtime configuration
- Optional `.env` values (see `.env.example`):
  - `OLLAMA_BASE_URL` (default `http://localhost:11434`)
  - `OLLAMA_DEFAULT_MODEL` (default empty in app; example uses `gemma3:latest`)
- `WORKSPACE_ROOT` can be set via environment variable; otherwise defaults to current working directory at startup.

## Architecture map (big picture)
### 1) Streamlit app is the orchestration layer
- `app.py` owns UI rendering, session state, tool actions, and chat lifecycle.
- `main()` builds sidebar config (base URL, model, temperature, workspace root), main chat timeline, workspace tools, and attachment uploader.
- Session state keys (`messages`, `models`, `model_capabilities`, `workspace_root`, `uploader_key`) are the source of truth for UI and chat context.

### 2) Ollama integration is isolated in an adapter
- `ollama_client.py` encapsulates all HTTP interactions with Ollama:
  - `list_models()` → `/api/tags`
  - `get_model_capabilities()` → `/api/show`
  - `chat_stream()` → `/api/chat` with streamed line-by-line JSON handling
- `OllamaClientError` is the app-level error boundary type consumed by `app.py`.

### 3) Chat message construction supports multimodal + text context injection
- `build_user_message()` in `app.py` merges prompt + attachments into the message payload:
  - image files are base64-encoded into `images` only when model capability includes `vision`
  - text-like files are decoded and appended into prompt content as structured context blocks
  - unsupported/oversized files are tracked and surfaced to the user

### 4) Workspace operations are intentionally sandboxed
- File and command tools in `app.py` (`_scan_directory`, `_read_text_file`, `_write_text_file`, `_run_workspace_command`) all operate relative to workspace root.
- `_safe_resolve_path()` enforces boundary checks using resolved absolute paths and rejects escapes outside workspace.
- Tool outputs are appended as `system` messages (`_add_system_context`) so the model can reason over real project state.
- Guardrails include max scan results, max read chars, max command output chars, per-file upload size, and command timeout.

### 5) Execution model and UX flow
- On user prompt:
  1. Build user message (including attachment-derived context)
  2. Append to `st.session_state.messages`
  3. Stream assistant response via `OllamaClient.chat_stream()`
  4. Persist assistant message and rerun UI
- This keeps conversation state entirely in-memory for the session (no persistence layer yet).

## File-level change guidance
- For UI/flow changes, start in `app.py` (`main()` and helper functions near it).
- For API/protocol/error handling changes, edit `ollama_client.py`.
- Keep workspace safety checks intact when modifying scan/read/write/command features.
- If adding persistent history or multi-conversation support, introduce a separate storage module rather than expanding `app.py` monolithically.
