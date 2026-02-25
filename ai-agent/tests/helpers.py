"""Shared test fixtures and helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx


# -- reusable data builders ----------------------------------------------------


def make_patient(**overrides: Any) -> dict[str, Any]:
    """Build a patient dict with sensible defaults (superset of all tool needs)."""
    base = {
        "pid": 10,
        "uuid": "patient-uuid-1234",
        "fname": "John",
        "lname": "Doe",
        "DOB": "1980-01-15",
        "sex": "Male",
        "pubpid": "MRN001",
        "street": "123 Main St",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62701",
    }
    base.update(overrides)
    return base


def make_encounter(**overrides: Any) -> dict[str, Any]:
    """Build an encounter dict with sensible defaults (superset of all tool needs)."""
    base = {
        "id": 5,
        "uuid": "enc-uuid-5678",
        "date": "2026-03-01 09:00:00",
        "reason": "Annual checkup",
        "pid": 10,
        "provider_id": 1,
        "facility": "Main Clinic",
        "facility_id": 3,
        "billing_facility": 3,
        "billing_facility_name": "Main Clinic",
        "class_code": "AMB",
        "pc_catname": "Office Visit",
        "billing_note": "",
        "last_level_billed": "0",
        "last_level_closed": "0",
    }
    base.update(overrides)
    return base


def mock_encounter_client(
    patients: list | None = None,
    encounters: list | None = None,
    vitals: list | None = None,
    soap_notes: list | None = None,
    conditions_bundle: dict | None = None,
    medications_bundle: dict | None = None,
    allergies_bundle: dict | None = None,
) -> AsyncMock:
    """Build a mock OpenEMRClient for encounter-context and draft-note tests."""
    client = AsyncMock()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        if "/fhir/Condition" in path:
            return conditions_bundle or {"entry": []}
        if "/fhir/MedicationRequest" in path:
            return medications_bundle or {"entry": []}
        if "/fhir/AllergyIntolerance" in path:
            return allergies_bundle or {"entry": []}
        if "/encounter/" in path and "/vital" in path:
            return {"data": vitals or []}
        if "/encounter/" in path and "/soap_note" in path:
            return {"data": soap_notes or []}
        if "/encounter" in path:
            return {"data": encounters or []}
        if "/patient" in path:
            return {"data": patients or []}
        return {"data": []}

    client.get = AsyncMock(side_effect=mock_get)
    return client


def mock_appointment_client(
    patients: list | None = None,
    appointments: list | None = None,
    patient_appointments: dict[int, list] | None = None,
) -> AsyncMock:
    """Build a mock OpenEMRClient for appointment tests."""
    client = AsyncMock()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        if "/patient" in path and "/appointment" in path:
            pid = int(path.split("/patient/")[1].split("/")[0])
            data = (patient_appointments or {}).get(pid, [])
            return {"data": data}
        if "/patient" in path:
            return {"data": patients or []}
        if "/appointment" in path:
            return {"data": appointments or []}
        return {"data": []}

    client.get = AsyncMock(side_effect=mock_get)
    return client


def mock_claim_client(
    patients: list | None = None,
    encounters: list | None = None,
) -> AsyncMock:
    """Build a mock OpenEMRClient for claim validation tests."""
    client = AsyncMock()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        if "/encounter" in path:
            return {"data": encounters or []}
        if "/patient" in path:
            return {"data": patients or []}
        return {"data": []}

    client.get = AsyncMock(side_effect=mock_get)
    return client


def mock_fhir_error_client(
    patients: list | None = None,
    encounters: list | None = None,
    failing_paths: set[str] | None = None,
) -> AsyncMock:
    """Build a mock client where specific FHIR paths raise HTTPStatusError."""
    client = AsyncMock()
    failing = failing_paths or set()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        for pattern in failing:
            if pattern in path:
                resp = httpx.Response(500, request=httpx.Request("GET", path))
                raise httpx.HTTPStatusError(
                    "Server Error", request=resp.request, response=resp
                )
        if "/encounter/" in path and "/vital" in path:
            return {"data": []}
        if "/encounter/" in path and "/soap_note" in path:
            return {"data": []}
        if "/encounter" in path:
            return {"data": encounters or []}
        if "/patient" in path:
            return {"data": patients or []}
        return {"entry": []}

    client.get = AsyncMock(side_effect=mock_get)
    return client


def mock_fhir_timeout_client(
    patients: list | None = None,
    encounters: list | None = None,
    failing_paths: set[str] | None = None,
) -> AsyncMock:
    """Build a mock client where specific FHIR paths raise TimeoutException."""
    client = AsyncMock()
    failing = failing_paths or set()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        for pattern in failing:
            if pattern in path:
                raise httpx.TimeoutException(
                    f"Timed out requesting {path}",
                    request=httpx.Request("GET", path),
                )
        if "/encounter/" in path and "/vital" in path:
            return {"data": []}
        if "/encounter/" in path and "/soap_note" in path:
            return {"data": []}
        if "/encounter" in path:
            return {"data": encounters or []}
        if "/patient" in path:
            return {"data": patients or []}
        return {"entry": []}

    client.get = AsyncMock(side_effect=mock_get)
    return client


def find_patient_uuid(patients: list[dict], pid: int) -> str:
    """Find the UUID for a specific pid in a list of patient records."""
    for p in patients:
        if str(p.get("pid")) == str(pid):
            return p["uuid"]
    raise ValueError(f"Patient {pid} not found in API response")
