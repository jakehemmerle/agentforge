"""Tests for the get_encounter_context tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import ToolException

import httpx

from ai_agent.tools.get_encounter_context import (
    GetEncounterContextInput,
    _format_billing_status,
    _format_encounter,
    _format_patient,
    _format_soap_notes,
    _format_vitals,
    _get_encounter_context_impl,
    _parse_allergies,
    _parse_conditions,
    _parse_medications,
)
from tests.helpers import make_encounter, make_patient, mock_encounter_client

pytestmark = pytest.mark.unit


# -- helpers -------------------------------------------------------------------


def _make_vitals(**overrides: Any) -> dict[str, Any]:
    base = {
        "temperature": "98.6",
        "bps": "120",
        "bpd": "80",
        "pulse": "72",
        "respiration": "16",
        "oxygen_saturation": "98",
        "weight": "180",
        "height": "70",
    }
    base.update(overrides)
    return base


def _make_fhir_condition(**overrides: Any) -> dict[str, Any]:
    base = {
        "resource": {
            "resourceType": "Condition",
            "code": {
                "coding": [{"code": "E11.9", "display": "Type 2 diabetes"}],
            },
            "onsetDateTime": "2020-06-15",
        }
    }
    if overrides:
        base["resource"].update(overrides)
    return base


def _make_fhir_medication(**overrides: Any) -> dict[str, Any]:
    base = {
        "resource": {
            "resourceType": "MedicationRequest",
            "medicationCodeableConcept": {
                "coding": [{"display": "Metformin"}],
            },
            "dosageInstruction": [
                {
                    "doseAndRate": [
                        {"doseQuantity": {"value": 500, "unit": "mg"}}
                    ],
                    "timing": {"code": {"text": "twice daily"}},
                }
            ],
        }
    }
    if overrides:
        base["resource"].update(overrides)
    return base


def _make_fhir_allergy(**overrides: Any) -> dict[str, Any]:
    base = {
        "resource": {
            "resourceType": "AllergyIntolerance",
            "code": {
                "coding": [{"display": "Penicillin"}],
            },
            "reaction": [
                {
                    "manifestation": [
                        {"coding": [{"display": "Rash"}]}
                    ],
                    "severity": "moderate",
                }
            ],
        }
    }
    if overrides:
        base["resource"].update(overrides)
    return base


def _make_soap_note(**overrides: Any) -> dict[str, Any]:
    base = {
        "subjective": "Patient reports feeling well.",
        "objective": "Vitals stable.",
        "assessment": "Diabetes controlled.",
        "plan": "Continue current medications.",
        "date": "2026-03-01",
    }
    base.update(overrides)
    return base


# -- FHIR parsers -------------------------------------------------------------


def test_parse_conditions():
    bundle = {"entry": [_make_fhir_condition()]}
    result = _parse_conditions(bundle)
    assert len(result) == 1
    assert result[0]["code"] == "E11.9"
    assert result[0]["description"] == "Type 2 diabetes"
    assert result[0]["onset_date"] == "2020-06-15"


def test_parse_conditions_empty():
    assert _parse_conditions({}) == []
    assert _parse_conditions({"entry": []}) == []


def test_parse_medications():
    bundle = {"entry": [_make_fhir_medication()]}
    result = _parse_medications(bundle)
    assert len(result) == 1
    assert result[0]["drug_name"] == "Metformin"
    assert result[0]["dose"] == "500 mg"
    assert result[0]["frequency"] == "twice daily"


def test_parse_allergies():
    bundle = {"entry": [_make_fhir_allergy()]}
    result = _parse_allergies(bundle)
    assert len(result) == 1
    assert result[0]["substance"] == "Penicillin"
    assert result[0]["reaction"] == "Rash"
    assert result[0]["severity"] == "moderate"


# -- vitals formatter ----------------------------------------------------------


def test_format_vitals():
    vitals_list = [_make_vitals()]
    result = _format_vitals(vitals_list)
    assert result["temp"] == "98.6"
    assert result["bp"] == "120/80"
    assert result["hr"] == "72"
    assert result["spo2"] == "98"


def test_format_vitals_empty():
    assert _format_vitals([]) is None


# -- billing status ------------------------------------------------------------


def test_format_billing_status():
    enc = make_encounter(billing_note="Some note", last_level_billed="25")
    result = _format_billing_status(enc)
    assert result["has_dx_codes"] is False
    assert result["dx_codes"] == []
    assert result["billing_note"] == "Some note"
    assert result["last_level_billed"] == "25"


# -- full implementation -------------------------------------------------------


async def test_get_encounter_by_id():
    patient = make_patient()
    encounter = make_encounter()
    vitals = [_make_vitals()]
    soap = [_make_soap_note()]
    conditions_bundle = {"entry": [_make_fhir_condition()]}
    medications_bundle = {"entry": [_make_fhir_medication()]}
    allergies_bundle = {"entry": [_make_fhir_allergy()]}

    client = mock_encounter_client(
        patients=[patient],
        encounters=[encounter],
        vitals=vitals,
        soap_notes=soap,
        conditions_bundle=conditions_bundle,
        medications_bundle=medications_bundle,
        allergies_bundle=allergies_bundle,
    )

    result = await _get_encounter_context_impl(
        client, patient_id=10, encounter_id=5
    )

    assert result["encounter"]["id"] == 5
    assert result["encounter"]["reason"] == "Annual checkup"
    assert result["patient"]["id"] == 10
    assert result["patient"]["name"] == "John Doe"
    assert len(result["clinical_context"]["active_problems"]) == 1
    assert len(result["clinical_context"]["medications"]) == 1
    assert len(result["clinical_context"]["allergies"]) == 1
    assert result["clinical_context"]["vitals"]["bp"] == "120/80"
    assert len(result["clinical_context"]["existing_notes"]) == 1
    assert result["billing_status"]["has_dx_codes"] is False
    assert result["data_warnings"] == []


async def test_get_encounter_by_date():
    patient = make_patient()
    encounter = make_encounter(date="2026-03-01 09:00:00")
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    result = await _get_encounter_context_impl(
        client, patient_id=10, date="2026-03-01"
    )

    assert result["encounter"]["id"] == 5
    assert result["data_warnings"] == []


async def test_encounter_not_found():
    patient = make_patient()
    client = mock_encounter_client(patients=[patient], encounters=[])

    with pytest.raises(ToolException, match="No encounter found with ID 999"):
        await _get_encounter_context_impl(
            client, patient_id=10, encounter_id=999
        )


async def test_patient_not_found():
    client = mock_encounter_client(patients=[])

    with pytest.raises(ToolException, match="No patient found with ID 99"):
        await _get_encounter_context_impl(
            client, patient_id=99, encounter_id=1
        )


async def test_multiple_encounters_on_date():
    patient = make_patient()
    encounters = [
        make_encounter(id=5, date="2026-03-01 09:00:00", reason="Morning visit"),
        make_encounter(id=6, date="2026-03-01 14:00:00", reason="Follow-up"),
    ]
    client = mock_encounter_client(patients=[patient], encounters=encounters)

    result = await _get_encounter_context_impl(
        client, patient_id=10, date="2026-03-01"
    )

    assert "message" in result
    assert "Multiple encounters" in result["message"]
    assert len(result["encounters"]) == 2


async def test_no_encounters_on_date():
    patient = make_patient()
    client = mock_encounter_client(patients=[patient], encounters=[])

    with pytest.raises(ToolException, match="No encounters found on 2026-04-01"):
        await _get_encounter_context_impl(
            client, patient_id=10, date="2026-04-01"
        )


async def test_partial_clinical_data():
    """Gracefully handles missing vitals/notes/conditions."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    result = await _get_encounter_context_impl(
        client, patient_id=10, encounter_id=5
    )

    assert result["clinical_context"]["vitals"] is None
    assert result["clinical_context"]["existing_notes"] == []
    assert result["clinical_context"]["active_problems"] == []
    assert result["data_warnings"] == []


# -- input schema validation ---------------------------------------------------


def test_input_schema_valid_with_encounter_id():
    inp = GetEncounterContextInput(patient_id=10, encounter_id=5)
    assert inp.patient_id == 10
    assert inp.encounter_id == 5


def test_input_schema_valid_with_date():
    inp = GetEncounterContextInput(patient_id=10, date="2026-03-01")
    assert inp.date == "2026-03-01"


def test_input_schema_requires_encounter_id_or_date():
    with pytest.raises(ValueError, match="Either encounter_id or date must be provided"):
        GetEncounterContextInput(patient_id=10)


def test_input_schema_valid_with_both():
    inp = GetEncounterContextInput(patient_id=10, encounter_id=5, date="2026-03-01")
    assert inp.encounter_id == 5
    assert inp.date == "2026-03-01"


# -- _format_soap_notes --------------------------------------------------------


def test_format_soap_notes_full():
    notes = [_make_soap_note()]
    result = _format_soap_notes(notes)
    assert len(result) == 1
    assert result[0]["type"] == "SOAP"
    assert result[0]["date"] == "2026-03-01"
    assert "SUBJECTIVE:" in result[0]["summary"]
    assert "OBJECTIVE:" in result[0]["summary"]
    assert "ASSESSMENT:" in result[0]["summary"]
    assert "PLAN:" in result[0]["summary"]


def test_format_soap_notes_partial_sections():
    note = _make_soap_note(objective="", plan="")
    result = _format_soap_notes([note])
    assert len(result) == 1
    assert "OBJECTIVE:" not in result[0]["summary"]
    assert "PLAN:" not in result[0]["summary"]
    assert "SUBJECTIVE:" in result[0]["summary"]


def test_format_soap_notes_empty():
    assert _format_soap_notes([]) == []


def test_format_soap_notes_all_sections_empty():
    note = {"subjective": "", "objective": "", "assessment": "", "plan": "", "date": "2026-03-01"}
    result = _format_soap_notes([note])
    assert result[0]["summary"] == ""


# -- _format_encounter --------------------------------------------------------


def test_format_encounter():
    enc = make_encounter()
    result = _format_encounter(enc)
    assert result["id"] == 5
    assert result["date"] == "2026-03-01 09:00:00"
    assert result["reason"] == "Annual checkup"
    assert result["provider"]["id"] == 1
    assert result["facility"]["name"] == "Main Clinic"
    assert result["facility"]["id"] == 3
    assert result["class_code"] == "AMB"
    assert result["status"] == "Office Visit"


def test_format_encounter_minimal():
    enc = {"id": 1}
    result = _format_encounter(enc)
    assert result["id"] == 1
    assert result["date"] == ""
    assert result["reason"] == ""
    assert result["provider"]["name"] == ""
    assert result["facility"]["name"] == ""


# -- _format_patient -----------------------------------------------------------


def test_format_patient():
    patient = make_patient()
    result = _format_patient(patient)
    assert result["id"] == 10
    assert result["name"] == "John Doe"
    assert result["dob"] == "1980-01-15"
    assert result["sex"] == "Male"
    assert result["mrn"] == "MRN001"


def test_format_patient_missing_name_parts():
    patient = make_patient(fname="", lname="Smith")
    result = _format_patient(patient)
    assert result["name"] == "Smith"


# -- patient no UUID error path ------------------------------------------------


async def test_patient_no_uuid():
    patient = make_patient(uuid="")
    client = mock_encounter_client(patients=[patient])

    with pytest.raises(ToolException, match="Patient 10 has no UUID"):
        await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)


# -- FHIR fetch HTTP errors (graceful degradation) ----------------------------


async def test_fhir_conditions_error_returns_empty(mock_fhir_error_client):
    """HTTPStatusError in conditions fetch is caught and returns empty list."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_error_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/fhir/Condition"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["active_problems"] == []
    assert any("conditions_fetch_failed" in w for w in result["data_warnings"])


async def test_fhir_medications_error_returns_empty(mock_fhir_error_client):
    """HTTPStatusError in medications fetch is caught and returns empty list."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_error_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/fhir/MedicationRequest"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["medications"] == []
    assert any("medications_fetch_failed" in w for w in result["data_warnings"])


async def test_fhir_allergies_error_returns_empty(mock_fhir_error_client):
    """HTTPStatusError in allergies fetch is caught and returns empty list."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_error_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/fhir/AllergyIntolerance"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["allergies"] == []
    assert any("allergies_fetch_failed" in w for w in result["data_warnings"])


async def test_vitals_error_returns_none(mock_fhir_error_client):
    """HTTPStatusError in vitals fetch is caught and returns None."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_error_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/vital"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["vitals"] is None
    assert any("vitals_fetch_failed" in w for w in result["data_warnings"])


async def test_soap_notes_error_returns_empty(mock_fhir_error_client):
    """HTTPStatusError in SOAP notes fetch is caught and returns empty list."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_error_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/soap_note"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["existing_notes"] == []
    assert any("soap_notes_fetch_failed" in w for w in result["data_warnings"])


async def test_all_fhir_errors_still_returns_encounter(mock_fhir_error_client):
    """All clinical fetches fail gracefully; encounter/patient data still returned."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_error_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/fhir/Condition", "/fhir/MedicationRequest", "/fhir/AllergyIntolerance", "/vital", "/soap_note"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["encounter"]["id"] == 5
    assert result["patient"]["name"] == "John Doe"
    assert result["clinical_context"]["active_problems"] == []
    assert result["clinical_context"]["medications"] == []
    assert result["clinical_context"]["allergies"] == []
    assert result["clinical_context"]["vitals"] is None
    assert result["clinical_context"]["existing_notes"] == []
    assert len(result["data_warnings"]) == 5


# -- FHIR timeout errors (graceful degradation) --------------------------------


async def test_fhir_conditions_timeout_returns_empty(mock_fhir_timeout_client):
    """TimeoutException in conditions fetch is caught and returns empty list."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_timeout_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/fhir/Condition"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["active_problems"] == []
    assert any("conditions_fetch_failed" in w and "timed out" in w for w in result["data_warnings"])


async def test_fhir_conditions_request_error_returns_empty():
    """RequestError in conditions fetch is caught and returns empty list."""
    patient = make_patient()
    encounter = make_encounter()

    client = AsyncMock()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        if "/fhir/Condition" in path:
            raise httpx.ConnectError(
                "Connection failed",
                request=httpx.Request("GET", path),
            )
        if "/encounter/" in path and "/vital" in path:
            return {"data": []}
        if "/encounter/" in path and "/soap_note" in path:
            return {"data": []}
        if "/encounter" in path:
            return {"data": [encounter]}
        if "/patient" in path:
            return {"data": [patient]}
        return {"entry": []}

    client.get = AsyncMock(side_effect=mock_get)

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["active_problems"] == []
    assert any(
        "conditions_fetch_failed" in w and "network error" in w
        for w in result["data_warnings"]
    )


async def test_fhir_medications_timeout_returns_empty(mock_fhir_timeout_client):
    """TimeoutException in medications fetch is caught and returns empty list."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_timeout_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/fhir/MedicationRequest"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["medications"] == []
    assert any("medications_fetch_failed" in w and "timed out" in w for w in result["data_warnings"])


async def test_vitals_timeout_returns_none(mock_fhir_timeout_client):
    """TimeoutException in vitals fetch is caught and returns None."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_timeout_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/vital"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["clinical_context"]["vitals"] is None
    assert any("vitals_fetch_failed" in w and "timed out" in w for w in result["data_warnings"])


async def test_all_fhir_timeouts_produce_5_warnings(mock_fhir_timeout_client):
    """All 5 clinical fetches timeout; produces exactly 5 data_warnings."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_fhir_timeout_client(
        patients=[patient], encounters=[encounter],
        failing_paths={"/fhir/Condition", "/fhir/MedicationRequest", "/fhir/AllergyIntolerance", "/vital", "/soap_note"},
    )

    result = await _get_encounter_context_impl(client, patient_id=10, encounter_id=5)
    assert result["encounter"]["id"] == 5
    assert result["patient"]["name"] == "John Doe"
    assert len(result["data_warnings"]) == 5
    warning_prefixes = {w.split(":")[0] for w in result["data_warnings"]}
    assert warning_prefixes == {
        "conditions_fetch_failed",
        "medications_fetch_failed",
        "allergies_fetch_failed",
        "vitals_fetch_failed",
        "soap_notes_fetch_failed",
    }


# -- FHIR parsers: multiple entries and fallbacks ------------------------------


def test_parse_conditions_multiple():
    bundle = {"entry": [
        _make_fhir_condition(),
        _make_fhir_condition(code={"coding": [{"code": "I10", "display": "Hypertension"}]}),
    ]}
    result = _parse_conditions(bundle)
    assert len(result) == 2
    assert result[1]["code"] == "I10"
    assert result[1]["description"] == "Hypertension"


def test_parse_conditions_empty_coding():
    entry = {"resource": {"code": {"coding": []}, "onsetDateTime": "2020-01-01"}}
    result = _parse_conditions({"entry": [entry]})
    assert len(result) == 1
    assert result[0]["code"] == ""
    assert result[0]["description"] == ""


def test_parse_conditions_text_fallback():
    """When coding[0] has no 'display', falls back to code.text."""
    entry = {"resource": {"code": {"text": "Some condition", "coding": [{"code": "X99"}]}, "onsetDateTime": ""}}
    result = _parse_conditions({"entry": [entry]})
    assert result[0]["code"] == "X99"
    assert result[0]["description"] == "Some condition"


def test_parse_medications_empty():
    assert _parse_medications({}) == []
    assert _parse_medications({"entry": []}) == []


def test_parse_medications_no_dosage():
    entry = {"resource": {
        "medicationCodeableConcept": {"coding": [{"display": "Aspirin"}]},
        "dosageInstruction": [],
    }}
    result = _parse_medications({"entry": [entry]})
    assert result[0]["drug_name"] == "Aspirin"
    assert result[0]["dose"] == ""
    assert result[0]["frequency"] == ""


def test_parse_medications_text_fallback():
    """When coding[0] has no 'display', falls back to medicationCodeableConcept.text."""
    entry = {"resource": {
        "medicationCodeableConcept": {"text": "Custom Drug", "coding": [{}]},
    }}
    result = _parse_medications({"entry": [entry]})
    assert result[0]["drug_name"] == "Custom Drug"


def test_parse_allergies_empty():
    assert _parse_allergies({}) == []
    assert _parse_allergies({"entry": []}) == []


def test_parse_allergies_no_reaction():
    entry = {"resource": {
        "code": {"coding": [{"display": "Latex"}]},
        "reaction": [],
    }}
    result = _parse_allergies({"entry": [entry]})
    assert result[0]["substance"] == "Latex"
    assert result[0]["reaction"] == ""
    assert result[0]["severity"] == ""


def test_parse_allergies_multiple():
    bundle = {"entry": [
        _make_fhir_allergy(),
        {"resource": {
            "code": {"coding": [{"display": "Sulfa"}]},
            "reaction": [{"manifestation": [{"coding": [{"display": "Hives"}]}], "severity": "severe"}],
        }},
    ]}
    result = _parse_allergies(bundle)
    assert len(result) == 2
    assert result[1]["substance"] == "Sulfa"
    assert result[1]["severity"] == "severe"


# -- vitals edge cases ---------------------------------------------------------


def test_format_vitals_partial_bp_systolic_only():
    vitals = [_make_vitals(bps="130", bpd="")]
    result = _format_vitals(vitals)
    assert result["bp"] == "130"


def test_format_vitals_partial_bp_diastolic_only():
    vitals = [_make_vitals(bps="", bpd="85")]
    result = _format_vitals(vitals)
    assert result["bp"] == "85"


def test_format_vitals_uses_last_entry():
    """When multiple vitals exist, uses the last one."""
    vitals = [
        _make_vitals(temperature="97.0"),
        _make_vitals(temperature="99.1"),
    ]
    result = _format_vitals(vitals)
    assert result["temp"] == "99.1"


# -- string ID matching (Bug 3) -----------------------------------------------


async def test_get_encounter_by_id_with_string_ids():
    """OpenEMR API returns IDs as strings — must still match int encounter_id."""
    patient = make_patient()
    encounter = make_encounter(id="5")  # string, not int
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    result = await _get_encounter_context_impl(
        client, patient_id=10, encounter_id=5
    )

    assert result["encounter"]["id"] == "5"
    assert result["patient"]["name"] == "John Doe"
    assert result["data_warnings"] == []
