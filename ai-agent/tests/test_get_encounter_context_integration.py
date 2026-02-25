"""Integration tests for get_encounter_context against a live OpenEMR instance.

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
from ai_agent.tools.get_encounter_context import (
    _get_encounter_context_impl,
    get_encounter_context,
)
from tests.integration.config import (
    ENCOUNTER_COMPLETE,
    ENCOUNTER_INCOMPLETE,
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
# 1. Encounter by ID
# ---------------------------------------------------------------------------


class TestEncounterById:
    async def test_complete_encounter(self, api_client):
        """Complete encounter 900001 should have vitals and SOAP notes."""
        async with api_client:
            result = await _get_encounter_context_impl(
                api_client,
                patient_id=PATIENT_ID_COMPLETE,
                encounter_id=ENCOUNTER_COMPLETE,
            )
        assert result["patient"]["name"] != ""
        vitals = result["clinical_context"]["vitals"]
        assert vitals is not None
        assert vitals.get("bp", "") != ""
        notes = result["clinical_context"]["existing_notes"]
        assert len(notes) >= 1
        assert result["data_warnings"] == []

    async def test_incomplete_encounter(self, api_client):
        """Incomplete encounter 900002 should have no vitals and no notes."""
        async with api_client:
            result = await _get_encounter_context_impl(
                api_client,
                patient_id=PATIENT_ID_INCOMPLETE,
                encounter_id=ENCOUNTER_INCOMPLETE,
            )
        assert result["clinical_context"]["vitals"] is None
        assert result["clinical_context"]["existing_notes"] == []


# ---------------------------------------------------------------------------
# 2. Encounter by date
# ---------------------------------------------------------------------------


class TestEncounterByDate:
    async def test_find_by_today(self, api_client):
        """Find encounter by today's date for patient 90002."""
        today = date.today().isoformat()
        async with api_client:
            result = await _get_encounter_context_impl(
                api_client,
                patient_id=PATIENT_ID_INCOMPLETE,
                date=today,
            )
        # Should return the encounter for today
        assert "encounter" in result
        assert result["encounter"]["id"] == ENCOUNTER_INCOMPLETE
        assert result["encounter"]["date"].startswith(today)


# ---------------------------------------------------------------------------
# 3. Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    async def test_nonexistent_patient(self, api_client):
        """Nonexistent patient raises ToolException."""
        async with api_client:
            with pytest.raises(ToolException, match="No patient found"):
                await _get_encounter_context_impl(
                    api_client, patient_id=999999, encounter_id=1
                )

    async def test_nonexistent_encounter(self, api_client):
        """Valid patient but nonexistent encounter raises ToolException."""
        async with api_client:
            with pytest.raises(ToolException, match="No encounter found"):
                await _get_encounter_context_impl(
                    api_client,
                    patient_id=PATIENT_ID_COMPLETE,
                    encounter_id=999999,
                )

    async def test_no_encounters_on_future_date(self, api_client):
        """No encounters on a far future date raises ToolException."""
        async with api_client:
            with pytest.raises(ToolException, match="No encounters found"):
                await _get_encounter_context_impl(
                    api_client,
                    patient_id=PATIENT_ID_COMPLETE,
                    date="2099-12-31",
                )


# ---------------------------------------------------------------------------
# 4. Output shape
# ---------------------------------------------------------------------------


class TestOutputShape:
    async def test_top_level_keys(self, api_client):
        """Response should have all expected top-level keys."""
        async with api_client:
            result = await _get_encounter_context_impl(
                api_client,
                patient_id=PATIENT_ID_COMPLETE,
                encounter_id=ENCOUNTER_COMPLETE,
            )
        assert {"encounter", "patient", "clinical_context", "billing_status", "data_warnings"} == set(
            result.keys()
        )
        clinical = result["clinical_context"]
        assert {"active_problems", "medications", "allergies", "vitals", "existing_notes"} == set(
            clinical.keys()
        )


# ---------------------------------------------------------------------------
# 5. @tool wrapper end-to-end
# ---------------------------------------------------------------------------


class TestToolWrapper:
    async def test_tool_invoke_complete(self):
        """End-to-end get_encounter_context.ainvoke for complete encounter."""
        with patch("ai_agent.config.get_settings", return_value=get_settings()):
            result = await get_encounter_context.ainvoke(
                {
                    "patient_id": PATIENT_ID_COMPLETE,
                    "encounter_id": ENCOUNTER_COMPLETE,
                }
            )
        assert result["patient"]["name"] != ""
        assert result["encounter"]["id"] is not None
