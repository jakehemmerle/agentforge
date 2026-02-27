#!/usr/bin/env python3
"""Register (or verify) an OAuth2 client for the AI agent dev environment.

Usage:
    python setup_oauth.py            # Idempotent: skip if credentials work
    python setup_oauth.py --force    # Always re-register a fresh client

Reads/writes OPENEMR_CLIENT_ID and OPENEMR_CLIENT_SECRET in both:
  - <project-root>/.env        (used by Docker Compose)
  - <project-root>/ai-agent/.env  (used by local dev / get_settings())
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
import pymysql
from dotenv import set_key

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENEMR_BASE_URL = os.getenv("OPENEMR_BASE_URL", "http://localhost:8300")
CLIENT_NAME = "openemr-ai-agent-dev"

# Keep in sync with ai_agent.openemr_client.OAUTH_SCOPES
OAUTH_SCOPES = (
    "openid api:oemr "
    "user/appointment.read "
    "user/encounter.read "
    "user/patient.read "
    "user/insurance.read "
    "user/vital.read "
    "user/soap_note.read "
    "user/AllergyIntolerance.read "
    "user/Condition.read "
    "user/MedicationRequest.read"
)

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "8320")),
    "user": os.getenv("MYSQL_USER", "openemr"),
    "password": os.getenv("MYSQL_PASS", "openemr"),
    "database": os.getenv("MYSQL_DATABASE", "openemr"),
}

SCRIPT_DIR = Path(__file__).resolve().parent
AI_AGENT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = AI_AGENT_DIR.parent
ROOT_ENV = PROJECT_ROOT / ".env"
AGENT_ENV = AI_AGENT_DIR / ".env"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_token(client_id: str, client_secret: str) -> bool:
    """Return True if we can obtain a valid OAuth token with these credentials."""
    try:
        with httpx.Client(base_url=OPENEMR_BASE_URL, timeout=10) as http:
            resp = http.post(
                "/oauth2/default/token",
                data={
                    "grant_type": "password",
                    "username": "admin",
                    "password": "pass",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": OAUTH_SCOPES,
                    "user_role": "users",
                },
            )
            return resp.status_code == 200 and "access_token" in resp.json()
    except (httpx.HTTPError, Exception):
        return False


def _register() -> tuple[str, str]:
    """Register a new OAuth client and enable it. Returns (client_id, secret)."""
    print("Registering OAuth2 client...")
    with httpx.Client(base_url=OPENEMR_BASE_URL, timeout=30) as http:
        resp = http.post(
            "/oauth2/default/registration",
            json={
                "application_type": "private",
                "client_name": CLIENT_NAME,
                "redirect_uris": ["https://localhost"],
                "scope": OAUTH_SCOPES,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    client_id: str = data["client_id"]
    client_secret: str = data.get("client_secret", "")
    print(f"  Registered: {client_id[:20]}...")

    # Enable the client (new registrations default to disabled)
    print("  Enabling client in database...")
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE oauth_clients SET is_enabled=1 WHERE client_name=%s",
                (CLIENT_NAME,),
            )
        conn.commit()
    finally:
        conn.close()

    return client_id, client_secret


def _update_env_files(client_id: str, client_secret: str) -> None:
    """Write credentials to both .env files using python-dotenv."""
    for env_path in (ROOT_ENV, AGENT_ENV):
        if not env_path.exists():
            env_path.touch()
        # quote_mode="never" — Docker Compose --env-file doesn't strip quotes
        set_key(str(env_path), "OPENEMR_CLIENT_ID", client_id, quote_mode="never")
        set_key(
            str(env_path), "OPENEMR_CLIENT_SECRET", client_secret, quote_mode="never"
        )
        print(f"  Updated {env_path.relative_to(PROJECT_ROOT)}")


def _read_existing() -> tuple[str, str]:
    """Read current credentials from the root .env (if any)."""
    client_id = ""
    client_secret = ""
    if ROOT_ENV.exists():
        for line in ROOT_ENV.read_text().splitlines():
            if line.startswith("OPENEMR_CLIENT_ID="):
                client_id = line.split("=", 1)[1].strip()
            elif line.startswith("OPENEMR_CLIENT_SECRET="):
                client_secret = line.split("=", 1)[1].strip()
    return client_id, client_secret


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register or verify OAuth2 client for dev environment",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-register even if existing credentials work",
    )
    args = parser.parse_args()

    # 1. Check existing credentials (unless --force)
    if not args.force:
        client_id, client_secret = _read_existing()
        if client_id and client_secret:
            print(f"Found existing credentials ({client_id[:20]}...)")
            if _try_token(client_id, client_secret):
                print("OAuth client already configured and working.")
                return
            print("  Existing credentials failed — re-registering.")

    # 2. Register new client
    client_id, client_secret = _register()

    # 3. Update .env files
    _update_env_files(client_id, client_secret)

    # 4. Validate
    if not _try_token(client_id, client_secret):
        print("ERROR: Token validation failed after registration.", file=sys.stderr)
        sys.exit(1)

    print("OAuth client configured and validated.")


if __name__ == "__main__":
    main()
