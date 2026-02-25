"""Shared test fixtures."""

from __future__ import annotations

import os
from typing import Any, Callable
from unittest.mock import AsyncMock

import pytest

from tests.helpers import (
    mock_appointment_client as _mock_appointment_client,
    mock_claim_client as _mock_claim_client,
    mock_fhir_error_client as _mock_fhir_error_client,
    mock_fhir_timeout_client as _mock_fhir_timeout_client,
)

_INTEGRATION = bool(os.environ.get("INTEGRATION_TEST"))


@pytest.fixture
def mock_appointment_client():
    """Factory fixture returning a mock OpenEMRClient for appointment tests."""
    return _mock_appointment_client


@pytest.fixture
def mock_claim_client():
    """Factory fixture returning a mock OpenEMRClient for claim validation tests."""
    return _mock_claim_client


@pytest.fixture
def mock_fhir_error_client():
    """Factory fixture returning a mock client where specific FHIR paths raise HTTPStatusError."""
    return _mock_fhir_error_client


@pytest.fixture
def mock_fhir_timeout_client():
    """Factory fixture returning a mock client where specific FHIR paths raise TimeoutException."""
    return _mock_fhir_timeout_client


# ---------------------------------------------------------------------------
# Integration test fixtures (active only when INTEGRATION_TEST=1)
# ---------------------------------------------------------------------------

if _INTEGRATION:
    from tests.integration.bootstrap import (
        configure_environment,
        get_db_connection,
        register_oauth_client,
        run_seed,
        start_services,
        validate_oauth_token,
        wait_for_health,
    )
    from tests.integration.config import (
        ALL_SEED_ENCOUNTER_IDS,
        ALL_SEED_PIDS,
        OPENEMR_BASE_URL,
    )
    from tests.integration.factories import insert_billing_row, insert_insurance

    @pytest.fixture(scope="session")
    def integration_env():
        """Bootstrap the full integration environment.

        Always spins up fresh test containers from docker-compose.test.yml.
        Never reuses existing containers.  Registers an OAuth client, seeds
        the database, and configures the process environment for the agent.

        Yields ``(client_id, client_secret)``.

        Skipped entirely when ``INTEGRATION_TEST`` is not set.
        """
        # Always start fresh containers — never reuse existing ones
        start_services()
        wait_for_health()

        client_id, client_secret = register_oauth_client()
        run_seed()

        configure_environment(client_id, client_secret)

        # Post-setup: verify OAuth token grants access to key endpoints
        try:
            validate_oauth_token(client_id, client_secret)
        except RuntimeError as exc:
            pytest.fail(str(exc))

        yield client_id, client_secret

    @pytest.fixture(scope="session", autouse=True)
    def _validate_seed_data(integration_env):
        """Verify expected seed patients and encounters exist in the database.

        Runs once per session after ``integration_env`` finishes setup.
        Calls ``pytest.fail()`` with an actionable message if seed data
        is missing.  No-ops for unit tests (guard is the ``if _INTEGRATION``
        block surrounding this fixture definition).
        """
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # Check patients
                cur.execute(
                    "SELECT pid FROM patient_data WHERE pid IN %s",
                    (tuple(ALL_SEED_PIDS),),
                )
                found_pids = {row["pid"] for row in cur.fetchall()}
                missing_pids = set(ALL_SEED_PIDS) - found_pids
                if missing_pids:
                    pytest.fail(
                        f"Seed patients missing: {missing_pids}. "
                        "Run: uv run python scripts/seed_data.py"
                    )

                # Check encounters
                cur.execute(
                    "SELECT encounter FROM form_encounter WHERE encounter IN %s",
                    (tuple(ALL_SEED_ENCOUNTER_IDS),),
                )
                found_encs = {row["encounter"] for row in cur.fetchall()}
                missing_encs = set(ALL_SEED_ENCOUNTER_IDS) - found_encs
                if missing_encs:
                    pytest.fail(
                        f"Seed encounters missing: {missing_encs}. "
                        "Run: uv run python scripts/seed_data.py"
                    )
        finally:
            conn.close()

    @pytest.fixture(scope="module")
    def db_conn(integration_env):
        """Module-scoped raw MySQL connection for direct queries."""
        conn = get_db_connection()
        yield conn
        conn.close()

    @pytest.fixture
    def api_client(integration_env):
        """Function-scoped OpenEMRClient configured for the Docker environment."""
        from ai_agent.config import get_settings
        from ai_agent.openemr_client import OpenEMRClient

        s = get_settings()
        return OpenEMRClient(
            base_url=s.openemr_base_url,
            client_id=s.openemr_client_id,
            client_secret=s.openemr_client_secret,
            username=s.openemr_username,
            password=s.openemr_password,
        )

    @pytest.fixture
    def db_cleanup():
        """Collect cleanup callables and run them in LIFO order during teardown."""
        cleanups: list[Callable[[], None]] = []

        def _register(fn: Callable[[], None]) -> None:
            cleanups.append(fn)

        yield _register

        errors = []
        for fn in reversed(cleanups):
            try:
                fn()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    @pytest.fixture
    def billing_factory(db_conn, db_cleanup):
        """Insert a billing row and auto-register cleanup.

        Usage::

            row_id = billing_factory(encounter_id=1, patient_id=2)
        """

        def _create(encounter_id: int, patient_id: int, **kwargs: Any) -> int:
            row_id, cleanup = insert_billing_row(
                db_conn, encounter_id, patient_id, **kwargs
            )
            db_cleanup(cleanup)
            return row_id

        return _create

    @pytest.fixture
    def insurance_factory(db_conn, db_cleanup):
        """Insert an insurance row and auto-register cleanup.

        Usage::

            row_id = insurance_factory(patient_id=2)
        """

        def _create(patient_id: int, **kwargs: Any) -> int:
            row_id, cleanup = insert_insurance(db_conn, patient_id, **kwargs)
            db_cleanup(cleanup)
            return row_id

        return _create
