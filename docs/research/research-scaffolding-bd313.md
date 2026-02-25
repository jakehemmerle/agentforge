# Research Report: Python Project Scaffolding (bd-313)

## Step 1: Environment Versions

```
uv 0.9.17 (2b5d65e61 2025-12-09)
Python 3.13.6
```

**Analysis:** Both `uv` and Python 3.13 are available on the host. uv is recent and fully supports `pyproject.toml` project management. Python 3.13 is modern and well-supported by all target packages. No compatibility concerns.

---

## Step 2: Docker Compose & .gitignore

### docker-compose.yml key findings

- **Services:** mysql (MariaDB 11.8), openemr (flex image), selenium, phpmyadmin, couchdb, openldap, mailpit
- **OpenEMR ports:** 8300 (HTTP), 9300 (HTTPS)
- **MySQL:** port 8320, root password `root`, user `openemr`/`openemr`
- **OAuth settings already enabled:**
  - `OPENEMR_SETTING_oauth_password_grant: 3` (password grant enabled for all roles)
  - `OPENEMR_SETTING_rest_system_scopes_api: 1` (system scopes enabled)
  - `OPENEMR_SETTING_rest_api: 1` (REST API enabled)
  - `OPENEMR_SETTING_rest_fhir_api: 1` (FHIR API enabled)
  - `OPENEMR_SETTING_site_addr_oath: 'https://localhost:9300'`
- **Repo is mounted read-only** at `/openemr:ro` and read-write at `/var/www/localhost/htdocs/openemr:rw`
- **Network:** Services use Docker internal DNS (e.g., `mysql`, `openemr`, `couchdb`)

**Analysis for ai-agent service (bd-coc):** The new ai-agent container will need to connect to `openemr` on port 80 internally (matching `OPENEMR_BASE_URL=http://openemr:80` from the .env.example spec). It should join the same Docker network and depend on the openemr service health check.

### .gitignore key findings

- `.env` is already gitignored (good -- our `.env.example` will be tracked but `.env` won't)
- `vendor/`, `node_modules/`, IDE configs all ignored
- No Python-specific ignores yet (will need `__pycache__/`, `.venv/`, `*.pyc` etc. -- but these can go in `ai-agent/.gitignore` or the root)

---

## Step 3: Existing Python Files

```
No files found
```

**Analysis:** Zero Python files exist in the repo. This is a pure PHP/JS project. The `ai-agent/` directory will be the first Python code. No naming conflicts, no existing conventions to follow. We have a clean slate for Python project structure.

---

## Step 4: Bead Specification (bd-313)

Full spec retrieved. Key details:

### Directory

`ai-agent/` at project root

### Structure

```
ai-agent/
  pyproject.toml
  .env.example
  ai_agent/
    __init__.py
    config.py          # Settings via pydantic-settings or python-dotenv
    openemr_client.py  # OAuth2 HTTP client (Epic 1, task 3)
    agent.py           # LangGraph StateGraph definition
    server.py          # FastAPI + SSE server
    tools/
      __init__.py
      find_appointments.py
  scripts/
    seed_data.py       # Synthetic data seeder
  tests/
    __init__.py
    conftest.py
```

### Dependencies specified

- langgraph >= 0.2.70
- langchain-anthropic (for Claude)
- langchain-core >= 1.2.4
- langsmith >= 0.3.0
- fastapi
- uvicorn[standard]
- httpx >= 0.27.0
- python-dotenv
- pydantic >= 2.0
- pytest, pytest-asyncio, pytest-httpx (dev deps)

### .env.example vars

```
ANTHROPIC_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=openemr-agent
OPENEMR_BASE_URL=http://openemr:80
OPENEMR_CLIENT_ID=
OPENEMR_CLIENT_SECRET=
```

### Dependencies graph

- Parent: bd-re0 (Epic 1: Basic Agent)
- Blocks: bd-2us (OAuth2 client), bd-coc (Docker Compose service)
- No blockers -- this is the foundation task

---

## Step 5: Latest Package Versions (PyPI)

| Package | Latest | Bead Min Spec | Recommended |
|---------|--------|---------------|-------------|
| langgraph | **1.0.9** | >= 0.2.70 | >= 0.2.70 (spec says this; latest is 1.0.9 which is a major bump -- keep the floor at 0.2.70 for compat, but uv will resolve to 1.0.9) |
| langchain-anthropic | **1.3.3** | (unversioned) | >= 1.0.0 |
| langchain-core | **1.2.15** | >= 1.2.4 | >= 1.2.4 |
| langsmith | **0.7.6** | >= 0.3.0 | >= 0.3.0 |
| fastapi | **0.132.0** | (unversioned) | >= 0.115.0 |
| uvicorn | **0.41.0** | (unversioned, with [standard]) | >= 0.30.0 |
| httpx | **0.28.1** | >= 0.27.0 | >= 0.27.0 |
| pydantic | **2.12.5** | >= 2.0 | >= 2.0 |

**Analysis:** All packages are actively maintained. The langgraph spec says `>= 0.2.70` but the latest is 1.0.9 (stable 1.x release). Since we're using `uv add` (per CLAUDE.md rules), uv will resolve to latest compatible versions automatically. The version floors in the bead spec are reasonable minimums. No compatibility issues expected with Python 3.13.

**Note:** The spec lists `python-dotenv` but config.py says "pydantic-settings or python-dotenv". Since we're already using pydantic, `pydantic-settings` would be more idiomatic (typed config with validation). Consider using `pydantic-settings` instead of bare `python-dotenv`.

---

## Step 6: OAuth2 Implementation in OpenEMR

### Files referencing OAuth in src/RestControllers/

- `AuthorizationController.php` -- Main OAuth2 server (League OAuth2 Server)
- `TokenIntrospectionRestController.php`
- `Authorization/OAuth2DiscoveryController.php`
- `Authorization/BearerTokenAuthorizationStrategy.php`
- `Authorization/OAuth2PublicJsonWebKeyController.php`
- `SMART/SMARTAuthorizationController.php`
- `SMART/SMARTConfigurationController.php`
- `SMART/ScopePermissionParser.php`
- `Subscriber/OAuth2AuthorizationListener.php`
- `Config/RestConfig.php`
- `ApiApplication.php`
- `RestControllerHelper.php`
- `FHIR/FhirMetaDataRestController.php`
- `Subscriber/SessionCleanupListener.php`
- `Subscriber/SiteSetupListener.php`
- `Subscriber/ExceptionHandlerListener.php`

### Key findings from AuthorizationController.php

1. **OAuth2 Library:** Uses `League\OAuth2\Server` (league/oauth2-server PHP package)

2. **Supported Grant Types:**
   - `authorization_code` -- Standard OAuth2 auth code flow
   - `password` -- Resource Owner Password Credentials (enabled via `oauth_password_grant: 3` in docker-compose)
   - `client_credentials` -- For system-to-system (requires JWK)
   - `refresh_token` -- Token refresh

3. **Client Registration** (`clientRegistration()` method):
   - Endpoint accepts JSON POST
   - Generates `client_id`, `client_secret` (for confidential apps), `registration_access_token`
   - For `application_type: 'private'` -> confidential client with secret, `client_role: 'user'`
   - System scopes (`system/`) require JWK or jwks_uri
   - User scopes (`user/`) only for confidential clients
   - Patient scopes for public clients

4. **Token Endpoint** (`oauthAuthorizeToken()` method):
   - Accepts `grant_type` in POST body
   - For password grant: saves trusted user after token issuance
   - Token TTLs: access=1hr, refresh=3mo, auth_code=5min

5. **For the AI agent's OAuth2 client (bd-2us), the recommended approach:**
   - Register as a **confidential client** (`application_type: 'private'`) to get a client_secret
   - Use **password grant** (already enabled with setting `3`) for simplicity -- send username/password/client_id/client_secret to get tokens
   - Alternative: client_credentials grant with JWK for system-level access (more complex but no user password needed)
   - Token endpoint: `POST /oauth2/default/token`
   - Registration endpoint: `POST /oauth2/default/registration`
   - The `OPENEMR_SETTING_site_addr_oath` is set to `https://localhost:9300`

6. **Scopes:** The agent will likely need `user/` or `system/` prefixed scopes for appointment access (e.g., `user/Appointment.read` for FHIR, or custom API scopes).

---

## Summary & Recommendations

1. **Environment is ready** -- uv 0.9.17 + Python 3.13.6 are available and modern.
2. **Clean slate** -- No existing Python files; `ai-agent/` will be the first Python code in the repo.
3. **Docker integration** is straightforward -- the existing compose already enables OAuth password grant and REST APIs. The ai-agent service (bd-coc) just needs to join the network.
4. **All PyPI packages are current** and compatible. Use `uv add` per CLAUDE.md rules (never edit pyproject.toml directly).
5. **OAuth2 flow for the agent client:** Password grant is the simplest path. Client registration -> get client_id/secret -> POST to token endpoint with credentials. This is already enabled in the dev docker setup.
6. **Consider `pydantic-settings`** over raw `python-dotenv` for config.py since pydantic is already a dependency.
7. **Gitignore:** Will need Python-specific entries (`__pycache__/`, `.venv/`, `*.pyc`) -- could add to root `.gitignore` or create `ai-agent/.gitignore`.
