---
name: langsmith
description: "Interact with LangSmith for observability: view traces, threads, errors, and metrics"
argument-hint: "[action: traces|threads|errors|metrics|verify]"
---

Interact with the LangSmith observability dashboard for the openemr-agent project. Use Chrome browser automation to inspect traces, threads, errors, and dashboard metrics. Prefer JavaScript extraction over screenshot-based navigation wherever possible.

## Prerequisites

- The ai-agent Docker service must be running: `docker compose ps` should show `ai-agent` as healthy
- LangSmith tab should be available in Chrome, or navigate to: `https://smith.langchain.com`
- Project name: `openemr-agent`

## Actions

### `traces` — View recent traces

1. Get browser tab context with `tabs_context_mcp`
2. Navigate to the LangSmith project page (find the existing LangSmith tab or create a new one)
3. Navigate to: `https://smith.langchain.com` > Tracing > openemr-agent
4. Click "Load latest" if the banner appears
5. The project page has top navigation tabs: **Runs, Threads, Evaluators, Automations, Insights**
6. The Runs tab shows all traces in a `<table>` with columns: Name, Input, Output, Error, Start Time, Latency, Dataset, Annotation Queue, Tokens, Cost, First Token, Tags, Metadata, Feedback, Reference Example
7. The filter bar has a **Traces/Runs toggle**, "Default View" dropdown, time range picker, and "+ Add filter"
8. **Use JS to extract runs** (preferred over screenshots):
   ```javascript
   (() => {
     const rows = document.querySelectorAll('table tbody tr');
     return Array.from(rows).map(row => {
       const cells = Array.from(row.querySelectorAll('td'));
       const statusSvg = cells[1] ? cells[1].querySelector('svg') : null;
       const color = statusSvg ? getComputedStyle(statusSvg).color : '';
       const isError = color.includes('249, 112, 102');
       return {
         name: cells[2]?.textContent.trim() || '',
         input: cells[3]?.textContent.trim() || '',
         output: cells[4]?.textContent.trim() || '',
         error: cells[5]?.textContent.trim() || '',
         startTime: cells[6]?.textContent.trim() || '',
         latency: cells[7]?.textContent.trim() || '',
         tokens: cells[10]?.textContent.trim() || '',
         cost: cells[11]?.textContent.trim() || '',
         status: isError ? 'error' : 'success'
       };
     });
   })()
   ```
9. Click on any trace row to open the detail peek panel showing:
   - **Waterfall view** (left panel): `chat_request → agent → ChatAnthropic → route → tools → [tool_name] → agent → ChatAnthropic → route`
   - **Run detail** (right panel) with tabs: **Run, Feedback, Metadata**
   - **Run tab**: Input/Output messages, Error details (highlighted in red if present)
   - **Metadata tab**: Fields vary by node level (see Metadata Reference below)
10. **Use JS to extract the waterfall tree** (preferred over screenshots):
    ```javascript
    (() => {
      const nodes = document.querySelectorAll('[data-testid^="run-tree-node-"]');
      return Array.from(nodes).map(node => ({
        name: node.getAttribute('data-testid').replace('run-tree-node-', ''),
        detail: node.textContent.trim()
      }));
    })()
    ```
11. **Use JS to extract metadata from the detail panel**:
    ```javascript
    (() => {
      const pane = document.querySelector('[data-testid="split-view-pane"]');
      if (!pane) return null;
      // Click Metadata tab
      const metaTab = Array.from(pane.querySelectorAll('button')).find(b => b.textContent.trim() === 'Metadata');
      if (metaTab) metaTab.click();
      // Extract key-value pairs from metadata section
      const metaBtn = Array.from(pane.querySelectorAll('button')).find(b => b.textContent.trim() === 'metadata');
      const container = metaBtn ? metaBtn.parentElement.parentElement : null;
      const anchors = container ? Array.from(container.querySelectorAll('a')).map(a => a.textContent.trim()) : [];
      const metadata = {};
      for (let i = 0; i < anchors.length; i += 2) metadata[anchors[i]] = anchors[i + 1] || '';
      return metadata;
    })()
    ```

### `threads` — View session/thread grouping

1. Navigate to the project page
2. Click the **Threads** tab in the top navigation bar
3. Threads are grouped by `session_id` / `thread_id`
4. Thread table columns: **Thread** (name + turn count + token count inline), **First Input**, **Last Output**, **First Start Time**, **Last Start Time**, **P50 Latency**, **P99 Latency**, **Feedback**
5. The right sidebar shows **Stats**: Thread Count, Trace Count, Total Tokens (with cost), Median Tokens, Error Rate, % Streaming, First Token P50/P99, Latency P50/P99
6. Below Stats, **Filter Shortcuts** offers quick filters by Run Name, Run Type, and Status
7. Click a thread to see all runs within that session
8. **Use JS to extract threads + stats** (preferred over screenshots):
   ```javascript
   (() => {
     const rows = document.querySelectorAll('table tbody tr');
     const threads = Array.from(rows).map(row => {
       const cells = Array.from(row.querySelectorAll('td'));
       return {
         thread: cells[0]?.textContent.trim() || '',
         firstInput: cells[1]?.textContent.trim() || '',
         lastOutput: cells[2]?.textContent.trim() || '',
         firstStart: cells[3]?.textContent.trim() || '',
         lastStart: cells[4]?.textContent.trim() || '',
       };
     });
     const body = document.body.innerText;
     const statsMatch = body.match(/Stats[\s\S]*?(?=Filter Shortcuts|$)/);
     return { threads, stats: statsMatch ? statsMatch[0] : '' };
   })()
   ```

### `errors` — Investigate error traces

1. Navigate to the project Runs tab
2. Error rows have red status icons (SVG color `rgb(249, 112, 102)`) and/or red text in the Error column
3. **Use JS to find all error rows** (preferred over visual scanning):
   ```javascript
   (() => {
     const rows = document.querySelectorAll('table tbody tr');
     return Array.from(rows).filter(row => {
       const svg = row.querySelectorAll('td')[1]?.querySelector('svg');
       return svg && getComputedStyle(svg).color.includes('249, 112, 102');
     }).map(row => {
       const cells = Array.from(row.querySelectorAll('td'));
       return {
         name: cells[2]?.textContent.trim() || '',
         input: cells[3]?.textContent.trim() || '',
         error: cells[5]?.textContent.trim() || '',
         latency: cells[7]?.textContent.trim() || ''
       };
     });
   })()
   ```
4. Click on an error trace to see the waterfall
5. In the waterfall, error nodes have orange/red indicators
6. **Use JS to click a specific waterfall node**:
   ```javascript
   ((nodeName) => {
     const node = document.querySelector(`[data-testid="run-tree-node-${nodeName}"]`);
     if (node) { node.click(); return 'clicked ' + nodeName; }
     return 'node not found: ' + nodeName;
   })('get_encounter_context')
   ```
7. Click the error node to see:
   - **Run tab**: Error message highlighted in red/pink box, Input parameters, Output (if any)
   - **Metadata tab**: Standard metadata fields (see Metadata Reference). Note: `@logged_tool` error classification fields (`error_type`, `error_category`) are logged to Docker structured logs but do NOT appear in the LangSmith Metadata tab.
8. The `@logged_tool` decorator in `ai_agent/tools/_logging.py` classifies errors in **Docker logs**:
   - `auth_error` (HTTP 401/403)
   - `api_timeout` (httpx timeout)
   - `not_found` (HTTP 404)
   - `validation_error` (ToolException with validation keywords)
   - `unknown` (everything else)
9. To check error classification in Docker logs:
   ```bash
   docker compose logs ai-agent --tail=50 2>&1 | grep -E "tool_call_error"
   ```

### `metrics` — View dashboard metrics

1. Navigate to the project page
2. Click the **Dashboard** button (top right of project page)
3. This opens the Monitoring page with top-level tabs: **Monitoring, Dashboards, Alerts**
4. The Monitoring tab shows charts organized by section. Use "Last 7 days" / "Last 1 day" time filter (top right) to adjust the window.
5. Dashboard sections and charts (section headings are `<h2>`, chart titles are `<h3>`):
   - **Traces**: Trace Count (success/error), Trace Latency (P50/P99), Trace Error Rate
   - **LLM Calls**: LLM Count, LLM Latency
   - **Cost & Tokens**: Total Cost, Cost per Trace, Output Tokens, Output Tokens per Trace, Input Tokens, Input Tokens per Trace
   - **Tools**: Run Count by Tool, Median Latency by Tool, Error Rate by Tool (broken down per tool name)
   - **Run Types**: Run Count by Name (depth=1), Median Latency by Run Name (depth=1), Error Rate by Run Name (depth=1)
   - **Feedback Scores**: (if feedback is configured)
6. **Use JS to list all dashboard sections and charts**:
   ```javascript
   (() => {
     const sections = Array.from(document.querySelectorAll('h2')).map(h => h.textContent.trim());
     const charts = Array.from(document.querySelectorAll('h3')).map(h => h.textContent.trim());
     return { sections, charts };
   })()
   ```
7. Note: Chart data is rendered as inline SVGs. Axis labels and tick values are in `<text>` elements but summary values are not easily extractable — use screenshots for visual chart inspection when needed.

### `verify` — Run observability verification

Runs a quick end-to-end verification of all observability features:

1. **Generate test traces** via curl:
   ```bash
   # Simple chat (no tool call)
   curl -s -X POST http://localhost:8350/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Hello", "session_id": "verify-session"}'

   # Tool call trace
   curl -s -X POST http://localhost:8350/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Find appointments for today", "session_id": "verify-session"}'

   # Error trace
   curl -s -X POST http://localhost:8350/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Get encounter context for patient 99999999", "session_id": "verify-error"}'
   ```

2. **Check Docker structured logs**:
   ```bash
   docker compose logs ai-agent --tail=50 2>&1 | grep -E "tool_call_(start|end|error)"
   ```

3. **Verify in LangSmith** using Chrome — prefer JS over manual navigation:
   - Navigate to project, click "Load latest"
   - **Check traces exist via JS**:
     ```javascript
     ((sessionId) => {
       const rows = document.querySelectorAll('table tbody tr');
       const matches = Array.from(rows).filter(row => {
         return Array.from(row.querySelectorAll('td')).some(td => td.textContent.includes(sessionId));
       });
       return { found: matches.length > 0, count: matches.length };
     })('verify-session')
     ```
   - **Extract waterfall via JS** to verify tool calls appear:
     ```javascript
     (() => {
       const nodes = document.querySelectorAll('[data-testid^="run-tree-node-"]');
       return Array.from(nodes).map(n => n.getAttribute('data-testid').replace('run-tree-node-', ''));
     })()
     ```
   - Click into a trace to verify waterfall, tool I/O, and metadata
   - Check Threads tab for session grouping
   - Check Dashboard for updated metrics

## Key Architecture

### Tracing Configuration

Tracing is configured in `ai-agent/ai_agent/config.py` via Pydantic Settings:
```
LANGSMITH_API_KEY=<key>
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=openemr-agent
```

### Session/Thread Mapping

In `ai-agent/ai_agent/server.py`, each request sets:
```python
config = {
    "configurable": {"thread_id": req.session_id},
    "metadata": {
        "session_id": req.session_id,
        "request_id": str(uuid.uuid4()),
    },
    "run_name": "chat_request",
}
```

### Structured Logging

`ai-agent/ai_agent/server.py` configures JSON logging via `python-json-logger`:
- Output: stdout (captured by Docker)
- Fields: timestamp, level, name, message + extra fields from `@logged_tool`

### Tool Instrumentation

`ai-agent/ai_agent/tools/_logging.py` provides `@logged_tool` decorator:
- Logs `tool_call_start` with tool name and input
- Logs `tool_call_end` with latency_ms, status, output_summary
- On error: logs `tool_call_error` with error_type, error_category, stack_trace
- Note: The decorator attempts to enrich LangSmith run tree metadata via `get_current_run_tree()`, but this does not currently propagate to the visible tool node in the LangSmith waterfall. Error classification is only reliably visible in Docker structured logs.

## Metadata Reference

Metadata fields in the LangSmith trace detail panel vary by node type:

| Node | Metadata Fields |
|------|----------------|
| `chat_request` (root) | `LANGSMITH_PROJECT`, `LANGSMITH_TRACING`, `ls_run_depth`, `request_id`, `session_id`, `thread_id` |
| `agent` / `tools` | Above + `langgraph_node`, `langgraph_step`, `langgraph_path`, `langgraph_triggers`, `checkpoint_ns` |
| `ChatAnthropic` | Above + model params (`temperature`, `max_tokens`, `max_retries`) under model invocation params |
| Tool nodes (e.g. `get_encounter_context`) | Above + `tool_call_id`, `langgraph_node: tools` |

All nodes also include a **RUNTIME** section: `langchain_core_version`, `library`, `platform`, `runtime`, `runtime_version`, `sdk`, `sdk_version`.

## DOM Selectors Reference

Stable `data-testid` selectors for browser automation:

| Selector | Purpose |
|----------|---------|
| `[data-testid^="run-tree-node-"]` | Waterfall tree nodes (suffix = node name) |
| `[data-testid="run-status-icon-success"]` | Green success status icons in runs table |
| `[data-testid="run-status-icon-error"]` | Red error status icons in runs table |
| `[data-testid="run-status-icon-pending"]` | Pending status icons |
| `[data-testid="split-view-pane"]` | Trace detail right panel (peek view) |
| `[data-testid="split-view-pane-expand-button"]` | Expand peek to full view |
| `[data-testid="split-view-pane-close-button"]` | Close peek view |
| `[data-testid="date-time-range-picker"]` | Time range filter |
| `[data-testid^="checkbox-row-"]` | Row selection checkboxes (suffix = row index) |
| `[data-testid="fold-toggle"]` | Collapse/expand toggle |
| `table tbody tr` | Runs/Threads table rows |
| `table thead th` | Table column headers |

Status icon colors (via `getComputedStyle(svg).color`):
- Success: `rgb(2, 174, 69)`
- Error: `rgb(249, 112, 102)`

## JavaScript Quick Reference

```javascript
// Check current page context
window.location.href.includes('/projects/p/')   // on project page
window.location.href.includes('/dashboards/')    // on monitoring dashboard
window.location.href.includes('tab=1')           // on threads tab

// Navigate tabs programmatically
document.querySelector('[data-testid="split-view-pane"]')
  .querySelectorAll('button')
  .forEach(b => { if (b.textContent.trim() === 'Metadata') b.click(); });

// Click a waterfall node by name
document.querySelector('[data-testid="run-tree-node-get_encounter_context"]').click();

// Extract table column headers
Array.from(document.querySelectorAll('table thead th')).map(th => th.textContent.trim());
```

## Navigation Reference

| Page | URL Pattern |
|------|-------------|
| Project runs | `smith.langchain.com/.../projects/p/<id>` |
| Project threads | `smith.langchain.com/.../projects/p/<id>?tab=1` |
| Monitoring | `smith.langchain.com/.../dashboards/projects/<id>` |
| Trace detail | Click any row in runs list, or use `?peek=<trace-id>` |

## Tips

- Use "Load latest" button when traces don't appear immediately (LangSmith has a slight delay)
- The Metadata tab on any node shows session_id, thread_id, and request_id; model params are only on ChatAnthropic nodes
- Filter by time range using "Last 1 day" button to focus on recent activity
- The waterfall view shows the full agent execution flow: agent decisions, tool calls, and LLM invocations
- Token counts shown next to each node indicate input+output tokens for that step
- Prefer JS extraction over screenshots for structured data (tables, metadata, waterfall nodes)
- Use screenshots only for chart visualization on the monitoring dashboard
- Error classification (`error_type`, `error_category`) is available in Docker logs via `@logged_tool`, not in LangSmith metadata
