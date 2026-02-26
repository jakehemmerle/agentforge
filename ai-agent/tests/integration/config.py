"""Single source of truth for integration test configuration.

All connection parameters, seed data IDs, and OAuth scopes live here.
Both pytest integration tests and the eval harness import from this module
instead of defining their own constants.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

COMPOSE_DIR = Path(__file__).resolve().parents[3] / "openemr" / "docker" / "development-easy"
COMPOSE_TEST_FILE = COMPOSE_DIR / "docker-compose.test.yml"
AI_AGENT_DIR = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Database connection (host-accessible ports from docker-compose)
# Keep defaults in sync with scripts/seed_data.py DB_CONFIG
# ---------------------------------------------------------------------------

DB_HOST = "127.0.0.1"
DB_PORT = 8320
DB_NAME = "openemr"
DB_USER = "openemr"
DB_PASSWORD = "openemr"

# ---------------------------------------------------------------------------
# OpenEMR API
# ---------------------------------------------------------------------------

OPENEMR_BASE_URL = "http://localhost:8300"
OPENEMR_ADMIN_USER = "admin"
OPENEMR_ADMIN_PASS = "pass"

# ---------------------------------------------------------------------------
# OAuth scopes required for the AI agent
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Seed data IDs (must match scripts/seed_data.py)
# ---------------------------------------------------------------------------

PATIENT_ID_COMPLETE = 90001  # Has ICD + CPT billing rows + insurance
PATIENT_ID_INCOMPLETE = 90002  # Has CPT only (no ICD) + no insurance
PATIENT_ID_JOHNSON = 90003
PATIENT_ID_GARCIA = 90004
PATIENT_ID_WILSON = 90005
ENCOUNTER_COMPLETE = 900001
ENCOUNTER_INCOMPLETE = 900002

ALL_SEED_PIDS = [
    PATIENT_ID_COMPLETE,
    PATIENT_ID_INCOMPLETE,
    PATIENT_ID_JOHNSON,
    PATIENT_ID_GARCIA,
    PATIENT_ID_WILSON,
]
ALL_SEED_ENCOUNTER_IDS = [ENCOUNTER_COMPLETE, ENCOUNTER_INCOMPLETE]

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------

HEALTH_TIMEOUT = 300  # seconds — fresh init includes schema creation
