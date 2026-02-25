"""Integration test infrastructure for the OpenEMR AI agent.

Provides shared configuration, Docker lifecycle management, and database
factories used by both ``pytest`` integration tests and the eval harness.

Modules
-------
config
    Single source of truth for connection parameters and seed data IDs.
bootstrap
    Docker health checks, OAuth registration, seed runner, environment setup.
factories
    DB-level scenario builders with automatic cleanup.
"""

from tests.integration.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    ENCOUNTER_COMPLETE,
    ENCOUNTER_INCOMPLETE,
    OPENEMR_BASE_URL,
    PATIENT_ID_COMPLETE,
    PATIENT_ID_INCOMPLETE,
)

__all__ = [
    "DB_HOST",
    "DB_NAME",
    "DB_PASSWORD",
    "DB_PORT",
    "DB_USER",
    "ENCOUNTER_COMPLETE",
    "ENCOUNTER_INCOMPLETE",
    "OPENEMR_BASE_URL",
    "PATIENT_ID_COMPLETE",
    "PATIENT_ID_INCOMPLETE",
]
