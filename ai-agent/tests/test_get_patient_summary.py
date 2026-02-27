"""Unit tests for get_patient_summary tool."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.tools import ToolException

from ai_agent.tools.get_patient_summary import (
    GetPatientSummaryInput,
    _get_patient_summary_impl,
    get_patient_summary,
)
from tests.helpers import (
    make_patient,
    mock_patient_summary_client,
)

pytestmark = pytest.mark.unit


# -- fixtures ------------------------------------------------------------------

PATIENT = make_patient(pid=90001, uuid="puuid-90001")

CONDITIONS_BUNDLE = {
    "entry": [
        {
            "resource": {
                "code": {
                    "coding": [
                        {
                            "code": "E11.9",
                            "display": "Type 2 diabetes mellitus without complications",
                        }
                    ]
                },
                "onsetDateTime": "2020-06-15",
            }
        },
        {
            "resource": {
                "code": {
                    "coding": [
                        {"code": "I10", "display": "Essential (primary) hypertension"}
                    ]
                },
                "onsetDateTime": "2019-01-10",
            }
        },
    ]
}

MEDICATIONS_BUNDLE = {
    "entry": [
        {
            "resource": {
                "medicationCodeableConcept": {"coding": [{"display": "Metformin"}]},
                "dosageInstruction": [
                    {
                        "doseAndRate": [{"doseQuantity": {"value": 500, "unit": "mg"}}],
                        "timing": {"code": {"text": "twice daily"}},
                    }
                ],
            }
        },
        {
            "resource": {
                "medicationCodeableConcept": {"coding": [{"display": "Lisinopril"}]},
                "dosageInstruction": [
                    {
                        "doseAndRate": [{"doseQuantity": {"value": 10, "unit": "mg"}}],
                        "timing": {"code": {"text": "once daily"}},
                    }
                ],
            }
        },
    ]
}

ALLERGIES_BUNDLE = {
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


# -- happy path ----------------------------------------------------------------


class TestHappyPath:
    async def test_returns_patient_demographics(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            conditions_bundle=CONDITIONS_BUNDLE,
            medications_bundle=MEDICATIONS_BUNDLE,
            allergies_bundle=ALLERGIES_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["patient"]["id"] == 90001
        assert result["patient"]["name"] == "John Doe"
        assert result["patient"]["dob"] == "1980-01-15"
        assert result["patient"]["sex"] == "Male"

    async def test_returns_active_problems(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            conditions_bundle=CONDITIONS_BUNDLE,
            medications_bundle=MEDICATIONS_BUNDLE,
            allergies_bundle=ALLERGIES_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        problems = result["active_problems"]
        assert len(problems) == 2
        assert problems[0]["code"] == "E11.9"
        assert problems[1]["code"] == "I10"

    async def test_returns_medications(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            conditions_bundle=CONDITIONS_BUNDLE,
            medications_bundle=MEDICATIONS_BUNDLE,
            allergies_bundle=ALLERGIES_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        meds = result["medications"]
        assert len(meds) == 2
        assert meds[0]["drug_name"] == "Metformin"
        assert meds[1]["drug_name"] == "Lisinopril"

    async def test_returns_allergies(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            conditions_bundle=CONDITIONS_BUNDLE,
            medications_bundle=MEDICATIONS_BUNDLE,
            allergies_bundle=ALLERGIES_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        allergies = result["allergies"]
        assert len(allergies) == 1
        assert allergies[0]["substance"] == "Penicillin"
        assert allergies[0]["reaction"] == "Rash"
        assert allergies[0]["severity"] == "moderate"

    async def test_no_data_warnings_on_success(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            conditions_bundle=CONDITIONS_BUNDLE,
            medications_bundle=MEDICATIONS_BUNDLE,
            allergies_bundle=ALLERGIES_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["data_warnings"] == []

    async def test_output_keys(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            conditions_bundle=CONDITIONS_BUNDLE,
            medications_bundle=MEDICATIONS_BUNDLE,
            allergies_bundle=ALLERGIES_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert set(result.keys()) == {
            "patient",
            "active_problems",
            "medications",
            "allergies",
            "data_warnings",
        }


# -- empty lists ---------------------------------------------------------------


class TestEmptyLists:
    async def test_no_medications(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            conditions_bundle=CONDITIONS_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["medications"] == []
        assert result["active_problems"] != []

    async def test_no_allergies(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["allergies"] == []

    async def test_no_problems(self):
        client = mock_patient_summary_client(
            patients=[PATIENT],
            medications_bundle=MEDICATIONS_BUNDLE,
            allergies_bundle=ALLERGIES_BUNDLE,
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["active_problems"] == []

    async def test_all_empty(self):
        client = mock_patient_summary_client(patients=[PATIENT])
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["active_problems"] == []
        assert result["medications"] == []
        assert result["allergies"] == []
        assert result["data_warnings"] == []


# -- error paths ---------------------------------------------------------------


class TestErrorPaths:
    async def test_patient_not_found(self):
        client = mock_patient_summary_client(patients=[])
        with pytest.raises(ToolException, match="No patient found with ID 999999"):
            await _get_patient_summary_impl(client, patient_id=999999)

    async def test_patient_no_uuid(self):
        patient_no_uuid = make_patient(pid=90001, uuid="")
        client = mock_patient_summary_client(patients=[patient_no_uuid])
        with pytest.raises(ToolException, match="has no UUID"):
            await _get_patient_summary_impl(client, patient_id=90001)

    async def test_patient_wrong_pid(self):
        """API returns a patient but with wrong pid — should not match."""
        wrong_patient = make_patient(pid=99, uuid="puuid-99")
        client = mock_patient_summary_client(patients=[wrong_patient])
        with pytest.raises(ToolException, match="No patient found"):
            await _get_patient_summary_impl(client, patient_id=90001)


# -- graceful degradation (FHIR fetch failures) --------------------------------


class TestGracefulDegradation:
    async def _make_failing_client(
        self, failing_paths: set[str], error_type: str = "http"
    ) -> AsyncMock:
        """Build a client where specific FHIR paths fail."""
        client = AsyncMock()

        async def mock_get(path: str, params: dict | None = None) -> dict:
            for pattern in failing_paths:
                if pattern in path:
                    if error_type == "http":
                        resp = httpx.Response(500, request=httpx.Request("GET", path))
                        raise httpx.HTTPStatusError(
                            "Server Error", request=resp.request, response=resp
                        )
                    elif error_type == "timeout":
                        raise httpx.TimeoutException(
                            f"Timed out requesting {path}",
                            request=httpx.Request("GET", path),
                        )
                    elif error_type == "network":
                        raise httpx.ConnectError(
                            f"Connection refused: {path}",
                            request=httpx.Request("GET", path),
                        )
            if "/patient" in path:
                return {"data": [PATIENT]}
            return {"entry": []}

        client.get = AsyncMock(side_effect=mock_get)
        return client

    async def test_conditions_http_error(self):
        client = await self._make_failing_client({"/fhir/Condition"})
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["active_problems"] == []
        assert any("conditions_fetch_failed" in w for w in result["data_warnings"])
        # Other data still returned
        assert "patient" in result

    async def test_medications_http_error(self):
        client = await self._make_failing_client({"/fhir/MedicationRequest"})
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["medications"] == []
        assert any("medications_fetch_failed" in w for w in result["data_warnings"])

    async def test_allergies_http_error(self):
        client = await self._make_failing_client({"/fhir/AllergyIntolerance"})
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["allergies"] == []
        assert any("allergies_fetch_failed" in w for w in result["data_warnings"])

    async def test_conditions_timeout(self):
        client = await self._make_failing_client({"/fhir/Condition"}, "timeout")
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["active_problems"] == []
        assert any("conditions_fetch_failed" in w for w in result["data_warnings"])
        assert any("timed out" in w for w in result["data_warnings"])

    async def test_medications_timeout(self):
        client = await self._make_failing_client({"/fhir/MedicationRequest"}, "timeout")
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["medications"] == []
        assert any("medications_fetch_failed" in w for w in result["data_warnings"])

    async def test_allergies_timeout(self):
        client = await self._make_failing_client(
            {"/fhir/AllergyIntolerance"}, "timeout"
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["allergies"] == []
        assert any("allergies_fetch_failed" in w for w in result["data_warnings"])

    async def test_conditions_network_error(self):
        client = await self._make_failing_client({"/fhir/Condition"}, "network")
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["active_problems"] == []
        assert any("conditions_fetch_failed" in w for w in result["data_warnings"])
        assert any("network error" in w for w in result["data_warnings"])

    async def test_medications_network_error(self):
        client = await self._make_failing_client({"/fhir/MedicationRequest"}, "network")
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["medications"] == []
        assert any("medications_fetch_failed" in w for w in result["data_warnings"])

    async def test_allergies_network_error(self):
        client = await self._make_failing_client(
            {"/fhir/AllergyIntolerance"}, "network"
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["allergies"] == []
        assert any("allergies_fetch_failed" in w for w in result["data_warnings"])

    async def test_multiple_fetches_fail(self):
        client = await self._make_failing_client(
            {"/fhir/Condition", "/fhir/MedicationRequest"}
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["active_problems"] == []
        assert result["medications"] == []
        assert len(result["data_warnings"]) == 2
        # Allergies still returned
        assert isinstance(result["allergies"], list)

    async def test_all_fetches_fail(self):
        client = await self._make_failing_client(
            {"/fhir/Condition", "/fhir/MedicationRequest", "/fhir/AllergyIntolerance"}
        )
        result = await _get_patient_summary_impl(client, patient_id=90001)
        assert result["active_problems"] == []
        assert result["medications"] == []
        assert result["allergies"] == []
        assert len(result["data_warnings"]) == 3
        # Patient info still returned
        assert result["patient"]["id"] == 90001


# -- input schema validation ---------------------------------------------------


class TestInputSchema:
    def test_valid_patient_id(self):
        inp = GetPatientSummaryInput(patient_id=90001)
        assert inp.patient_id == 90001

    def test_patient_id_required(self):
        with pytest.raises(Exception):
            GetPatientSummaryInput()

    def test_patient_id_must_be_int(self):
        with pytest.raises(Exception):
            GetPatientSummaryInput(patient_id="not_an_int")


# -- @tool wrapper -------------------------------------------------------------


class TestToolWrapper:
    async def test_tool_name(self):
        assert get_patient_summary.name == "get_patient_summary"

    async def test_tool_has_description(self):
        assert "patient overview" in get_patient_summary.description.lower()
