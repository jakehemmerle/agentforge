# Integration Tests

Integration tests run against live Docker services (OpenEMR + MariaDB) and
validate the AI agent's tools against a real API and database.

They are **skipped by default** so they don't break CI pipelines that lack
Docker services. Set `INTEGRATION_TEST=1` to enable them.

## Quick Start

```bash
INTEGRATION_TEST=1 uv run pytest tests/ -v              # All tests (unit + integration)
INTEGRATION_TEST=1 uv run pytest tests/ -v -m integration  # Integration only
```

## Ephemeral Test Environment

Integration tests use `docker-compose.test.yml` — a dedicated compose file
that uses **tmpfs mounts instead of named volumes**. This means:

- Every `docker compose down` destroys all data (DB, config, logs)
- Every `docker compose up` starts from a completely clean slate
- No leftover state from previous runs can affect test results
- Only the services needed for testing are started (mysql + openemr)

The development compose file (`docker-compose.yml`) retains its persistent
volumes for interactive development work. Tests never use it.

To manually start/stop the test environment:

```bash
docker compose -f openemr/docker/development-easy/docker-compose.test.yml up -d --wait
docker compose -f openemr/docker/development-easy/docker-compose.test.yml down
```

## Prerequisites

- **Docker** must be installed and the daemon running
- **uv** for Python package management
- No manual OAuth registration or seed scripts needed

## How It Works

When you run integration tests with `INTEGRATION_TEST=1`, the `integration_env`
session fixture in `tests/conftest.py` bootstraps the environment:

1. Tears down previous test containers (`docker compose down --remove-orphans`)
2. Checks for port conflicts from non-test processes
3. Starts fresh ephemeral test containers (`docker compose up -d --wait`)
4. Waits for OpenEMR health
5. Registers an OAuth2 client and enables it in the DB
6. Runs `scripts/seed_data.py` to create test patients and encounters
7. Configures environment variables so `get_settings()` returns Docker-local config
8. Validates OAuth token access for required endpoints

If you already have credentials (e.g. from a previous run), you can skip
auto-registration by setting:

```bash
export INTEGRATION_TEST_CLIENT_ID="..."
export INTEGRATION_TEST_CLIENT_SECRET="..."
```

### Fixture Dependency Chain

```
integration_env (session)
├── _validate_seed_data (session, autouse) — fail-fast if seed data missing
├── db_conn (module) — raw pymysql connection
├── db_cleanup (function) — LIFO cleanup registration for DB mutations
├── billing_factory (function) — billing row factory + auto-cleanup
├── insurance_factory (function) — insurance row factory + auto-cleanup
└── api_client (function) — configured OpenEMRClient
```

- `integration_env` is the root: it starts Docker, registers OAuth, seeds data,
  and configures env vars. All other integration fixtures depend on it.
- `_validate_seed_data` runs once per session after bootstrap and aborts early
  if expected patients/encounters are missing.
- `db_conn` is module-scoped so each test module gets its own connection.
- `db_cleanup` collects DB cleanup callables and runs them in reverse order.
- `billing_factory` and `insurance_factory` perform table mutations and auto-register cleanup.
- `api_client` is function-scoped so each test gets a fresh client.

## Test Structure

```
tests/
  conftest.py                                # Unit + integration fixtures
  test_validate_claim_integration.py              # 4 classes, 13 test methods
  test_get_encounter_context_integration.py       # get_encounter_context integration tests
  test_draft_encounter_note_integration.py        # 5 classes, 9 test methods
  helpers.py                                      # Shared helpers (find_patient_uuid, etc.)
  integration/
    __init__.py                              # Package init, re-exports config
    config.py                                # Connection params, seed IDs, OAuth scopes
    bootstrap.py                             # Docker lifecycle, OAuth, seed, env config
    factories.py                             # DB-level scenario builders
```

### `tests/integration/config.py`

Single source of truth for all connection parameters and seed data IDs.
Both pytest tests and `evals/run_evals.py` import from here.

### `tests/integration/bootstrap.py`

Reusable infrastructure functions:

| Function | Purpose |
|----------|---------|
| `check_port_conflicts()` | Fail-fast if non-test processes hold required ports |
| `start_services()` | Tear down + port check + start Docker Compose |
| `wait_for_health()` | Poll until OpenEMR responds |
| `register_oauth_client()` | Register + enable OAuth client (sync) |
| `validate_oauth_token()` | Verify OAuth token grants access to required endpoints |
| `run_seed()` | Run seed_data.py via subprocess |
| `configure_environment()` | Set env vars + clear settings cache |
| `get_db_connection()` | Create a pymysql connection |

### `tests/integration/factories.py`

DB-level scenario builders for creating test-specific data:

| Function | Purpose |
|----------|---------|
| `insert_billing_row()` | Insert a billing row, returns cleanup callable |
| `insert_insurance()` | Insert an insurance row, returns cleanup callable |
| `ensure_insurance_for_patient()` | Idempotent: insert if missing |
| `clear_insurance_for_patient()` | Remove all insurance, returns saved rows |

## Test Classes

### TestInternalBillingEndpoint

Tests the `/internal/billing` endpoint against MySQL.

- `test_returns_data_for_known_encounter` — verifies ICD10 + CPT4 rows with correct columns
- `test_empty_for_nonexistent_encounter` — nonexistent encounter returns empty list
- `test_filters_inactive_rows` — `activity=0` rows are excluded
- `test_bad_db_credentials_raises` — bad credentials raise `pymysql.Error`

### TestInsuranceAPI

Tests insurance data fetching via the OpenEMR REST API.

- `test_returns_policies_for_insured_patient` — patient 90001 has primary insurance
- `test_empty_for_uninsured_patient` — patient 90002 has no insurance

### TestValidateClaimImpl

End-to-end tests for the `_validate_claim_impl` function with real API calls.
All tests assert `data_warnings` is present and empty on success paths.

- `test_complete_encounter_is_ready` — complete encounter returns `ready=True`, empty `data_warnings`
- `test_incomplete_encounter_not_ready` — missing ICD10 codes returns `ready=False`, empty `data_warnings`
- `test_nonexistent_patient_raises` — raises `ToolException`
- `test_nonexistent_encounter_raises` — raises `ToolException`

### TestToolWrapper (`test_validate_claim_integration.py`)

Full end-to-end tests for the `@tool` wrapper function.
Tests verify `data_warnings` field is present in tool output and populated on fetch failures.

- `test_full_tool_complete_encounter` — complete encounter via tool wrapper, empty `data_warnings`
- `test_full_tool_incomplete_encounter` — incomplete encounter via tool wrapper, empty `data_warnings`
- `test_tool_wrapper_handles_billing_fetch_error` — bad DB creds degrade gracefully (no crash), `data_warnings` includes `billing_fetch_failed`

### TestDraftSOAPNote (`test_draft_encounter_note_integration.py`)

Tests SOAP note generation with mocked LLM but real encounter context fetching.

- `test_soap_complete_encounter` — complete encounter 900001 produces SOAP note with empty `data_warnings`
- `test_soap_incomplete_encounter` — incomplete encounter 900002 produces warnings about missing vitals

### TestDraftProgressNote (`test_draft_encounter_note_integration.py`)

Tests progress note generation with mocked LLM.

- `test_progress_note` — progress note for complete encounter has `narrative` key

### TestErrorPaths (`test_draft_encounter_note_integration.py`)

Tests error handling in `_draft_encounter_note_impl`.

- `test_nonexistent_patient` — raises `ToolException`
- `test_nonexistent_encounter` — raises `ToolException`
- `test_invalid_note_type_defaults_to_soap` — invalid type defaults to SOAP with warning

### TestOutputShape (`test_draft_encounter_note_integration.py`)

Validates the response structure of draft notes.

- `test_top_level_keys` — response has `draft_note`, `warnings`, `data_warnings`, `disclaimer`
- `test_data_warnings_on_malformed_llm_response` — malformed LLM output populates `data_warnings` with `llm_response_parse_failed`

### TestToolWrapper (`test_draft_encounter_note_integration.py`)

End-to-end test of the `@tool` wrapper with mocked LLM.

- `test_tool_invoke_soap` — full tool invocation for complete encounter

## Pytest Markers

| Marker        | Description                                           | Requires         |
|---------------|-------------------------------------------------------|------------------|
| `unit`        | Fast unit tests with no Docker or network access      | Nothing          |
| `integration` | Tests requiring Docker services (MySQL, OpenEMR API)  | Docker + env vars |
| `slow`        | Tests that take more than a few seconds               | Varies           |

### Running by marker

```bash
cd ai-agent

uv run pytest tests/ -m unit -v                        # Unit only
INTEGRATION_TEST=1 uv run pytest tests/ -m integration -v  # Integration only
uv run pytest tests/ -m "not slow" -v                   # Exclude slow
uv run pytest tests/ -m "not integration" -v            # Exclude integration
```

## Fixtures (conftest.py)

Integration fixtures are only defined when `INTEGRATION_TEST=1`:

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `integration_env` | session | Full bootstrap (OAuth, seed, env config) |
| `_validate_seed_data` | session (autouse) | Fail-fast if seed data missing |
| `db_conn` | module | Raw pymysql connection |
| `db_cleanup` | function | LIFO cleanup registration for DB mutations |
| `billing_factory` | function | Insert billing rows with auto-cleanup |
| `insurance_factory` | function | Insert insurance rows with auto-cleanup |
| `api_client` | function | Configured `OpenEMRClient` |

## Seed Data

Created by `scripts/seed_data.py`:

| Patient | PID | Encounter | Billing | Insurance |
|---------|-----|-----------|---------|-----------|
| John Doe | 90001 | 900001 | ICD10 + CPT4 | Primary (via fixture) |
| Jane Smith | 90002 | 900002 | CPT4 only | None |

## Troubleshooting

**Tests skipped with "set INTEGRATION_TEST=1"**
```bash
INTEGRATION_TEST=1 uv run pytest tests/test_validate_claim_integration.py -v
```

**Connection refused on port 8320**

MySQL container is not running or not healthy:
```bash
docker compose -f openemr/docker/development-easy/docker-compose.test.yml ps
# Both mysql and openemr should show "(healthy)"
```

**OAuth authentication fails**

The OAuth client may not be enabled. Check:
```bash
docker compose -f openemr/docker/development-easy/docker-compose.test.yml exec mysql \
  mariadb -u openemr -popenemr openemr \
  -e "SELECT client_id, client_name, is_enabled FROM oauth_clients;"
```

**Patient/encounter not found**

Seed data may not exist. Run the seed script (idempotent):
```bash
cd ai-agent && uv run python scripts/seed_data.py
```

Verify with SQL:
```bash
docker compose -f openemr/docker/development-easy/docker-compose.test.yml exec mysql \
  mariadb -u openemr -popenemr openemr \
  -e "SELECT pid, fname, lname FROM patient_data WHERE pid IN (90001, 90002);"
```

**Seed data validation fails**
```bash
cd ai-agent && uv run python scripts/seed_data.py
```

**Start fresh (tear down and re-create containers)**
```bash
docker compose -f openemr/docker/development-easy/docker-compose.test.yml down --remove-orphans
INTEGRATION_TEST=1 uv run pytest tests/ -m integration -v
```

## See Also

- [research-seed-data-bd-t1a.md](../../docs/research/research-seed-data-bd-t1a.md) — full schema
  reference and rationale for the seed data design
- [AGENTS.md](../../AGENTS.md) — quick reference for running integration tests
