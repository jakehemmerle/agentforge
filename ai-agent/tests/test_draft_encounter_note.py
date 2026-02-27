"""Tests for the draft_encounter_note tool."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import ToolException

from ai_agent.tools.draft_encounter_note import (
    DraftEncounterNoteInput,
    _build_encounter_summary,
    _draft_encounter_note_impl,
    _format_full_text,
    _parse_llm_response,
)
from tests.helpers import make_encounter, make_patient, mock_encounter_client

pytestmark = pytest.mark.unit


# -- helpers -------------------------------------------------------------------


def _make_encounter_context(**overrides: Any) -> dict[str, Any]:
    """Build a complete encounter context response as returned by _get_encounter_context_impl."""
    base = {
        "encounter": {
            "id": 5,
            "date": "2026-03-01 09:00:00",
            "reason": "Annual checkup",
            "provider": {"name": "", "id": 1},
            "facility": {"name": "Main Clinic", "id": 3},
            "class_code": "AMB",
            "status": "Office Visit",
        },
        "patient": {
            "id": 10,
            "name": "John Doe",
            "dob": "1980-01-15",
            "sex": "Male",
            "mrn": "MRN001",
        },
        "clinical_context": {
            "active_problems": [
                {
                    "code": "E11.9",
                    "description": "Type 2 diabetes",
                    "onset_date": "2020-06-15",
                },
            ],
            "medications": [
                {
                    "drug_name": "Metformin",
                    "dose": "500 mg",
                    "frequency": "twice daily",
                },
            ],
            "allergies": [
                {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"},
            ],
            "vitals": {
                "temp": "98.6",
                "bp": "120/80",
                "hr": "72",
                "rr": "16",
                "spo2": "98",
                "weight": "180",
                "height": "70",
            },
            "existing_notes": [
                {
                    "type": "SOAP",
                    "date": "2026-03-01",
                    "summary": "SUBJECTIVE: Patient reports feeling well.",
                },
            ],
        },
        "billing_status": {
            "has_dx_codes": False,
            "has_cpt_codes": False,
            "dx_codes": [],
            "cpt_codes": [],
            "billing_note": "",
            "last_level_billed": "0",
            "last_level_closed": "0",
        },
    }
    base.update(overrides)
    return base


def _mock_llm(response_json: dict[str, Any]) -> AsyncMock:
    """Build a mock ChatAnthropic that returns the given JSON as content."""
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=json.dumps(response_json)))
    return llm


# -- _build_encounter_summary --------------------------------------------------


def test_build_encounter_summary_full():
    ctx = _make_encounter_context()
    summary = _build_encounter_summary(ctx)
    assert "John Doe" in summary
    assert "Annual checkup" in summary
    assert "Type 2 diabetes" in summary
    assert "Metformin" in summary
    assert "Penicillin" in summary
    assert "120/80" in summary


def test_build_encounter_summary_empty_clinical():
    ctx = _make_encounter_context(
        clinical_context={
            "active_problems": [],
            "medications": [],
            "allergies": [],
            "vitals": None,
            "existing_notes": [],
        }
    )
    summary = _build_encounter_summary(ctx)
    assert "None documented" in summary
    assert "Not recorded" in summary


# -- _parse_llm_response -------------------------------------------------------


def test_parse_llm_response_valid_json():
    data = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    result, failed = _parse_llm_response(json.dumps(data), "SOAP")
    assert result == data
    assert failed is False


def test_parse_llm_response_with_code_fences():
    data = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    wrapped = f"```json\n{json.dumps(data)}\n```"
    result, failed = _parse_llm_response(wrapped, "SOAP")
    assert result == data
    assert failed is False


def test_parse_llm_response_invalid_json_soap():
    result, failed = _parse_llm_response("not valid json", "SOAP")
    assert result["subjective"] == "not valid json"
    assert result["objective"] == "No data available"
    assert failed is True


def test_parse_llm_response_invalid_json_progress():
    result, failed = _parse_llm_response("free text note", "progress")
    assert result["narrative"] == "free text note"
    assert failed is True


def test_parse_llm_response_invalid_json_brief():
    result, failed = _parse_llm_response("short summary", "brief")
    assert result["summary"] == "short summary"
    assert failed is True


# -- _format_full_text ---------------------------------------------------------


def test_format_full_text_soap():
    content = {
        "subjective": "CC here",
        "objective": "Vitals normal",
        "assessment": "Stable",
        "plan": "Follow up",
    }
    text = _format_full_text(content, "SOAP")
    assert "S: CC here" in text
    assert "O: Vitals normal" in text
    assert "A: Stable" in text
    assert "P: Follow up" in text


def test_format_full_text_progress():
    content = {"narrative": "Patient doing well."}
    text = _format_full_text(content, "progress")
    assert text == "Patient doing well."


def test_format_full_text_brief():
    content = {"summary": "Brief encounter summary."}
    text = _format_full_text(content, "brief")
    assert text == "Brief encounter summary."


# -- full implementation -------------------------------------------------------


async def test_draft_soap_note():
    """Full flow: fetch context, call LLM, return structured draft."""
    patient = make_patient()
    encounter = make_encounter()
    vitals = [
        {
            "temperature": "98.6",
            "bps": "120",
            "bpd": "80",
            "pulse": "72",
            "respiration": "16",
            "oxygen_saturation": "98",
            "weight": "180",
            "height": "70",
        }
    ]
    conditions_bundle = {
        "entry": [
            {
                "resource": {
                    "code": {
                        "coding": [{"code": "E11.9", "display": "Type 2 diabetes"}]
                    },
                    "onsetDateTime": "2020-06-15",
                }
            }
        ]
    }
    medications_bundle = {
        "entry": [
            {
                "resource": {
                    "medicationCodeableConcept": {"coding": [{"display": "Metformin"}]},
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
        ]
    }
    allergies_bundle = {
        "entry": [
            {
                "resource": {
                    "code": {"coding": [{"display": "Penicillin"}]},
                    "reaction": [
                        {
                            "manifestation": [{"coding": [{"display": "Rash"}]}],
                            "severity": "moderate",
                        }
                    ],
                }
            }
        ]
    }

    client = mock_encounter_client(
        patients=[patient],
        encounters=[encounter],
        vitals=vitals,
        conditions_bundle=conditions_bundle,
        medications_bundle=medications_bundle,
        allergies_bundle=allergies_bundle,
    )

    llm_response = {
        "subjective": "Patient presents for annual checkup. Reports feeling well.",
        "objective": "Vitals: T 98.6, BP 120/80, HR 72, RR 16, SpO2 98%.",
        "assessment": "Type 2 diabetes, well controlled.",
        "plan": "Continue Metformin 500mg BID. Follow up in 3 months.",
    }
    llm = _mock_llm(llm_response)

    result = await _draft_encounter_note_impl(
        client, llm, encounter_id=5, patient_id=10, note_type="SOAP"
    )

    assert result["draft_note"]["type"] == "SOAP"
    assert result["draft_note"]["encounter_id"] == 5
    assert result["draft_note"]["patient_name"] == "John Doe"
    assert result["draft_note"]["content"]["subjective"] == llm_response["subjective"]
    assert "S: " in result["draft_note"]["full_text"]
    assert "generated_at" in result["draft_note"]
    assert (
        result["disclaimer"]
        == "This is an AI-generated draft. Review and edit before saving."
    )
    assert result["warnings"] == []
    assert result["data_warnings"] == []

    # Verify LLM was called with encounter context
    llm.ainvoke.assert_called_once()
    call_messages = llm.ainvoke.call_args[0][0]
    assert len(call_messages) == 2  # system + human
    assert "Annual checkup" in call_messages[1].content
    assert "Type 2 diabetes" in call_messages[1].content


async def test_draft_progress_note():
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"narrative": "Patient seen for annual checkup. Stable."}
    llm = _mock_llm(llm_response)

    result = await _draft_encounter_note_impl(
        client, llm, encounter_id=5, patient_id=10, note_type="progress"
    )

    assert result["draft_note"]["type"] == "progress"
    assert (
        result["draft_note"]["content"]["narrative"]
        == "Patient seen for annual checkup. Stable."
    )
    assert (
        result["draft_note"]["full_text"] == "Patient seen for annual checkup. Stable."
    )


async def test_draft_brief_note():
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"summary": "Annual checkup, stable diabetes, continue meds."}
    llm = _mock_llm(llm_response)

    result = await _draft_encounter_note_impl(
        client, llm, encounter_id=5, patient_id=10, note_type="brief"
    )

    assert result["draft_note"]["type"] == "brief"
    assert (
        result["draft_note"]["full_text"]
        == "Annual checkup, stable diabetes, continue meds."
    )


async def test_invalid_note_type_defaults_to_soap():
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    llm = _mock_llm(llm_response)

    result = await _draft_encounter_note_impl(
        client, llm, encounter_id=5, patient_id=10, note_type="invalid"
    )

    assert result["draft_note"]["type"] == "SOAP"
    assert any("defaulting to SOAP" in w for w in result["warnings"])


async def test_missing_encounter_raises():
    patient = make_patient()
    client = mock_encounter_client(patients=[patient], encounters=[])
    llm = _mock_llm({})

    with pytest.raises(ToolException, match="No encounter found with ID 999"):
        await _draft_encounter_note_impl(client, llm, encounter_id=999, patient_id=10)


async def test_missing_patient_raises():
    client = mock_encounter_client(patients=[])
    llm = _mock_llm({})

    with pytest.raises(ToolException, match="No patient found with ID 99"):
        await _draft_encounter_note_impl(client, llm, encounter_id=5, patient_id=99)


async def test_warnings_for_missing_clinical_data():
    """When vitals/problems/meds are missing, warnings are included."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    llm = _mock_llm(llm_response)

    result = await _draft_encounter_note_impl(
        client, llm, encounter_id=5, patient_id=10
    )

    warning_texts = " ".join(result["warnings"])
    assert "No vitals" in warning_texts
    assert "No active problems" in warning_texts
    assert "No medications" in warning_texts


async def test_additional_context_included_in_prompt():
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    llm = _mock_llm(llm_response)

    await _draft_encounter_note_impl(
        client,
        llm,
        encounter_id=5,
        patient_id=10,
        additional_context="Patient mentioned knee pain during conversation.",
    )

    call_messages = llm.ainvoke.call_args[0][0]
    assert "knee pain" in call_messages[1].content


# -- input schema validation ---------------------------------------------------


def test_input_schema_required_fields():
    inp = DraftEncounterNoteInput(encounter_id=5, patient_id=10)
    assert inp.encounter_id == 5
    assert inp.patient_id == 10
    assert inp.note_type == "SOAP"
    assert inp.additional_context is None


def test_input_schema_with_all_fields():
    inp = DraftEncounterNoteInput(
        encounter_id=5,
        patient_id=10,
        note_type="progress",
        additional_context="Extra info",
    )
    assert inp.note_type == "progress"
    assert inp.additional_context == "Extra info"


def test_input_schema_missing_encounter_id():
    with pytest.raises(Exception):
        DraftEncounterNoteInput(patient_id=10)


def test_input_schema_missing_patient_id():
    with pytest.raises(Exception):
        DraftEncounterNoteInput(encounter_id=5)


# -- additional coverage: disambiguation, LLM errors, edge cases ---------------


async def test_disambiguation_raises_tool_exception():
    """When get_encounter_context returns multiple encounters, a ToolException is raised."""
    patient = make_patient()
    # Two encounters on the same date — triggers disambiguation in get_encounter_context
    enc1 = make_encounter(id=5, date="2026-03-01 09:00:00", reason="Morning visit")
    enc2 = make_encounter(
        id=6, date="2026-03-01 14:00:00", reason="Afternoon follow-up"
    )
    client = mock_encounter_client(patients=[patient], encounters=[enc1, enc2])
    llm = _mock_llm({})

    # _get_encounter_context_impl is called with encounter_id=None and date,
    # so we need to patch it to return a disambiguation response
    disambiguation = {
        "message": "Multiple encounters found on 2026-03-01. Please specify encounter_id.",
        "encounters": [
            {"id": 5, "date": "2026-03-01 09:00:00", "reason": "Morning visit"},
            {"id": 6, "date": "2026-03-01 14:00:00", "reason": "Afternoon follow-up"},
        ],
    }

    with patch(
        "ai_agent.tools.draft_encounter_note._get_encounter_context_impl",
        new_callable=AsyncMock,
        return_value=disambiguation,
    ):
        with pytest.raises(ToolException, match="Multiple encounters"):
            await _draft_encounter_note_impl(client, llm, encounter_id=5, patient_id=10)


async def test_llm_invocation_error_propagates():
    """When the LLM raises an exception, it propagates up."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm = AsyncMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM service unavailable"))

    with pytest.raises(RuntimeError, match="LLM service unavailable"):
        await _draft_encounter_note_impl(client, llm, encounter_id=5, patient_id=10)


async def test_llm_non_string_content():
    """When LLM returns non-string content (e.g. list), it's coerced to str."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    # Simulate LLM returning a list (non-string content)
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(content=[{"type": "text", "text": "some content"}])
    )

    result = await _draft_encounter_note_impl(
        client, llm, encounter_id=5, patient_id=10, note_type="brief"
    )

    # Should not crash; the non-string content is stringified and wrapped as fallback
    assert "draft_note" in result
    assert result["draft_note"]["type"] == "brief"
    # Non-string content gets str()-ified then hits JSON parse fallback
    assert "summary" in result["draft_note"]["content"]


async def test_no_additional_context_omitted_from_prompt():
    """When additional_context is None, the ADDITIONAL CONTEXT section is absent."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    llm = _mock_llm(llm_response)

    await _draft_encounter_note_impl(
        client,
        llm,
        encounter_id=5,
        patient_id=10,
        additional_context=None,
    )

    call_messages = llm.ainvoke.call_args[0][0]
    assert "ADDITIONAL CONTEXT" not in call_messages[1].content


async def test_system_prompt_contains_safety_instructions():
    """The system message includes critical safety rules for the LLM."""
    patient = make_patient()
    encounter = make_encounter()
    client = mock_encounter_client(patients=[patient], encounters=[encounter])

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    llm = _mock_llm(llm_response)

    await _draft_encounter_note_impl(client, llm, encounter_id=5, patient_id=10)

    call_messages = llm.ainvoke.call_args[0][0]
    system_msg = call_messages[0].content
    assert "NEVER fabricate" in system_msg
    assert "DRAFT" in system_msg
    assert "valid JSON" in system_msg


def test_parse_llm_response_empty_string():
    """Empty string input falls back to the note type's default structure."""
    result, failed = _parse_llm_response("", "SOAP")
    assert result["subjective"] == ""
    assert result["objective"] == "No data available"
    assert failed is True


def test_parse_llm_response_whitespace_only():
    """Whitespace-only input falls back to the note type's default structure."""
    result, failed = _parse_llm_response("   \n\t  ", "progress")
    assert "narrative" in result
    assert failed is True


def test_parse_llm_response_code_fences_no_language():
    """Code fences without a language tag (just ```) are stripped correctly."""
    data = {"narrative": "Patient stable."}
    wrapped = f"```\n{json.dumps(data)}\n```"
    result, failed = _parse_llm_response(wrapped, "progress")
    assert result == data
    assert failed is False


def test_format_full_text_soap_missing_keys():
    """SOAP format handles missing keys gracefully with defaults."""
    content = {"subjective": "CC here"}  # missing objective, assessment, plan
    text = _format_full_text(content, "SOAP")
    assert "S: CC here" in text
    assert "O: No data available" in text
    assert "A: No data available" in text
    assert "P: No data available" in text


def test_format_full_text_progress_missing_key():
    """Progress format returns empty string when narrative key is missing."""
    content = {}
    text = _format_full_text(content, "progress")
    assert text == ""


def test_format_full_text_brief_missing_key():
    """Brief format returns empty string when summary key is missing."""
    content = {}
    text = _format_full_text(content, "brief")
    assert text == ""


def test_build_encounter_summary_empty_dicts():
    """_build_encounter_summary handles completely empty patient/encounter gracefully."""
    ctx = {
        "patient": {},
        "encounter": {},
        "clinical_context": {},
    }
    summary = _build_encounter_summary(ctx)
    # Should not crash; empty dicts are falsy so patient/encounter sections are skipped
    # but clinical sections still appear with defaults
    assert "None documented" in summary
    assert "Not recorded" in summary


def test_build_encounter_summary_existing_notes():
    """Existing notes section is included when notes are present."""
    ctx = _make_encounter_context()
    summary = _build_encounter_summary(ctx)
    assert "EXISTING NOTES:" in summary
    assert "Patient reports feeling well" in summary


def test_build_encounter_summary_no_existing_notes():
    """Existing notes section is omitted when no notes exist."""
    ctx = _make_encounter_context(
        clinical_context={
            "active_problems": [],
            "medications": [],
            "allergies": [],
            "vitals": None,
            "existing_notes": [],
        }
    )
    summary = _build_encounter_summary(ctx)
    assert "EXISTING NOTES:" not in summary


# -- data_warnings tests ------------------------------------------------------


async def test_data_warnings_propagated_from_upstream():
    """data_warnings from get_encounter_context are included in draft output."""
    patient = make_patient()
    encounter = make_encounter()
    upstream_warnings = [
        "vitals_fetch_failed: request timed out",
        "conditions_fetch_failed: HTTP 500",
    ]

    context = _make_encounter_context(
        data_warnings=upstream_warnings,
        clinical_context={
            "active_problems": [],
            "medications": [
                {
                    "drug_name": "Metformin",
                    "dose": "500 mg",
                    "frequency": "twice daily",
                },
            ],
            "allergies": [],
            "vitals": None,
            "existing_notes": [],
        },
    )

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    llm = _mock_llm(llm_response)

    with patch(
        "ai_agent.tools.draft_encounter_note._get_encounter_context_impl",
        new_callable=AsyncMock,
        return_value=context,
    ):
        client = mock_encounter_client(patients=[patient], encounters=[encounter])
        result = await _draft_encounter_note_impl(
            client, llm, encounter_id=5, patient_id=10
        )

    assert "data_warnings" in result
    assert "vitals_fetch_failed: request timed out" in result["data_warnings"]
    assert "conditions_fetch_failed: HTTP 500" in result["data_warnings"]


async def test_data_warnings_llm_parse_failure():
    """When LLM returns invalid JSON, data_warnings includes parse failure warning."""
    patient = make_patient()
    encounter = make_encounter()

    context = _make_encounter_context(data_warnings=[])

    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="this is not json at all"))

    with patch(
        "ai_agent.tools.draft_encounter_note._get_encounter_context_impl",
        new_callable=AsyncMock,
        return_value=context,
    ):
        client = mock_encounter_client(patients=[patient], encounters=[encounter])
        result = await _draft_encounter_note_impl(
            client, llm, encounter_id=5, patient_id=10
        )

    assert any("llm_response_parse_failed" in w for w in result["data_warnings"])


async def test_fetch_failed_vs_genuinely_absent_vitals():
    """Vitals fetch failure produces different warning text than genuinely missing vitals."""
    patient = make_patient()
    encounter = make_encounter()

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}

    # Case 1: vitals genuinely absent (no data_warnings about vitals)
    context_absent = _make_encounter_context(
        data_warnings=[],
        clinical_context={
            "active_problems": [
                {"code": "E11.9", "description": "Diabetes", "onset_date": "2020-01-01"}
            ],
            "medications": [
                {"drug_name": "Metformin", "dose": "500 mg", "frequency": "BID"}
            ],
            "allergies": [],
            "vitals": None,
            "existing_notes": [],
        },
    )

    with patch(
        "ai_agent.tools.draft_encounter_note._get_encounter_context_impl",
        new_callable=AsyncMock,
        return_value=context_absent,
    ):
        client = mock_encounter_client(patients=[patient], encounters=[encounter])
        result_absent = await _draft_encounter_note_impl(
            client, _mock_llm(llm_response), encounter_id=5, patient_id=10
        )

    # Case 2: vitals fetch failed (data_warnings contains vitals_fetch_failed)
    context_failed = _make_encounter_context(
        data_warnings=["vitals_fetch_failed: request timed out"],
        clinical_context={
            "active_problems": [
                {"code": "E11.9", "description": "Diabetes", "onset_date": "2020-01-01"}
            ],
            "medications": [
                {"drug_name": "Metformin", "dose": "500 mg", "frequency": "BID"}
            ],
            "allergies": [],
            "vitals": None,
            "existing_notes": [],
        },
    )

    with patch(
        "ai_agent.tools.draft_encounter_note._get_encounter_context_impl",
        new_callable=AsyncMock,
        return_value=context_failed,
    ):
        client = mock_encounter_client(patients=[patient], encounters=[encounter])
        result_failed = await _draft_encounter_note_impl(
            client, _mock_llm(llm_response), encounter_id=5, patient_id=10
        )

    # Genuinely absent: "No vitals recorded"
    assert any("No vitals recorded" in w for w in result_absent["warnings"])
    assert not any(
        "fetch" in w.lower() for w in result_absent["warnings"] if "vitals" in w.lower()
    )

    # Fetch failed: "fetch from EHR failed"
    assert any("fetch from EHR failed" in w for w in result_failed["warnings"])


async def test_fetch_failed_vs_genuinely_absent_problems():
    """Active problems fetch failure produces different warning text than genuinely missing."""
    patient = make_patient()
    encounter = make_encounter()

    llm_response = {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}

    # Case 1: genuinely absent
    context_absent = _make_encounter_context(
        data_warnings=[],
        clinical_context={
            "active_problems": [],
            "medications": [
                {"drug_name": "Metformin", "dose": "500 mg", "frequency": "BID"}
            ],
            "allergies": [],
            "vitals": {
                "temp": "98.6",
                "bp": "120/80",
                "hr": "72",
                "rr": "16",
                "spo2": "98",
                "weight": "180",
                "height": "70",
            },
            "existing_notes": [],
        },
    )

    with patch(
        "ai_agent.tools.draft_encounter_note._get_encounter_context_impl",
        new_callable=AsyncMock,
        return_value=context_absent,
    ):
        client = mock_encounter_client(patients=[patient], encounters=[encounter])
        result_absent = await _draft_encounter_note_impl(
            client, _mock_llm(llm_response), encounter_id=5, patient_id=10
        )

    # Case 2: fetch failed
    context_failed = _make_encounter_context(
        data_warnings=["conditions_fetch_failed: HTTP 500"],
        clinical_context={
            "active_problems": [],
            "medications": [
                {"drug_name": "Metformin", "dose": "500 mg", "frequency": "BID"}
            ],
            "allergies": [],
            "vitals": {
                "temp": "98.6",
                "bp": "120/80",
                "hr": "72",
                "rr": "16",
                "spo2": "98",
                "weight": "180",
                "height": "70",
            },
            "existing_notes": [],
        },
    )

    with patch(
        "ai_agent.tools.draft_encounter_note._get_encounter_context_impl",
        new_callable=AsyncMock,
        return_value=context_failed,
    ):
        client = mock_encounter_client(patients=[patient], encounters=[encounter])
        result_failed = await _draft_encounter_note_impl(
            client, _mock_llm(llm_response), encounter_id=5, patient_id=10
        )

    # Genuinely absent: "No active problems documented"
    assert any("No active problems documented" in w for w in result_absent["warnings"])

    # Fetch failed: "Active problems unavailable" with "fetch from EHR failed"
    assert any(
        "Active problems unavailable" in w and "fetch from EHR failed" in w
        for w in result_failed["warnings"]
    )
