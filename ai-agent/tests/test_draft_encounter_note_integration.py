"""Integration tests for draft_encounter_note against a live OpenEMR instance.

Requires Docker services running with seeded data.
Run via: INTEGRATION_TEST=1 uv run pytest tests/ -m integration -v

The LLM call (ChatAnthropic) is mocked to avoid API costs in CI.
Only the encounter context fetching runs against real services.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import ToolException

from ai_agent.tools.draft_encounter_note import (
    _draft_encounter_note_impl,
    draft_encounter_note,
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


# -- helpers -------------------------------------------------------------------


def _mock_llm_soap() -> AsyncMock:
    """Return a mock LLM that produces a valid SOAP JSON response."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content=json.dumps({
            "subjective": "Patient presents for annual checkup.",
            "objective": "Vitals within normal limits.",
            "assessment": "Routine wellness visit.",
            "plan": "Continue current medications. Follow up in 1 year.",
        })
    )
    return llm


def _mock_llm_progress() -> AsyncMock:
    """Return a mock LLM that produces a valid progress note JSON response."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content=json.dumps({
            "narrative": "Patient seen for follow-up. Stable condition."
        })
    )
    return llm


def _mock_llm_brief() -> AsyncMock:
    """Return a mock LLM that produces a valid brief note JSON response."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content=json.dumps({
            "summary": "Routine annual visit. No acute concerns."
        })
    )
    return llm


def _mock_llm_malformed() -> AsyncMock:
    """Return a mock LLM that produces malformed (non-JSON) output."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content="This is not valid JSON but a free-text note."
    )
    return llm


# ---------------------------------------------------------------------------
# 1. SOAP note generation
# ---------------------------------------------------------------------------


class TestDraftSOAPNote:
    async def test_soap_complete_encounter(self, api_client):
        """SOAP note for complete encounter 900001 should include vitals info."""
        llm = _mock_llm_soap()
        async with api_client:
            result = await _draft_encounter_note_impl(
                api_client,
                llm,
                encounter_id=ENCOUNTER_COMPLETE,
                patient_id=PATIENT_ID_COMPLETE,
                note_type="SOAP",
            )
        assert result["draft_note"]["type"] == "SOAP"
        assert "subjective" in result["draft_note"]["content"]
        assert result["draft_note"]["patient_name"] != ""
        assert result["draft_note"]["encounter_id"] == ENCOUNTER_COMPLETE
        assert result["data_warnings"] == []
        # LLM was called with encounter context
        llm.ainvoke.assert_called_once()

    async def test_soap_incomplete_encounter(self, api_client):
        """SOAP note for incomplete encounter 900002 should have warnings about missing data."""
        llm = _mock_llm_soap()
        async with api_client:
            result = await _draft_encounter_note_impl(
                api_client,
                llm,
                encounter_id=ENCOUNTER_INCOMPLETE,
                patient_id=PATIENT_ID_INCOMPLETE,
                note_type="SOAP",
            )
        assert result["draft_note"]["type"] == "SOAP"
        # Incomplete encounter has no vitals, so warnings should include that
        assert any("vitals" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# 2. Progress note generation
# ---------------------------------------------------------------------------


class TestDraftProgressNote:
    async def test_progress_note(self, api_client):
        """Progress note for complete encounter."""
        llm = _mock_llm_progress()
        async with api_client:
            result = await _draft_encounter_note_impl(
                api_client,
                llm,
                encounter_id=ENCOUNTER_COMPLETE,
                patient_id=PATIENT_ID_COMPLETE,
                note_type="progress",
            )
        assert result["draft_note"]["type"] == "progress"
        assert "narrative" in result["draft_note"]["content"]
        assert result["data_warnings"] == []


# ---------------------------------------------------------------------------
# 3. Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    async def test_nonexistent_patient(self, api_client):
        """Nonexistent patient raises ToolException."""
        llm = _mock_llm_soap()
        async with api_client:
            with pytest.raises(ToolException, match="No patient found"):
                await _draft_encounter_note_impl(
                    api_client,
                    llm,
                    encounter_id=1,
                    patient_id=999999,
                )

    async def test_nonexistent_encounter(self, api_client):
        """Valid patient but nonexistent encounter raises ToolException."""
        llm = _mock_llm_soap()
        async with api_client:
            with pytest.raises(ToolException, match="No encounter found"):
                await _draft_encounter_note_impl(
                    api_client,
                    llm,
                    encounter_id=999999,
                    patient_id=PATIENT_ID_COMPLETE,
                )

    async def test_invalid_note_type_defaults_to_soap(self, api_client):
        """Invalid note_type should default to SOAP with a warning."""
        llm = _mock_llm_soap()
        async with api_client:
            result = await _draft_encounter_note_impl(
                api_client,
                llm,
                encounter_id=ENCOUNTER_COMPLETE,
                patient_id=PATIENT_ID_COMPLETE,
                note_type="invalid_type",
            )
        assert result["draft_note"]["type"] == "SOAP"
        assert any("defaulting to SOAP" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# 4. Output shape
# ---------------------------------------------------------------------------


class TestOutputShape:
    async def test_top_level_keys(self, api_client):
        """Response should have all expected top-level keys."""
        llm = _mock_llm_soap()
        async with api_client:
            result = await _draft_encounter_note_impl(
                api_client,
                llm,
                encounter_id=ENCOUNTER_COMPLETE,
                patient_id=PATIENT_ID_COMPLETE,
            )
        assert {"draft_note", "warnings", "data_warnings", "disclaimer"} == set(
            result.keys()
        )
        note = result["draft_note"]
        assert {"type", "content", "full_text", "encounter_id", "patient_name", "generated_at"} == set(
            note.keys()
        )

    async def test_data_warnings_on_malformed_llm_response(self, api_client):
        """Malformed LLM response should populate data_warnings with parse failure."""
        llm = _mock_llm_malformed()
        async with api_client:
            result = await _draft_encounter_note_impl(
                api_client,
                llm,
                encounter_id=ENCOUNTER_COMPLETE,
                patient_id=PATIENT_ID_COMPLETE,
            )
        assert any("llm_response_parse_failed" in w for w in result["data_warnings"])
        # Should still return a valid structure (fallback wrapping)
        assert "subjective" in result["draft_note"]["content"]


# ---------------------------------------------------------------------------
# 5. @tool wrapper end-to-end
# ---------------------------------------------------------------------------


class TestToolWrapper:
    async def test_tool_invoke_soap(self):
        """End-to-end draft_encounter_note.ainvoke for complete encounter."""
        from ai_agent.config import get_settings

        mock_llm = _mock_llm_soap()
        with (
            patch("ai_agent.config.get_settings", return_value=get_settings()),
            patch(
                "ai_agent.tools.draft_encounter_note.ChatAnthropic",
                return_value=mock_llm,
            ),
        ):
            result = await draft_encounter_note.ainvoke(
                {
                    "encounter_id": ENCOUNTER_COMPLETE,
                    "patient_id": PATIENT_ID_COMPLETE,
                    "note_type": "SOAP",
                }
            )
        assert result["draft_note"]["type"] == "SOAP"
        assert result["draft_note"]["patient_name"] != ""
        assert "disclaimer" in result
