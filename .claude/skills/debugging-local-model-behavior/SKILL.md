---
name: debugging-local-model-behavior
description: Diagnoses why a small local model misbehaves in open-agent-ia — malformed JSON, ignored or repeated tool calls, loops, forgotten context, wrong mode. Use when the agent works with a large or hosted model but fails with a local one, when output is not valid JSON, or when the agent repeats a tool or never finishes.
---

# Debugging local model behavior

The 3B–8B models this project targets fail in characteristic ways. Most of the machinery
to handle that already exists — the fix is almost always to route the call through it,
not to add another regex repair.

**Diagnose before changing code.** Reproduce with a larger local model (or a hosted
provider). If the problem disappears, it is a model-capability problem and belongs in the
constraint layers below. If it reproduces everywhere, it is an ordinary bug.

## Malformed or unparseable JSON

Do not add parsing repair. Constrain generation instead.

Decision calls — intent parsing, plans, reflection, memory extraction — must pass a JSON
schema from `llm/schemas.py` as `fmt`, and run at `DECISION_TEMPERATURE` (`config.py`,
default 0.2) rather than the session temperature. Creative temperature on a decision call
is a common cause of drifting output.

```python
from llm.schemas import PLAN_SCHEMA
self._call_model(messages, fmt=PLAN_SCHEMA, temperature=DECISION_TEMPERATURE)
```

Providers degrade to legacy `"json"` mode automatically when they reject a schema, so
prompts must keep describing the expected shape. Never remove the format description from
a prompt just because a schema exists.

If a new decision call needs constraining, add a schema to `llm/schemas.py`; keep it
minimal, with only genuinely required fields in `required`.

## The model ignores tools, or emits them as prose

Native function calling is gated by `model_supports_tools()`. When it is unsupported the
agent falls back to the text parser in `core/conversation/natural_loop.py`, which reads
tool intent out of prose.

Check which path is running before debugging — the symptoms differ. `ollama show <model>`
lists capabilities; `GET /api/models` reports them per model.

Both paths coexist by design: even in the native loop, prose that looks like a tool call
is re-parsed and re-injected as if it had been a native call. A model that emits tools as
text is expected, not broken.

## The agent repeats the same tool, or never finishes

`core/agent.py` tracks a signature per `(tool, args)`. A legitimate repeat is allowed
(`git status` after a change is not a loop); from the third identical call it returns a
correction instead of executing, and after three corrections it forces a close with a
summary.

If a model still loops, the tool `description` is usually the problem — the model cannot
tell two tools apart, or cannot tell that it already has the answer. Fix the description
(see `adding-agent-tools`) before touching the loop limits.

`MAX_AGENT_STEPS` and `AGENT_TASK_TIMEOUT` (`config.py`) bound the run.

## The model forgets earlier tool results

Within a run, tool calls and results live only in `extra_messages`, in the provider's
native format. They are persisted into the conversation as text **once**, when the run
ends by any path — including cancellation and error.

This asymmetry is deliberate: it stops every result appearing twice in the prompt. When
adding a new exit path to the agent loop, it must flush that pending history, or the
model loses the turn's work. Route new exits through the existing finish helper rather
than returning directly.

## Context exhaustion

Small models have small windows. `get_context_length()` returns 0 when unknown, so it
cannot be relied on for arithmetic. Symptoms are silent: the system prompt or early
history falls out and the model starts ignoring instructions it followed a moment ago.

The workspace snapshot (`core/conversation/context_builder.py`) and RAG results are the
largest variable inputs — suspect them first with a large workspace.

## Provider-specific, not model-specific

If the failure only happens on one provider, it is a message-formatting bug, not a model
limitation. See `adding-llm-providers` for the tool-calling message protocol and the
multiple-system-message pitfall.
