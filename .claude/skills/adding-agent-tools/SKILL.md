---
name: adding-agent-tools
description: Adds a new tool to the open-agent-ia agent registry, or changes an existing tool's parameters, approval behavior or sandboxing. Use when the user wants the agent to be able to do something new (call an API, manipulate files, run something), or mentions tools, the tool registry, approvals, or write operations.
---

# Adding an agent tool

Tools live in `tools/`, inherit from `BaseTool` (`tools/base.py`) and are registered in
`ToolRegistry.AVAILABLE_TOOLS` (`tools/registry.py`).

## Checklist

```
- [ ] 1. Class in tools/<area>.py inheriting BaseTool
- [ ] 2. name, description, is_write_operation set as class attributes
- [ ] 3. get_parameters() -> List[ToolParameter]
- [ ] 4. execute(**kwargs) -> ToolResult
- [ ] 5. Entry in ToolRegistry.AVAILABLE_TOOLS
- [ ] 6. Mentioned in the tool list inside llm/prompts.py
```

## The contract

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "One line — this goes straight into the model's prompt."
    is_write_operation = False

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="path", description="...", type="string", required=True),
        ]

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="...")
```

`BaseTool.__init__` receives `workspace_root` and `current_cwd`; the registry passes them
and re-instantiates every tool when the cwd changes.

`to_ollama_tool()` builds the function-calling JSON schema from `get_parameters()`
automatically — never hand-write that schema. `type` must be a JSON Schema type string
(`"string"`, `"boolean"`, `"integer"`, `"object"`, `"array"`).

## description is a prompt, not documentation

Local 3B–8B models pick tools almost entirely from `description`. Say what it does and
when to use it, and distinguish it from neighbouring tools. `"Reads a file"` competes
with `search_files`; `"Reads the full contents of a single file given its path. Use when
you already know the exact path."` does not.

## is_write_operation drives the security layer

`ApprovalManager` (`security/approval.py`) blocks execution pending user approval when
the level is `WRITE_ONLY` and the tool is a write. Anything that mutates the filesystem,
the network, or external state MUST set `is_write_operation = True`.

Two behaviors to know before touching this:

- `run_command` is classified dynamically, not by the flag — see
  `ToolRegistry.is_tool_write_operation()`.
- An unknown tool name is assumed to be a write. Fail closed; keep it that way.

Tools that execute arbitrary code belong behind `security/sandbox.py`, like
`ExecutePythonTool`, which is bounded by `PYTHON_SANDBOX_TIMEOUT_SECONDS`.

## Return errors, don't raise

`execute()` should return `ToolResult(success=False, error=...)` so the agent can read the
failure and retry differently. Populate `output` even on failure — that text is what the
model actually sees. Raise `ToolError` only for genuinely unrecoverable cases.

Keep paths inside `workspace_root`; it is the security boundary, not a hint.

## Runtime-registered tools

MCP tools arrive at runtime through `register_dynamic_tool(name, ollama_tool, executor)`
and are executed via `execute_dynamic()`. Those do **not** go in `AVAILABLE_TOOLS` — see
`tools/mcp_manager.py`.
