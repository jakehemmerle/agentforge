"""Integration tests for get_patient_summary against a live OpenEMR instance.

Requires Docker services running with seeded data.
Run via: INTEGRATION_TEST=1 uv run pytest tests/ -m integration -v
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from langchain_core.tools import ToolException

from ai_agent.config import get_settings
from ai_agent.tools.get_patient_summary import (
    _get_patient_summary_impl,
    get_patient_summary,
)
from tests.integration.config import (
    PATIENT_ID_COMPLETE,
    PATIENT_ID_INCOMPLETE,
    PATIENT_ID_JOHNSON,
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
# 1. By patient ID
# ---------------------------------------------------------------------------


class TestByPatientId:
    async def test_complete_patient(self, api_client):
        """Patient 90001 should have meds, allergies, and problems."""
        async with api_client:
            result = await _get_patient_summary_impl(
                api_client,
                patient_id=PATIENT_ID_COMPLETE,
            )
        assert result["patient"]["name"] != ""
        assert result["data_warnings"] == []

    async def test_incomplete_patient(self, api_client):
        """Patient 90002 should still return a valid summary."""
        async with api_client:
            result = await _get_patient_summary_impl(
                api_client,
                patient_id=PATIENT_ID_INCOMPLETE,
            )
        assert result["patient"]["id"] == PATIENT_ID_INCOMPLETE
        assert isinstance(result["active_problems"], list)
        assert isinstance(result["medications"], list)
        assert isinstance(result["allergies"], list)

    async def test_johnson_patient(self, api_client):
        """Patient 90003 (NKDA profile) returns valid summary."""
        async with api_client:
            result = await _get_patient_summary_impl(
                api_client,
                patient_id=PATIENT_ID_JOHNSON,
            )
        assert result["patient"]["id"] == PATIENT_ID_JOHNSON


# ---------------------------------------------------------------------------
# 2. Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    async def test_nonexistent_patient(self, api_client):
        """Nonexistent patient raises ToolException."""
        async with api_client:
            with pytest.raises(ToolException, match="No patient found"):
                await _get_patient_summary_impl(api_client, patient_id=999999)


# ---------------------------------------------------------------------------
# 3. Output shape
# ---------------------------------------------------------------------------


class TestOutputShape:
    async def test_top_level_keys(self, api_client):
        """Response should have all expected top-level keys."""
        async with api_client:
            result = await _get_patient_summary_impl(
                api_client,
                patient_id=PATIENT_ID_COMPLETE,
            )
        assert {
            "patient",
            "active_problems",
            "medications",
            "allergies",
            "data_warnings",
        } == set(result.keys())

    async def test_patient_shape(self, api_client):
        """Patient object has expected keys."""
        async with api_client:
            result = await _get_patient_summary_impl(
                api_client,
                patient_id=PATIENT_ID_COMPLETE,
            )
        patient = result["patient"]
        assert "id" in patient
        assert "name" in patient
        assert "dob" in patient
        assert "sex" in patient
        assert "mrn" in patient


# ---------------------------------------------------------------------------
# 4. @tool wrapper end-to-end
# ---------------------------------------------------------------------------


class TestToolWrapper:
    async def test_tool_invoke_complete(self):
        """End-to-end get_patient_summary.ainvoke for complete patient."""
        with patch("ai_agent.config.get_settings", return_value=get_settings()):
            result = await get_patient_summary.ainvoke(
                {"patient_id": PATIENT_ID_COMPLETE}
            )
        assert result["patient"]["name"] != ""
        assert isinstance(result["medications"], list)
