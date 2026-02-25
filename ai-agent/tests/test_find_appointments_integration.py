"""Integration tests for find_appointments against a live OpenEMR instance.

Requires Docker services running with seeded data.
Run via: INTEGRATION_TEST=1 uv run pytest tests/ -m integration -v
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

import pytest
from langchain_core.tools import ToolException

from ai_agent.config import get_settings
from ai_agent.tools.find_appointments import (
    _find_appointments_impl,
    find_appointments,
)
from tests.integration.config import (
    PATIENT_ID_COMPLETE,
    PATIENT_ID_INCOMPLETE,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.environ.get("INTEGRATION_TEST"),
        reason="Integration tests require Docker services (set INTEGRATION_TEST=1)",
    ),
]


# ---------------------------------------------------------------------------
# 1. Search by patient_id
# ---------------------------------------------------------------------------


class TestSearchByPatientId:
    async def test_known_patient_returns_appointments(self, api_client):
        """Known seed patient should have appointments."""
        async with api_client:
            result = await _find_appointments_impl(
                api_client, patient_id=PATIENT_ID_COMPLETE
            )
        assert result["total_count"] >= 1

    async def test_nonexistent_patient_returns_zero(self, api_client):
        """Nonexistent patient ID should return zero results."""
        async with api_client:
            result = await _find_appointments_impl(api_client, patient_id=999999)
        assert result["total_count"] == 0


# ---------------------------------------------------------------------------
# 2. Search by patient name
# ---------------------------------------------------------------------------


class TestSearchByPatientName:
    async def test_last_name_doe(self, api_client):
        """Searching by last name 'Doe' should find John Doe's appointments."""
        async with api_client:
            result = await _find_appointments_impl(api_client, patient_name="Doe")
        assert result["total_count"] >= 1
        names = [a["patient_name"] for a in result["appointments"]]
        assert any("Doe" in n for n in names)

    async def test_first_name_jane(self, api_client):
        """Searching by first name 'Jane' should find Jane Smith's appointments."""
        async with api_client:
            result = await _find_appointments_impl(api_client, patient_name="Jane")
        assert result["total_count"] >= 1
        names = [a["patient_name"] for a in result["appointments"]]
        assert any("Jane" in n for n in names)

    async def test_nonexistent_name(self, api_client):
        """Nonexistent name should return a 'No patients found' message."""
        async with api_client:
            result = await _find_appointments_impl(
                api_client, patient_name="Zzzznonexistent"
            )
        assert result["total_count"] == 0
        assert "No patients found" in result.get("message", "")


# ---------------------------------------------------------------------------
# 3. Date filter
# ---------------------------------------------------------------------------


class TestDateFilter:
    async def test_today_returns_results(self, api_client):
        """Today's date should have seed appointments."""
        today = date.today().isoformat()
        async with api_client:
            result = await _find_appointments_impl(api_client, date=today)
        assert result["total_count"] >= 3
        assert all(appt["date"] == today for appt in result["appointments"])
        patient_ids = {str(appt["patient_id"]) for appt in result["appointments"]}
        assert str(PATIENT_ID_COMPLETE) in patient_ids
        assert str(PATIENT_ID_INCOMPLETE) in patient_ids

    async def test_far_future_returns_zero(self, api_client):
        """Far future date should return zero results."""
        async with api_client:
            result = await _find_appointments_impl(api_client, date="2099-12-31")
        assert result["total_count"] == 0


# ---------------------------------------------------------------------------
# 4. Status filter
# ---------------------------------------------------------------------------


class TestStatusFilter:
    async def test_arrived_status(self, api_client):
        """Filtering by status '@' (arrived) on today should return results."""
        today = date.today().isoformat()
        async with api_client:
            result = await _find_appointments_impl(
                api_client, date=today, status="@"
            )
        assert result["total_count"] > 0
        statuses = {a["status"] for a in result["appointments"]}
        assert statuses == {"@"}


# ---------------------------------------------------------------------------
# 5. Output shape
# ---------------------------------------------------------------------------


class TestOutputShape:
    async def test_appointment_record_keys(self, api_client):
        """Appointment records should have all expected keys."""
        async with api_client:
            result = await _find_appointments_impl(
                api_client, patient_id=PATIENT_ID_COMPLETE
            )
        assert result["total_count"] >= 1
        appt = result["appointments"][0]
        expected_keys = {
            "appointment_id",
            "patient_name",
            "patient_id",
            "provider_name",
            "date",
            "start_time",
            "end_time",
            "status",
            "status_label",
            "category",
            "facility",
            "reason",
        }
        assert expected_keys.issubset(set(appt.keys()))


# ---------------------------------------------------------------------------
# 6. @tool wrapper end-to-end
# ---------------------------------------------------------------------------


class TestToolWrapper:
    async def test_tool_invoke(self):
        """End-to-end find_appointments.ainvoke returns results."""
        with patch("ai_agent.config.get_settings", return_value=get_settings()):
            result = await find_appointments.ainvoke(
                {"patient_id": PATIENT_ID_COMPLETE}
            )
        assert result["total_count"] >= 1
