# Research Report: Structured Logging for Tool Calls (bd-2qj)

## Current Logging State

### What exists

Standard `logging.getLogger(__name__)` is used in three files:

| File | Usage |
|------|-------|
| `ai-agent/ai_agent/server.py` | LangSmith tracing status, OAuth client init at startup |
| `ai-agent/ai_agent/openemr_client.py` | HTTP request debug logs, auth events (info), errors |
| `ai-agent/ai_agent/tools/find_appointments.py` | Logger created but **never used** — no log statements |

All logging uses Python's default plain-text formatter. No structured/JSON output is configured anywhere.

### Missing

- No JSON log formatter configured
- No `python-json-logger` or `structlog` in dependencies
- No tool-call-specific logging (inputs, outputs, latency, errors)
- No `@traceable` usage anywhere in the codebase

---

## Tool Invocation Architecture

### Tool definition

Only one tool exists: `find_appointments` in `ai-agent/ai_agent/tools/find_appointments.py`.

```
@tool("find_appointments", args_schema=FindAppointmentsInput)
async def find_appointments(...) -> dict[str, Any]:
    # Creates OpenEMRClient, calls _find_appointments_impl(), catches httpx errors
```

Key pattern: the `@tool` wrapper handles client setup and error mapping (`httpx` exceptions → `ToolException`), while the actual logic lives in `_find_appointments_impl()` (separated for testability).

### LangGraph wiring

In `agent.py`:

```python
tools = [find_appointments]
model_with_tools = model.bind_tools(tools)
builder.add_node("tools", ToolNode(tools, handle_tool_errors=True))
```

`ToolNode` invokes each tool via LangChain's `BaseTool.ainvoke()`, which triggers the callback system (`on_tool_start`, `on_tool_end`, `on_tool_error`).

### Built-in tracing

LangChain's `BaseTool` has a full callback pipeline. When `LANGSMITH_TRACING` is enabled, tool invocations are **already auto-traced** to LangSmith via these callbacks — inputs, outputs, and errors are captured without any additional decorators.

`ToolNode` itself sets `trace=False` to avoid double-tracing at the node level, relying on each tool's own callback-based tracing.

---

## LangSmith `@traceable` Capabilities

### Version

- **Installed:** `langsmith==0.7.6` (locked in `uv.lock`)
- **Declared:** `langsmith>=0.3.0` in `pyproject.toml`

### `@traceable` API

```python
from langsmith import traceable

@traceable(
    run_type="tool",      # Span type: llm, chain, tool, prompt, retriever, etc.
    name="custom_name",   # Defaults to function name
    metadata={...},       # Static metadata attached to the span
    tags=["tag1"],        # Tags for filtering in LangSmith UI
    process_inputs=fn,    # Custom input serialization
    process_outputs=fn,   # Custom output serialization
)
async def my_function(...):
    ...
```

### Interaction with `@tool`

**Critical finding:** Stacking `@traceable(run_type='tool')` on a `@tool`-decorated function would create **duplicate spans** in LangSmith — one from LangChain's callback system, one from `@traceable`. The `@traceable` decorator is designed for plain Python functions that aren't already instrumented by LangChain.

---

## Available Structured Logging Packages

### In current deps

None. No structured logging packages are in `pyproject.toml` or `uv.lock`.

### Candidates

| Package | Notes |
|---------|-------|
| `python-json-logger` | Lightweight, drop-in JSON formatter for stdlib logging. Most common choice. |
| `structlog` | More powerful (processors, context binding), but heavier dependency. |

The issue pseudocode implies stdlib logging with JSON formatting, which aligns with `python-json-logger`.

---

## Proposed Approach

### 1. `logged_tool` decorator (stdout/Docker logging)

Create `ai-agent/ai_agent/tools/_logging.py`:

```python
import logging
import time
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger("ai_agent.tools")

def logged_tool(func: Callable) -> Callable:
    """Add structured logging around a tool's inner implementation."""
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        tool_name = func.__name__
        logger.info("tool_call_start", extra={
            "tool": tool_name,
            "input": _sanitize_input(kwargs),
        })
        start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            latency_ms = round((time.monotonic() - start) * 1000)
            logger.info("tool_call_end", extra={
                "tool": tool_name,
                "latency_ms": latency_ms,
                "status": "success",
                "output_summary": str(result)[:200],
            })
            return result
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000)
            logger.error("tool_call_error", extra={
                "tool": tool_name,
                "latency_ms": latency_ms,
                "status": "error",
                "error_type": type(e).__name__,
                "error_msg": str(e),
            })
            raise
    return wrapper
```

**Apply to `_find_appointments_impl`** (the inner function), not the `@tool` wrapper. This avoids conflicts with LangChain's callback/tracing pipeline.

### 2. JSON log formatter for Docker

Add `python-json-logger` to deps and configure a JSON formatter in a `logging_config.py` or in `server.py` lifespan. This makes all existing `logger.*()` calls across the codebase output JSON.

### 3. Skip `@traceable` on tool functions

Since `@tool` already traces to LangSmith via callbacks, adding `@traceable` would duplicate spans. If extra LangSmith metadata is needed later, use `langsmith.run_helpers.get_current_run_tree()` to enrich the existing span.

---

## Open Questions and Decisions

1. **Decorator target:** Apply `logged_tool` to inner impl functions (`_find_appointments_impl`) or the `@tool` wrapper? Recommend inner function to avoid LangChain callback conflicts.

2. **JSON logging package:** `python-json-logger` (simple, lightweight) vs `structlog` (more features, heavier). Recommend `python-json-logger` for simplicity.

3. **Skip `@traceable`?** The issue pseudocode stacks `@traceable` with the custom decorator, but this would duplicate LangSmith spans. Recommend skipping it and documenting that LangChain callbacks handle LangSmith tracing.

4. **Blocker status:** Issue is blocked by `bd-20x` (Configure LangSmith tracing). The config infrastructure already exists (`Settings` has `langsmith_tracing`, `langsmith_api_key`, `langsmith_project`; server logs tracing status). May already be resolved — needs confirmation.

5. **Input sanitization:** Should the decorator redact any fields from tool inputs (e.g., patient IDs for privacy)? Or log everything for debugging?
