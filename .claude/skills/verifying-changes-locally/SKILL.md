---
name: verifying-changes-locally
description: Runs the right checks for a change in open-agent-ia and tells apart real failures from environment-dependent ones. Use before committing or pushing, when the user asks to run the tests or check that something works, or when a test failure needs triage.
---

# Verifying changes

The suite mixes three kinds of tests with very different requirements. Running plain
`pytest tests/` produces failures that mean nothing about the change being made, which
burns a debugging cycle. Pick the right gate.

## Default gate — run this after every change

```bash
.venv/bin/python -m pytest tests/ -q -m "not integration" --ignore=tests/test_e2e.py
```

Under two seconds, no Ollama, no browser. **A failure here is real.**

## Lint — this is what CI enforces

CI (`.github/workflows/ci.yml`) runs `ruff check .` and a `py_compile` pass. Ruff is not
in `.venv`, so lint breakage is invisible locally until CI goes red. Before pushing:

```bash
.venv/bin/pip install -q ruff && .venv/bin/ruff check .
```

Config lives in `pyproject.toml`: line length 100, target `py311`.

## Integration tests — need Ollama and a specific model

Marked `@pytest.mark.integration` in `tests/test_conversation_engine.py`; they drive a
real agent against a real model.

```bash
.venv/bin/python -m pytest tests/test_conversation_engine.py -q -m integration
```

The model is hardcoded at `tests/test_conversation_engine.py:24` (`MODEL = ...`). If it
is not pulled, Ollama returns `model 'X' not found` and the tests fail with misleading
assertions like `El agente no retornó ninguna respuesta` — the agent is fine, the model
is absent. Check `ollama list` before believing these failures, and prefer changing the
constant over pulling a large model.

Results vary between runs: a local model may answer from the workspace snapshot instead
of calling a tool. Both are valid, and the assertions allow it.

## E2E tests — self-hosted browser suite

```bash
.venv/bin/python -m pytest tests/test_e2e.py -q          # headless
.venv/bin/python -m pytest tests/test_e2e.py -q --headed # visible browser
```

They spawn their own uvicorn on port **8791** (no need to start the app first) and drive
Chromium through Playwright. They need the browsers installed:
`.venv/bin/playwright install chromium`.

**Known failing:** several `TestFileViewer` / explorer cases time out waiting for
`.file-viewer-content` to become visible — it stays `fv-hidden`. This predates the
current work. Do not treat it as a regression, and do not "fix" it as a side effect of an
unrelated change.

## Triage order

When something fails, establish which category it is before debugging:

1. Does it fail under the default gate? → real, fix it.
2. Integration failure → check `ollama list` for the hardcoded model first.
3. E2E failure → check whether it also fails on a clean checkout of the previous commit
   before assuming the change caused it.

## Running the app to check by hand

```bash
./run.sh                     # port 9901, hot reload
PORT=8001 ./run.sh           # another port
```

`python app_web.py` also works but hardcodes port 8000. Health check:
`curl -s localhost:9901/api/health`.
