"""Tests for the find_appointments tool."""

from __future__ import annotations

from typing import Any

import pytest

from ai_agent.tools.find_appointments import (
    FindAppointmentsInput,
    _find_appointments_impl,
    _format_appointment,
)
from tests.helpers import make_patient

pytestmark = pytest.mark.unit


# -- helpers -------------------------------------------------------------------


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


# -- _format_appointment -------------------------------------------------------


def test_format_appointment_basic():
    raw = _make_appointment()
    out = _format_appointment(raw)
    assert out["appointment_id"] == 1
    assert out["patient_name"] == "John Doe"
    assert out["patient_id"] == 10
    assert out["provider_name"] == "Dr Smith"
    assert out["date"] == "2026-03-01"
    assert out["start_time"] == "09:00:00"
    assert out["end_time"] == "09:30:00"
    assert out["status"] == "@"
    assert out["status_label"] == "Arrived"
    assert out["category"] == "Office Visit"
    assert out["facility"] == "Main Clinic"
    assert out["reason"] == "Follow-up"


def test_format_appointment_unknown_status():
    raw = _make_appointment(pc_apptstatus="Z")
    out = _format_appointment(raw)
    assert out["status_label"] == "Z"


# -- search by patient_id (direct) --------------------------------------------


async def test_search_by_patient_id(mock_appointment_client):
    appts = [_make_appointment(), _make_appointment(pc_eid=2)]
    client = mock_appointment_client(patient_appointments={10: appts})

    result = await _find_appointments_impl(client, patient_id=10)

    assert result["total_count"] == 2
    assert len(result["appointments"]) == 2
    assert result["appointments"][0]["appointment_id"] == 1


# -- search by patient_name ---------------------------------------------------


async def test_search_by_patient_name_single_match(mock_appointment_client):
    patients = [make_patient()]
    appts = [_make_appointment()]
    client = mock_appointment_client(
        patients=patients, patient_appointments={10: appts}
    )

    result = await _find_appointments_impl(client, patient_name="Doe")

    assert result["total_count"] == 1
    assert result["appointments"][0]["patient_name"] == "John Doe"


async def test_search_by_patient_name_no_match(mock_appointment_client):
    client = mock_appointment_client(patients=[])

    result = await _find_appointments_impl(client, patient_name="Nobody")

    assert result["total_count"] == 0
    assert "No patients found" in result["message"]


async def test_search_by_patient_name_ambiguous(mock_appointment_client):
    """More than 5 matches triggers disambiguation."""
    patients = [make_patient(pid=i, fname=f"P{i}") for i in range(6)]
    client = mock_appointment_client(patients=patients)

    result = await _find_appointments_impl(client, patient_name="P")

    assert result["total_count"] == 0
    assert "Multiple patients" in result["message"]
    assert "matching_patients" in result
    assert len(result["matching_patients"]) == 6


# -- search all appointments (no patient filter) -------------------------------


async def test_search_all_appointments(mock_appointment_client):
    appts = [
        _make_appointment(pc_eid=1),
        _make_appointment(pc_eid=2, pc_eventDate="2026-03-02"),
    ]
    client = mock_appointment_client(appointments=appts)

    result = await _find_appointments_impl(client)

    assert result["total_count"] == 2


# -- date filter ---------------------------------------------------------------


async def test_filter_by_date(mock_appointment_client):
    appts = [
        _make_appointment(pc_eid=1, pc_eventDate="2026-03-01"),
        _make_appointment(pc_eid=2, pc_eventDate="2026-03-02"),
    ]
    client = mock_appointment_client(appointments=appts)

    result = await _find_appointments_impl(client, date="2026-03-01")

    assert result["total_count"] == 1
    assert result["appointments"][0]["date"] == "2026-03-01"


# -- status filter -------------------------------------------------------------


async def test_filter_by_status(mock_appointment_client):
    appts = [
        _make_appointment(pc_eid=1, pc_apptstatus="@"),
        _make_appointment(pc_eid=2, pc_apptstatus="-"),
    ]
    client = mock_appointment_client(appointments=appts)

    result = await _find_appointments_impl(client, status="-")

    assert result["total_count"] == 1
    assert result["appointments"][0]["status"] == "-"


# -- provider filter -----------------------------------------------------------


async def test_filter_by_provider(mock_appointment_client):
    appts = [
        _make_appointment(pc_eid=1, pce_aid_fname="Dr", pce_aid_lname="Smith"),
        _make_appointment(pc_eid=2, pce_aid_fname="Dr", pce_aid_lname="Jones"),
    ]
    client = mock_appointment_client(appointments=appts)

    result = await _find_appointments_impl(client, provider_name="Jones")

    assert result["total_count"] == 1
    assert result["appointments"][0]["provider_name"] == "Dr Jones"


# -- combined filters ----------------------------------------------------------


async def test_combined_filters(mock_appointment_client):
    appts = [
        _make_appointment(pc_eid=1, pc_eventDate="2026-03-01", pc_apptstatus="@"),
        _make_appointment(pc_eid=2, pc_eventDate="2026-03-01", pc_apptstatus="-"),
        _make_appointment(pc_eid=3, pc_eventDate="2026-03-02", pc_apptstatus="@"),
    ]
    client = mock_appointment_client(patient_appointments={10: appts})

    result = await _find_appointments_impl(
        client, patient_id=10, date="2026-03-01", status="@"
    )

    assert result["total_count"] == 1
    assert result["appointments"][0]["appointment_id"] == 1


# -- no results ----------------------------------------------------------------


async def test_no_results_message(mock_appointment_client):
    client = mock_appointment_client(appointments=[])

    result = await _find_appointments_impl(client, date="2099-01-01")

    assert result["total_count"] == 0
    assert "No appointments found" in result["message"]


# -- input schema validation ---------------------------------------------------


def test_input_schema_all_optional():
    """All fields are optional — empty input is valid."""
    inp = FindAppointmentsInput()
    assert inp.patient_name is None
    assert inp.date is None
    assert inp.patient_id is None


def test_input_schema_with_values():
    inp = FindAppointmentsInput(patient_name="Doe", date="2026-03-01", patient_id=5)
    assert inp.patient_name == "Doe"
    assert inp.date == "2026-03-01"
    assert inp.patient_id == 5
