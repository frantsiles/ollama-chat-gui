---
name: adding-llm-providers
description: Adds a new LLM provider to open-agent-ia or fixes provider-specific bugs in tool calling, structured outputs, and message formatting. Use when the user mentions adding a provider (Groq, vLLM, llama.cpp, Mistral, OpenRouter...), when a provider misbehaves only with certain models, or when wiring a provider through the factory, config, API and UI selector.
---

# Adding an LLM provider

A provider is only "done" when all six touchpoints are wired. Missing one produces a
provider that works in `curl` but not in the app.

## Checklist

```
- [ ] 1. llm/providers/<name>.py       implements LLMProvider
- [ ] 2. llm/client.py                 branch in create_client()
- [ ] 3. config.py                     env vars (base URL, API key)
- [ ] 4. web/api.py                    add to _valid_providers set
- [ ] 5. web/static/index.html         <option> in #llm-provider-select
- [ ] 6. README.md                     row in the env var table
```

## 1. Implement the contract

`llm/base.py` defines `LLMProvider`. Five abstract methods:

| Method | Returns |
|---|---|
| `chat` | response text |
| `chat_stream` | iterable of text chunks |
| `chat_with_tools` | `{"content": str, "tool_calls": [...]}` |
| `list_models` | list of model names |
| `model_supports_tools` | bool |

Optional overrides with defaults: `get_model_capabilities`, `get_model_info`,
`get_context_length`, `is_available`.

Set `self.last_usage` after each call — the UI reads token counts from it.

**If the API is OpenAI-compatible, do not write a new provider.** Add a branch in
`create_client()` pointing at `OpenAICompatProvider` with the right `base_url`, the way
`lmstudio`, `groq` and `copilot` already do.

## 2. The `fmt` contract

`fmt` is `None` (free text), `"json"` (JSON, no schema), or a **dict holding a JSON
schema** (structured output). Schemas live in `llm/schemas.py`.

Map it to whatever the provider calls it, and **degrade instead of failing** when the
provider rejects a schema:

- Ollama: goes in `format`. On an error mentioning `format`, retry once with `fmt="json"`.
- OpenAI-compatible: `response_format: {type: "json_schema", ...}`. On HTTP 400, retry
  once with `fmt="json"`.

Degrading matters because this project targets local models on older servers. Prompts
still describe the expected JSON, so the legacy path stays correct.

## 3. Tool calling message protocol

Every provider has its own shape for "assistant requested tools" and "here is the
result". `LLMProvider` supplies the Ollama-style default; override both methods when the
provider differs:

- `format_assistant_tool_message(content, tool_calls)`
- `format_tool_result_message(tool_call, output)`

Reference implementations: `llm/providers/openai_compat.py` (needs `tool_call_id`,
arguments serialized as a JSON **string**) and `llm/providers/anthropic.py` (`tool_use`
blocks in an assistant message, `tool_result` blocks inside a **user** message).

**`chat_with_tools` MUST preserve the provider's `id` on each tool call.** Results are
paired back to their call by that id. Dropping it silently breaks multi-tool turns:

```python
tool_calls.append({
    "id": tc.get("id"),
    "function": {"name": fn.get("name", ""), "arguments": args},
})
```

Normalize `arguments` to a dict — OpenAI sends a JSON string, Ollama sends a dict.

## Known pitfalls

**Multiple system messages.** This app sends several: main prompt, workspace snapshot,
and persisted tool results. Providers with a dedicated system parameter must
**concatenate all of them**. Keeping only the last one silently drops the main prompt —
this was a real bug in the Anthropic provider.

**Tool support is per-model, not per-provider.** `model_supports_tools()` gates the
native tool calling loop; when it returns False the agent falls back to the text parser
in `core/conversation/natural_loop.py`. Guessing wrong here degrades the agent silently.

## Verify

Native tool calling is the part that breaks. Test it end to end, not just `chat()`:

```bash
curl -s "http://localhost:9901/api/models?provider=<name>"
```

Then run an Agent-mode task in the UI that forces a tool (e.g. "lista los archivos de
este repo") and confirm the model receives the result and answers from it.
