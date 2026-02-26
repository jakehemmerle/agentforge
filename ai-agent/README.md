# OpenEMR AI Agent

A LangGraph-based clinical AI agent that assists with appointment lookup,
encounter context retrieval, claim validation, and encounter note drafting
against a live OpenEMR instance.

## Tool Development Pattern

All tools in `ai_agent/tools/` follow the same pattern (see `find_appointments.py` as reference):

1. **Pydantic input schema** — `class MyToolInput(BaseModel)` with `Field` descriptors
2. **`_impl` function** — async, takes `OpenEMRClient` as first arg, contains the logic. Decorated with `@logged_tool` from `_logging.py`.
3. **`@tool` wrapper** — creates the client from settings, calls `_impl`, catches `httpx` exceptions → `ToolException`
4. **Registration** — add to `tools` list in `agent.py` and update `SYSTEM_PROMPT`
5. **Tests** — mirror in `tests/test_<tool_name>.py`, mock the `OpenEMRClient`

All tools return `data_warnings: list[str]` for fetch failure transparency.

## Running Tests

```bash
cd ai-agent
uv run pytest              # All tests
uv run pytest -v           # Verbose
uv run pytest -m unit -v   # Unit tests only (no Docker)
uv run pytest tests/test_find_appointments.py  # Single file
```

Integration tests are EXTREMELY important to run before committing and pushing.

```bash
INTEGRATION_TEST=1 uv run pytest -m integration -v # integration
```

## Adding Dependencies

```bash
cd ai-agent
uv add <package-name>   # Never edit pyproject.toml directly
```

## Docker Service

The ai-agent runs as a Docker service alongside OpenEMR:

```bash
cd openemr/docker/development-easy
docker compose up ai-agent --detach
docker compose logs ai-agent          # View logs
```

Service URL: http://localhost:8350/

## OpenEMR API Notes

- Standard API uses **UUIDs** for patient/encounter resources
- Sub-resources (SOAP notes, vitals) use **integer IDs**
- After fetching by UUID, extract integer IDs for sub-resource calls
- No billing REST API exists — billing data is fetched via the agent's `/internal/billing` endpoint (direct SQL)
- FHIR endpoints return Bundles; parse with `entry[].resource`

## Further Documentation

- [docs/integration-tests.md](docs/integration-tests.md) — full integration test reference
