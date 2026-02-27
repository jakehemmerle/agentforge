"""Tests for final-response verification node."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_agent.verification.node import verify_final_response

pytestmark = pytest.mark.unit


async def test_verify_passes_grounded_ready_claim():
    state = {
        "messages": [
            HumanMessage(content="Is this claim ready?"),
            ToolMessage(
                content=json.dumps(
                    {
                        "ready": True,
                        "errors": {},
                        "warnings": {},
                        "data_warnings": [],
                    }
                ),
                tool_call_id="call-1",
                name="validate_claim_ready_completeness",
            ),
            AIMessage(content="The claim is ready for submission."),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "pass"
    assert result["verification"]["confidence"] == "high"
    assert "messages" not in result


async def test_verify_warns_when_data_warning_not_disclosed():
    state = {
        "messages": [
            HumanMessage(content="Draft a note."),
            ToolMessage(
                content=json.dumps(
                    {
                        "draft_note": {"summary": "Draft"},
                        "data_warnings": ["vitals_fetch_failed: timeout"],
                    }
                ),
                tool_call_id="call-2",
                name="draft_encounter_note",
            ),
            AIMessage(content="I drafted the note from available context."),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "warn"
    assert result["verification"]["confidence"] == "medium"
    assert "messages" in result
    assert "Verification caveat" in result["messages"][0].content


async def test_verify_fails_false_claim_readiness():
    state = {
        "messages": [
            HumanMessage(content="Is claim ready?"),
            ToolMessage(
                content=json.dumps(
                    {
                        "ready": False,
                        "errors": {"diagnosis_codes": "Missing ICD10 code"},
                        "warnings": {},
                        "data_warnings": [],
                    }
                ),
                tool_call_id="call-3",
                name="validate_claim_ready_completeness",
            ),
            AIMessage(content="The claim is ready for submission."),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "fail"
    assert result["verification"]["confidence"] == "low"
    assert "messages" in result
    assert "cannot provide a reliable final answer" in result["messages"][0].content


async def test_verify_fails_prohibited_phrase_for_warning_prefix():
    state = {
        "messages": [
            HumanMessage(content="Draft SOAP note."),
            ToolMessage(
                content=json.dumps(
                    {
                        "draft_note": {"summary": "Draft"},
                        "data_warnings": ["vitals_fetch_failed: timeout"],
                    }
                ),
                tool_call_id="call-4",
                name="draft_encounter_note",
            ),
            AIMessage(content="Blood pressure is 120/80 and heart rate is stable."),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "fail"
    assert result["verification"]["confidence"] == "low"


async def test_verify_returns_empty_for_non_ai_last_message():
    state = {
        "messages": [
            HumanMessage(content="hello"),
            ToolMessage(content="{}", tool_call_id="call-5", name="find_appointments"),
        ]
    }
    result = await verify_final_response(state)
    assert result == {}


async def test_verify_fails_nkda_when_allergies_fetch_failed():
    state = {
        "messages": [
            HumanMessage(content="Any allergies?"),
            ToolMessage(
                content=json.dumps(
                    {
                        "clinical_context": {},
                        "data_warnings": ["allergies_fetch_failed: timeout"],
                    }
                ),
                tool_call_id="call-6",
                name="get_encounter_context",
            ),
            AIMessage(content="Patient has NKDA."),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "fail"
    assert result["verification"]["confidence"] == "low"


async def test_verify_fails_soap_claims_when_soap_notes_fetch_failed():
    state = {
        "messages": [
            HumanMessage(content="Draft SOAP summary."),
            ToolMessage(
                content=json.dumps(
                    {
                        "draft_note": {"summary": "Draft"},
                        "data_warnings": ["soap_notes_fetch_failed: HTTP 500"],
                    }
                ),
                tool_call_id="call-7",
                name="draft_encounter_note",
            ),
            AIMessage(content="Subjective and objective findings were both stable."),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "fail"
    assert result["verification"]["confidence"] == "low"


async def test_verify_fails_medications_claim_when_medications_fetch_failed():
    state = {
        "messages": [
            HumanMessage(content="What medications is this patient on?"),
            ToolMessage(
                content=json.dumps(
                    {
                        "patient": {"id": 90001, "name": "John Doe"},
                        "active_problems": [],
                        "medications": [],
                        "allergies": [],
                        "data_warnings": ["medications_fetch_failed: HTTP 500"],
                    }
                ),
                tool_call_id="call-ps-1",
                name="get_patient_summary",
            ),
            AIMessage(
                content="The patient is currently taking Metformin 500mg twice daily."
            ),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "fail"
    assert result["verification"]["confidence"] == "low"


async def test_verify_fails_conditions_claim_when_conditions_fetch_failed():
    state = {
        "messages": [
            HumanMessage(content="What conditions does this patient have?"),
            ToolMessage(
                content=json.dumps(
                    {
                        "patient": {"id": 90001, "name": "John Doe"},
                        "active_problems": [],
                        "medications": [],
                        "allergies": [],
                        "data_warnings": ["conditions_fetch_failed: timeout"],
                    }
                ),
                tool_call_id="call-ps-2",
                name="get_patient_summary",
            ),
            AIMessage(
                content="The patient has been diagnosed with diabetes and hypertension."
            ),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "fail"
    assert result["verification"]["confidence"] == "low"


async def test_verify_alias_prefixes_still_match_rules():
    state = {
        "messages": [
            HumanMessage(content="Any allergies?"),
            ToolMessage(
                content=json.dumps(
                    {
                        "clinical_context": {},
                        "data_warnings": ["allergy_fetch_failed: timeout"],
                    }
                ),
                tool_call_id="call-8",
                name="get_encounter_context",
            ),
            AIMessage(content="No known drug allergies."),
        ]
    }

    result = await verify_final_response(state)
    assert result["verification"]["decision"] == "fail"
