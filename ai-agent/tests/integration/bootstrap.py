"""Reusable infrastructure helpers for integration tests.

Extracted from ``evals/run_evals.py`` so that both the eval harness and
pytest integration tests can share the same Docker lifecycle, OAuth
registration, seed-data, and environment-configuration logic without
duplication.

All configuration constants (URLs, ports, credentials, timeouts) are
imported from :mod:`tests.integration.config`.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from urllib.parse import urlparse

import httpx
import pymysql
import pymysql.cursors

from tests.integration.config import (
    AI_AGENT_DIR,
    COMPOSE_TEST_FILE,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    HEALTH_TIMEOUT,
    OAUTH_SCOPES,
    OPENEMR_ADMIN_PASS,
    OPENEMR_ADMIN_USER,
    OPENEMR_BASE_URL,
)


# ---------------------------------------------------------------------------
# Port conflict detection
# ---------------------------------------------------------------------------

# Ports required by docker-compose.test.yml
_REQUIRED_PORTS: dict[int, str] = {
    int(urlparse(OPENEMR_BASE_URL).port or 8300): "OpenEMR HTTP",
    DB_PORT: "MySQL",
}


def _is_port_in_use(port: int) -> bool:
    """Return ``True`` if *port* is accepting connections on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_port_conflicts() -> None:
    """Fail fast if required ports are occupied by any process.

    Integration tests always spin up their own containers from
    ``docker-compose.test.yml``.  If any process (including development
    Docker containers) is already bound to a required port, we cannot
    proceed — the test compose would fail to bind.

    Raises :class:`RuntimeError` with an actionable message listing
    every conflicting port.
    """
    conflicts: list[str] = []
    for port, label in _REQUIRED_PORTS.items():
        if _is_port_in_use(port):
            conflicts.append(
                f"  - Port {port} ({label}) is already in use."
            )
    if conflicts:
        raise RuntimeError(
            "Port conflict detected — cannot start integration test services:\n"
            + "\n".join(conflicts)
            + "\n\nIntegration tests require exclusive use of these ports.\n"
            "Stop any services occupying them (e.g. development Docker "
            "containers) before running integration tests:\n"
            "  docker compose -f openemr/docker/development-easy/docker-compose.yml down"
        )


# ---------------------------------------------------------------------------
# Docker lifecycle
# ---------------------------------------------------------------------------


def _ensure_overlay_applied() -> None:
    """Check that the OpenEMR overlay has been applied.

    Raises :class:`RuntimeError` with an actionable message if
    ``docker-compose.test.yml`` is missing from the compose directory,
    indicating the overlay has not been applied.
    """
    if COMPOSE_TEST_FILE.exists():
        return

    raise RuntimeError(
        f"Compose test file not found: {COMPOSE_TEST_FILE}\n\n"
        "The OpenEMR overlay has not been applied. "
        "Integration tests require the overlay (patches + widget files) "
        "to be applied before running.\n\n"
        "Apply the overlay first:\n"
        "  ./injectables/openemr-customize.sh apply\n\n"
        "Then re-run integration tests:\n"
        "  INTEGRATION_TEST=1 uv run pytest tests/ -m integration"
    )


def start_services() -> None:
    """Tear down any previous test containers, then start fresh ones.

    Always runs ``docker compose down --remove-orphans`` first to ensure
    a completely clean slate.  Integration tests must never reuse
    existing containers.
    """
    _ensure_overlay_applied()

    compose_base_file = COMPOSE_TEST_FILE.parent / "docker-compose.yml"
    compose_cmd = [
        "docker", "compose",
        "-f", str(compose_base_file),
        "-f", str(COMPOSE_TEST_FILE),
    ]

    print("Tearing down any previous test containers...")
    result = subprocess.run(
        [*compose_cmd, "down", "--remove-orphans", "-v"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or "no previous test containers were running"
        print(f"  Note: {msg}")
    else:
        print("  Done — old test containers removed.")

    # Check conflicts only after teardown so stale prior test containers
    # don't block a clean rerun.
    check_port_conflicts()

    print("Starting Docker services (ephemeral — no persistent volumes)...")
    subprocess.run(
        [*compose_cmd, "up", "mysql", "openemr", "-d", "--wait"],
        check=True,
        timeout=600,
    )
    print("  Docker services started.")


def wait_for_health(timeout: int = HEALTH_TIMEOUT) -> None:
    """Poll until OpenEMR responds with HTTP < 400.

    Checks every 3 seconds. Raises :class:`RuntimeError` if *timeout*
    seconds elapse without a healthy response.
    """
    print(
        f"Waiting for OpenEMR at {OPENEMR_BASE_URL} (timeout {timeout}s)..."
    )
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(
                f"{OPENEMR_BASE_URL}/",
                timeout=5,
                follow_redirects=True,
            )
            if resp.status_code < 400:
                print(f"  OpenEMR is healthy (HTTP {resp.status_code}).")
                return
            last_error = f"HTTP {resp.status_code}"
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
        ) as exc:
            last_error = type(exc).__name__
        time.sleep(3)
    raise RuntimeError(
        f"OpenEMR failed to become healthy within {timeout}s. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# OAuth registration (synchronous — safe for session-scoped fixtures)
# ---------------------------------------------------------------------------


def register_oauth_client(
    client_name: str = "openemr-ai-agent-test",
) -> tuple[str, str]:
    """Register an OAuth2 client with OpenEMR and enable it in the DB.

    Uses :class:`httpx.Client` (synchronous) so this function can be
    called from session-scoped pytest fixtures without triggering
    event-loop conflicts.

    Returns
    -------
    tuple[str, str]
        ``(client_id, client_secret)``
    """
    print("Registering OAuth2 client...")
    with httpx.Client(base_url=OPENEMR_BASE_URL, timeout=30) as http:
        resp = http.post(
            "/oauth2/default/registration",
            json={
                "application_type": "private",
                "client_name": client_name,
                "redirect_uris": ["https://localhost"],
                "scope": OAUTH_SCOPES,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        client_id: str = data["client_id"]
        client_secret: str = data.get("client_secret", "")

    # Enable the client in the database (new registrations default to
    # disabled).
    print("  Enabling OAuth2 client in database...")
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE oauth_clients SET is_enabled=1 "
                "WHERE client_name=%s",
                (client_name,),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"  Client registered and enabled: {client_id[:20]}...")
    return client_id, client_secret


def validate_oauth_token(client_id: str, client_secret: str) -> str:
    """Obtain an OAuth token and validate it grants access to key endpoints.

    Returns the access token on success.  Raises :class:`RuntimeError` with
    an actionable message if the token cannot be obtained or if key
    endpoints return 401 (indicating missing scopes).
    """
    print("Validating OAuth token and API endpoint access...")

    # 1. Obtain token
    with httpx.Client(base_url=OPENEMR_BASE_URL, timeout=30) as http:
        resp = http.post(
            "/oauth2/default/token",
            data={
                "grant_type": "password",
                "username": OPENEMR_ADMIN_USER,
                "password": OPENEMR_ADMIN_PASS,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": OAUTH_SCOPES,
                "user_role": "users",
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to obtain OAuth token (HTTP {resp.status_code}): "
                f"{resp.text}\n\n"
                "The OAuth client may need to be re-registered. "
                "Try: INTEGRATION_TEST=1 uv run pytest tests/ -m integration "
                "(without INTEGRATION_TEST_CLIENT_ID set)."
            )
        token = resp.json()["access_token"]

    # 2. Probe key endpoints for scope coverage
    probe_paths = [
        ("/apis/default/api/patient", "user/patient.read"),
        ("/apis/default/api/patient/1/encounter", "user/encounter.read"),
    ]
    headers = {"Authorization": f"Bearer {token}"}
    missing_scopes: list[str] = []

    with httpx.Client(base_url=OPENEMR_BASE_URL, timeout=15) as http:
        for path, scope in probe_paths:
            r = http.get(path, headers=headers)
            if r.status_code == 401:
                missing_scopes.append(scope)

    if missing_scopes:
        raise RuntimeError(
            "OAuth token is missing required scopes. "
            f"Endpoints returned 401 for: {', '.join(missing_scopes)}\n"
            "Re-register the OAuth client with the correct scopes.\n"
            f"Required scopes: {OAUTH_SCOPES}"
        )

    print("  OAuth token valid — key endpoints accessible.")
    return token


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def run_seed(*, clean: bool = False) -> None:
    """Run ``scripts/seed_data.py`` via ``uv``.

    Parameters
    ----------
    clean:
        If ``True``, pass ``--clean`` to remove existing seed rows first.
    """
    cmd = ["uv", "run", "python", "scripts/seed_data.py"]
    if clean:
        cmd.append("--clean")
    label = "Seeding data (clean)..." if clean else "Seeding data..."
    print(label)
    subprocess.run(cmd, cwd=AI_AGENT_DIR, check=True)
    print("  Seed data complete.")


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------


def configure_environment(client_id: str, client_secret: str) -> None:
    """Set environment variables so the agent talks to local Docker services.

    Also clears the cached :func:`ai_agent.config.get_settings` so that
    any subsequent import picks up the new values.
    """
    print("Configuring environment variables...")
    os.environ["OPENEMR_BASE_URL"] = OPENEMR_BASE_URL
    os.environ["OPENEMR_CLIENT_ID"] = client_id
    os.environ["OPENEMR_CLIENT_SECRET"] = client_secret
    os.environ["DB_HOST"] = DB_HOST
    os.environ["DB_PORT"] = str(DB_PORT)
    os.environ["DB_NAME"] = DB_NAME
    os.environ["DB_USER"] = DB_USER
    os.environ["DB_PASSWORD"] = DB_PASSWORD

    # Clear cached settings so the agent picks up the new values
    from ai_agent.config import get_settings

    get_settings.cache_clear()
    print("  Environment configured.")


# ---------------------------------------------------------------------------
# Database connection helper
# ---------------------------------------------------------------------------


def get_db_connection() -> pymysql.Connection:
    """Create and return a new pymysql connection using config constants.

    The connection uses :class:`pymysql.cursors.DictCursor` so that rows
    are returned as dictionaries.
    """
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )
