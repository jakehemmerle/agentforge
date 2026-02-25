"""Schema validation tests for tool output shapes.

These tests verify that tool outputs conform to expected schemas by running
the tools with mock data and asserting on the returned dict structures.
No external dependencies beyond the test helpers are required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from ai_agent.tools.find_appointments import _find_appointments_impl, _format_appointment
from ai_agent.tools.get_encounter_context import _get_encounter_context_impl
from ai_agent.tools.draft_encounter_note import _draft_encounter_note_impl
from ai_agent.tools.validate_claim_completeness import _validate_claim_impl
from tests.helpers import make_encounter, make_patient, mock_encounter_client, mock_appointment_client, mock_claim_client

pytestmark = pytest.mark.unit

# -- expected schemas (key → type) --------------------------------------------

FIND_APPOINTMENTS_SCHEMA: dict[str, type] = {
    "appointments": list,
    "total_count": int,
}

FIND_APPOINTMENTS_ITEM_SCHEMA: dict[str, type] = {
    "appointment_id": int,
    "patient_name": str,
    "patient_id": int,
    "provider_name": str,
    "date": str,
    "start_time": str,
    "end_time": str,
    "status": str,
    "status_label": str,
    "category": str,
    "facility": str,
    "reason": str,
}

GET_ENCOUNTER_CONTEXT_SCHEMA: dict[str, type] = {
    "encounter": dict,
    "patient": dict,
    "clinical_context": dict,
    "billing_status": dict,
    "data_warnings": list,
}

GET_ENCOUNTER_CONTEXT_ENCOUNTER_SCHEMA: dict[str, type] = {
    "id": (int, str),
    "date": str,
    "reason": str,
    "provider": dict,
    "facility": dict,
    "class_code": str,
    "status": str,
}

GET_ENCOUNTER_CONTEXT_PATIENT_SCHEMA: dict[str, type] = {
    "id": (int, str),
    "name": str,
    "dob": str,
    "sex": str,
    "mrn": str,
}

DRAFT_NOTE_SCHEMA: dict[str, type] = {
    "draft_note": dict,
    "warnings": list,
    "data_warnings": list,
    "disclaimer": str,
}

DRAFT_NOTE_INNER_SCHEMA: dict[str, type] = {
    "type": str,
    "encounter_id": int,
    "patient_name": str,
    "content": dict,
    "full_text": str,
    "generated_at": str,
}

VALIDATE_CLAIM_SCHEMA: dict[str, type] = {
    "encounter_id": int,
    "ready": bool,
    "errors": list,
    "warnings": list,
    "summary": dict,
    "data_warnings": list,
}

VALIDATE_CLAIM_SUMMARY_SCHEMA: dict[str, type] = {
    "dx_codes": list,
    "cpt_codes": list,
    "provider": str,
    "facility": str,
    "total_charges": float,
}


# -- helpers ------------------------------------------------------------------


def _assert_schema(result: dict[str, Any], schema: dict[str, Any]) -> None:
    """Assert all expected keys exist with correct types."""
    for key, expected_type in schema.items():
        assert key in result, f"Missing key: {key}"
        if isinstance(expected_type, tuple):
            assert isinstance(result[key], expected_type), (
                f"Key '{key}': expected {expected_type}, got {type(result[key])}"
            )
        else:
            assert isinstance(result[key], expected_type), (
                f"Key '{key}': expected {expected_type.__name__}, got {type(result[key]).__name__}"
            )


def _assert_keys(result: dict[str, Any], expected_keys: set[str]) -> None:
    """Assert result contains at least the expected keys."""
    assert expected_keys.issubset(set(result.keys())), (
        f"Missing keys: {expected_keys - set(result.keys())}"
    )


# -- helpers for building mock data -------------------------------------------


def _make_appointment(**overrides: Any) -> dict[str, Any]:
    base = {
        "pc_eid": 1,
        "fname": "John",
        "lname": "Doe",
        "pc_pid": 10,
        "pid": 10,
        "pce_aid_fname": "Dr",
        "pce_aid_lname": "Smith",
        "pc_eventDate": "2026-03-01",
        "pc_startTime": "09:00:00",
        "pc_endTime": "09:30:00",
        "pc_apptstatus": "@",
        "pc_title": "Office Visit",
        "facility_name": "Main Clinic",
        "pc_hometext": "Follow-up",
    }
    base.update(overrides)
    return base


# -- find_appointments schema tests -------------------------------------------


async def test_find_appointments_output_schema():
    """find_appointments output has correct top-level keys and types."""
    appts = [_make_appointment()]
    client = mock_appointment_client(appointments=appts)
    result = await _find_appointments_impl(client)
    _assert_schema(result, FIND_APPOINTMENTS_SCHEMA)
    assert len(result["appointments"]) == 1
    _assert_schema(result["appointments"][0], FIND_APPOINTMENTS_ITEM_SCHEMA)


async def test_find_appointments_empty_output_schema():
    """Empty results still have correct schema."""
    client = mock_appointment_client(appointments=[])
    result = await _find_appointments_impl(client, date="2099-01-01")
    _assert_schema(result, FIND_APPOINTMENTS_SCHEMA)
    assert result["total_count"] == 0
    assert result["appointments"] == []


# -- get_encounter_context schema tests ---------------------------------------


async def test_get_encounter_context_output_schema():
    """get_encounter_context output has correct top-level and nested keys."""
    patient = make_patient()
    encounter = make_encounter()
    vitals = [{
        "temperature": "98.6", "bps": "120", "bpd": "80", "pulse": "72",
        "respiration": "16", "oxygen_saturation": "98", "weight": "180", "height": "70",
    }]
    conditions_bundle = {
        "entry": [{"resource": {"code": {"coding": [{"code": "E11.9", "display": "Type 2 diabetes"}]}, "onsetDateTime": "2020-06-15"}}]
    }
    medications_bundle = {
        "entry": [{"resource": {"medicationCodeableConcept": {"coding": [{"display": "Metformin"}]},
                   "dosageInstruction": [{"doseAndRate": [{"doseQuantity": {"value": 500, "unit": "mg"}}],
                                          "timing": {"code": {"text": "twice daily"}}}]}}]
    }
    allergies_bundle = {
        "entry": [{"resource": {"code": {"coding": [{"display": "Penicillin"}]},
                   "reaction": [{"manifestation": [{"coding": [{"display": "Rash"}]}], "severity": "moderate"}]}}]
    }

    client = mock_encounter_client(
        patients=[patient], encounters=[encounter], vitals=vitals,
        conditions_bundle=conditions_bundle, medications_bundle=medications_bundle,
        allergies_bundle=allergies_bundle,
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    _assert_schema(result, GET_ENCOUNTER_CONTEXT_SCHEMA)
    _assert_schema(result["encounter"], GET_ENCOUNTER_CONTEXT_ENCOUNTER_SCHEMA)
    _assert_schema(result["patient"], GET_ENCOUNTER_CONTEXT_PATIENT_SCHEMA)
    _assert_keys(result["clinical_context"], {"active_problems", "medications", "allergies", "vitals", "existing_notes"})
    _assert_keys(result["billing_status"], {"has_dx_codes", "dx_codes", "billing_note", "last_level_billed"})


# -- draft_encounter_note schema tests ----------------------------------------


async def test_draft_encounter_note_output_schema():
    """draft_encounter_note output has correct structure."""
    import json
    from langchain_core.messages import AIMessage

    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=json.dumps(llm_response)))

    result = await _draft_encounter_note_impl(client, llm, encounter_id=5, patient_id=10, note_type="SOAP")
    _assert_schema(result, DRAFT_NOTE_SCHEMA)
    _assert_schema(result["draft_note"], DRAFT_NOTE_INNER_SCHEMA)


# -- validate_claim schema tests ----------------------------------------------


async def test_validate_claim_output_schema():
    """validate_claim output has correct structure."""
    patient = make_patient()
    encounter = make_encounter()
    billing_rows = [
        {"code_type": "ICD10", "code": "J06.9", "code_text": "URI", "fee": 0, "modifier": "", "units": 1},
        {"code_type": "CPT4", "code": "99213", "code_text": "Office visit", "fee": 75.0, "modifier": "", "units": 1},
    ]
    insurance = [{"type": "primary", "provider": "1", "policy_number": "POL1"}]

    client = mock_claim_client(patients=[patient], encounters=[encounter])
    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )
    _assert_schema(result, VALIDATE_CLAIM_SCHEMA)
    _assert_schema(result["summary"], VALIDATE_CLAIM_SUMMARY_SCHEMA)


async def test_validate_claim_error_item_schema():
    """Error and warning items have {check, message, severity}."""
    patient = make_patient(fname="", street="")
    encounter = make_encounter(provider_id=0, billing_facility=0)
    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=[], insurance_list=[],
    )

    assert len(result["errors"]) > 0
    assert len(result["warnings"]) > 0

    for item in result["errors"]:
        _assert_keys(item, {"check", "message", "severity"})
        assert isinstance(item["check"], str)
        assert isinstance(item["message"], str)
        assert item["severity"] == "error"

    for item in result["warnings"]:
        _assert_keys(item, {"check", "message", "severity"})
        assert isinstance(item["check"], str)
        assert isinstance(item["message"], str)
        assert item["severity"] == "warning"
