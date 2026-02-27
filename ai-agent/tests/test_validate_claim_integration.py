"""Integration tests for validate_claim_completeness against Docker services.

Requires Docker services running with seeded data.
Run via: INTEGRATION_TEST=1 uv run pytest tests/ -m integration
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from langchain_core.tools import ToolException

from ai_agent.config import get_settings
from ai_agent.server import app
from ai_agent.tools.validate_claim_completeness import (
    _validate_claim_impl,
    validate_claim_ready_completeness,
)
from tests.helpers import find_patient_uuid
from tests.integration.config import (
    ENCOUNTER_COMPLETE,
    ENCOUNTER_INCOMPLETE,
    PATIENT_ID_COMPLETE,
    PATIENT_ID_INCOMPLETE,
)
from tests.integration.factories import (
    clear_insurance_for_patient,
    ensure_insurance_for_patient,
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ensure_claim_insurance_state(db_conn, db_cleanup):
    """Prepare deterministic insurance state for claim tests.

    - patient 90001 must have primary insurance
    - patient 90002 must have no insurance
    """
    db_cleanup(ensure_insurance_for_patient(db_conn, PATIENT_ID_COMPLETE))

    saved_rows = clear_insurance_for_patient(db_conn, PATIENT_ID_INCOMPLETE)
    if saved_rows:

        def _restore_deleted_rows() -> None:
            cur = db_conn.cursor()
            for row in saved_rows:
                restored = dict(row)
                restored.pop("id", None)
                cols = ", ".join(restored.keys())
                placeholders = ", ".join(["%s"] * len(restored))
                cur.execute(
                    f"INSERT INTO insurance_data ({cols}) VALUES ({placeholders})",
                    list(restored.values()),
                )
            db_conn.commit()
            cur.close()

        db_cleanup(_restore_deleted_rows)


async def _fetch_billing_via_endpoint(
    encounter_id: int,
    patient_id: int,
    settings_override=None,
) -> list[dict[str, Any]]:
    """Fetch billing rows via the /internal/billing ASGI endpoint.

    Uses the current ``get_settings()`` values (set by ``integration_env``)
    unless an explicit ``settings_override`` is provided for negative tests.
    """
    settings = settings_override or get_settings()
    with patch("ai_agent.server.get_settings", return_value=settings):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get(
                "/internal/billing",
                params={"encounter_id": encounter_id, "patient_id": patient_id},
            )
            resp.raise_for_status()
            return resp.json().get("data", [])


# ---------------------------------------------------------------------------
# 1. /internal/billing endpoint against real MySQL
# ---------------------------------------------------------------------------


class TestInternalBillingEndpoint:
    """Tests for the /internal/billing HTTP endpoint against the real database."""

    async def test_returns_data_for_known_encounter(self):
        """Billing rows for encounter 900001 should include ICD and CPT codes."""
        rows = await _fetch_billing_via_endpoint(
            encounter_id=ENCOUNTER_COMPLETE,
            patient_id=PATIENT_ID_COMPLETE,
        )
        assert isinstance(rows, list)
        assert len(rows) > 0

        # Verify expected column names
        expected_cols = {"code_type", "code", "code_text", "fee", "modifier", "units"}
        assert expected_cols.issubset(set(rows[0].keys()))

        # Should contain both ICD10 and CPT4 rows
        code_types = {row["code_type"] for row in rows}
        assert "ICD10" in code_types
        assert "CPT4" in code_types

    async def test_empty_for_nonexistent_encounter(self):
        """Querying a nonexistent encounter returns an empty list."""
        rows = await _fetch_billing_via_endpoint(
            encounter_id=999999,
            patient_id=999999,
        )
        assert isinstance(rows, list)
        assert len(rows) == 0

    async def test_filters_inactive_rows(self, db_conn, billing_factory):
        """Rows with activity=0 should be excluded from results."""
        billing_factory(
            encounter_id=ENCOUNTER_COMPLETE,
            patient_id=PATIENT_ID_COMPLETE,
            code_type="CPT4",
            code="99999",
            code_text="INACTIVE TEST",
            fee=0.00,
            modifier="",
            units=1,
            activity=0,
        )

        rows = await _fetch_billing_via_endpoint(
            encounter_id=ENCOUNTER_COMPLETE,
            patient_id=PATIENT_ID_COMPLETE,
        )
        inactive_codes = [r for r in rows if r["code"] == "99999"]
        assert inactive_codes == [], "Inactive rows should be filtered out"

    async def test_bad_db_credentials_returns_502(self):
        """Bad DB credentials should return HTTP 502."""
        settings = get_settings().model_copy(
            update={"db_user": "bad_user", "db_password": "bad_pass"}
        )

        with patch("ai_agent.server.get_settings", return_value=settings):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/internal/billing",
                    params={
                        "encounter_id": ENCOUNTER_COMPLETE,
                        "patient_id": PATIENT_ID_COMPLETE,
                    },
                )
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# 2. Insurance API via OpenEMRClient
# ---------------------------------------------------------------------------


class TestInsuranceAPI:
    """Tests for insurance data fetched via the OpenEMR REST API."""

    async def test_returns_policies_for_insured_patient(
        self, api_client, ensure_claim_insurance_state
    ):
        """Patient 90001 should have primary insurance via the API."""
        async with api_client:
            # Resolve patient UUID (API may return all patients)
            patient_resp = await api_client.get(
                "/apis/default/api/patient", params={"pid": PATIENT_ID_COMPLETE}
            )
            patients = patient_resp.get("data", patient_resp)
            puuid = find_patient_uuid(patients, PATIENT_ID_COMPLETE)

            # Fetch insurance
            ins_resp = await api_client.get(
                f"/apis/default/api/patient/{puuid}/insurance"
            )
            ins_data = ins_resp.get("data", ins_resp)
            assert isinstance(ins_data, list)
            assert len(ins_data) > 0

            # Verify primary insurance exists
            types = [ins.get("type", "").lower() for ins in ins_data]
            assert "primary" in types

    async def test_empty_for_uninsured_patient(
        self, api_client, ensure_claim_insurance_state
    ):
        """Patient 90002 should have no insurance policies."""
        async with api_client:
            patient_resp = await api_client.get(
                "/apis/default/api/patient", params={"pid": PATIENT_ID_INCOMPLETE}
            )
            patients = patient_resp.get("data", patient_resp)
            puuid = find_patient_uuid(patients, PATIENT_ID_INCOMPLETE)

            ins_resp = await api_client.get(
                f"/apis/default/api/patient/{puuid}/insurance"
            )
            ins_data = ins_resp.get("data", ins_resp)
            assert isinstance(ins_data, list)
            assert len(ins_data) == 0


# ---------------------------------------------------------------------------
# 3. Full _validate_claim_impl against real API
# ---------------------------------------------------------------------------


class TestValidateClaimImpl:
    """End-to-end tests for _validate_claim_impl with real API calls."""

    async def test_complete_encounter_is_ready(
        self, api_client, ensure_claim_insurance_state
    ):
        """Encounter 900001 with billing + insurance -> ready=True."""
        billing_rows = await _fetch_billing_via_endpoint(
            encounter_id=ENCOUNTER_COMPLETE,
            patient_id=PATIENT_ID_COMPLETE,
        )
        assert len(billing_rows) > 0

        # Fetch insurance via the api_client fixture
        async with api_client:
            patient_resp = await api_client.get(
                "/apis/default/api/patient", params={"pid": PATIENT_ID_COMPLETE}
            )
            puuid = find_patient_uuid(patient_resp.get("data", []), PATIENT_ID_COMPLETE)
            ins_resp = await api_client.get(
                f"/apis/default/api/patient/{puuid}/insurance"
            )
            insurance_list = ins_resp.get("data", [])

            result = await _validate_claim_impl(
                api_client,
                patient_id=PATIENT_ID_COMPLETE,
                encounter_id=ENCOUNTER_COMPLETE,
                billing_rows=billing_rows,
                insurance_list=insurance_list,
            )

        assert result["encounter_id"] == ENCOUNTER_COMPLETE
        assert result["ready"] is True
        assert result["errors"] == []
        assert "dx_codes" in result["summary"]
        assert "cpt_codes" in result["summary"]
        assert len(result["summary"]["dx_codes"]) > 0
        assert len(result["summary"]["cpt_codes"]) > 0
        assert "data_warnings" in result

    async def test_incomplete_encounter_not_ready(self, api_client):
        """Encounter 900002 with CPT only (no ICD) -> ready=False."""
        billing_rows = await _fetch_billing_via_endpoint(
            encounter_id=ENCOUNTER_INCOMPLETE,
            patient_id=PATIENT_ID_INCOMPLETE,
        )

        async with api_client:
            result = await _validate_claim_impl(
                api_client,
                patient_id=PATIENT_ID_INCOMPLETE,
                encounter_id=ENCOUNTER_INCOMPLETE,
                billing_rows=billing_rows,
                insurance_list=[],
            )

        assert result["encounter_id"] == ENCOUNTER_INCOMPLETE
        assert result["ready"] is False
        error_checks = {e["check"] for e in result["errors"]}
        assert "diagnosis_codes" in error_checks

        # Insurance missing is a warning
        warning_checks = {w["check"] for w in result["warnings"]}
        assert "insurance" in warning_checks

    async def test_nonexistent_patient_raises(self, api_client):
        """Nonexistent patient -> ToolException."""
        async with api_client:
            with pytest.raises(ToolException, match="No patient found"):
                await _validate_claim_impl(
                    api_client,
                    patient_id=999999,
                    encounter_id=1,
                    billing_rows=[],
                    insurance_list=[],
                )

    async def test_nonexistent_encounter_raises(self, api_client):
        """Valid patient but nonexistent encounter -> ToolException."""
        async with api_client:
            with pytest.raises(ToolException, match="No encounter found"):
                await _validate_claim_impl(
                    api_client,
                    patient_id=PATIENT_ID_COMPLETE,
                    encounter_id=999999,
                    billing_rows=[],
                    insurance_list=[],
                )


# ---------------------------------------------------------------------------
# 4. Full @tool wrapper end-to-end
# ---------------------------------------------------------------------------


class TestToolWrapper:
    """Tests for the validate_claim_ready_completeness @tool wrapper."""

    async def test_full_tool_complete_encounter(self, ensure_claim_insurance_state):
        """End-to-end @tool call for a complete encounter."""
        result = await validate_claim_ready_completeness.ainvoke(
            {"encounter_id": ENCOUNTER_COMPLETE, "patient_id": PATIENT_ID_COMPLETE}
        )

        assert result["encounter_id"] == ENCOUNTER_COMPLETE
        assert result["ready"] is True
        assert result["errors"] == []
        assert "summary" in result
        assert "data_warnings" in result

    async def test_full_tool_incomplete_encounter(self):
        """End-to-end @tool call for an incomplete encounter."""
        result = await validate_claim_ready_completeness.ainvoke(
            {
                "encounter_id": ENCOUNTER_INCOMPLETE,
                "patient_id": PATIENT_ID_INCOMPLETE,
            }
        )

        assert result["encounter_id"] == ENCOUNTER_INCOMPLETE
        assert result["ready"] is False
        error_checks = {e["check"] for e in result["errors"]}
        assert "diagnosis_codes" in error_checks
        assert "data_warnings" in result

    async def test_tool_wrapper_handles_billing_fetch_error(self):
        """Unreachable billing endpoint -> graceful degradation, not crash."""
        settings = get_settings().model_copy(
            update={"agent_base_url": "http://localhost:1"}
        )

        with patch("ai_agent.config.get_settings", return_value=settings):
            # The tool should still work — just with empty billing rows
            result = await validate_claim_ready_completeness.ainvoke(
                {
                    "encounter_id": ENCOUNTER_COMPLETE,
                    "patient_id": PATIENT_ID_COMPLETE,
                }
            )

        # With no billing data, dx and cpt checks should fail
        assert result["ready"] is False
        error_checks = {e["check"] for e in result["errors"]}
        assert "diagnosis_codes" in error_checks
        assert "procedure_codes" in error_checks
        assert any("billing_fetch_failed" in w for w in result["data_warnings"])
