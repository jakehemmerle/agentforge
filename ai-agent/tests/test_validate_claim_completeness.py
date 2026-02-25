"""Tests for the validate_claim_completeness tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.tools import ToolException

from ai_agent.tools.validate_claim_completeness import (
    ValidateClaimInput,
    _check_billing_facility,
    _check_demographics,
    _check_diagnosis_codes,
    _check_insurance,
    _check_procedure_codes,
    _check_rendering_provider,
    _validate_claim_impl,
    validate_claim_ready_completeness,
)
from tests.helpers import make_encounter, make_patient

pytestmark = pytest.mark.unit


# -- helpers -------------------------------------------------------------------


def _make_billing_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "code_type": "CPT4",
        "code": "99213",
        "code_text": "Office visit, est patient, low complexity",
        "fee": 75.00,
        "modifier": "",
        "units": 1,
    }
    base.update(overrides)
    return base


def _make_dx_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "code_type": "ICD10",
        "code": "J06.9",
        "code_text": "Acute upper respiratory infection",
        "fee": 0.00,
        "modifier": "",
        "units": 1,
    }
    base.update(overrides)
    return base


def _make_insurance(**overrides: Any) -> dict[str, Any]:
    base = {
        "type": "primary",
        "provider": "1",
        "policy_number": "POL12345",
        "group_number": "GRP001",
        "subscriber_lname": "Doe",
        "subscriber_fname": "John",
        "subscriber_DOB": "1980-01-15",
        "date": "2025-01-01",
        "date_end": None,
    }
    base.update(overrides)
    return base


# -- individual check tests: diagnosis codes -----------------------------------


def test_check_diagnosis_codes_present():
    rows = [_make_dx_row()]
    errors, dx_codes = _check_diagnosis_codes(rows)
    assert errors == []
    assert dx_codes == ["J06.9"]


def test_check_diagnosis_codes_multiple():
    rows = [
        _make_dx_row(code="J06.9"),
        _make_dx_row(code="E11.9", code_text="Type 2 diabetes"),
    ]
    errors, dx_codes = _check_diagnosis_codes(rows)
    assert errors == []
    assert dx_codes == ["J06.9", "E11.9"]


def test_check_diagnosis_codes_icd10_cm_variant():
    rows = [_make_dx_row(code_type="ICD-10-CM")]
    errors, dx_codes = _check_diagnosis_codes(rows)
    assert errors == []
    assert dx_codes == ["J06.9"]


def test_check_diagnosis_codes_missing():
    errors, dx_codes = _check_diagnosis_codes([])
    assert len(errors) == 1
    assert errors[0]["check"] == "diagnosis_codes"
    assert errors[0]["severity"] == "error"
    assert "Missing diagnosis codes" in errors[0]["message"]
    assert dx_codes == []


def test_check_diagnosis_codes_only_cpt_no_dx():
    rows = [_make_billing_row()]
    errors, dx_codes = _check_diagnosis_codes(rows)
    assert len(errors) == 1
    assert dx_codes == []


# -- individual check tests: procedure codes -----------------------------------


def test_check_procedure_codes_present():
    rows = [_make_billing_row(fee=75.00)]
    errors, warnings, cpt_codes, total = _check_procedure_codes(rows)
    assert errors == []
    assert warnings == []
    assert cpt_codes == ["99213"]
    assert total == 75.00


def test_check_procedure_codes_multiple():
    rows = [
        _make_billing_row(code="99213", fee=75.00),
        _make_billing_row(code="85025", fee=15.00, code_text="CBC"),
    ]
    errors, warnings, cpt_codes, total = _check_procedure_codes(rows)
    assert errors == []
    assert cpt_codes == ["99213", "85025"]
    assert total == 90.00


def test_check_procedure_codes_hcpcs():
    rows = [_make_billing_row(code_type="HCPCS", code="G0101", fee=50.00)]
    errors, warnings, cpt_codes, total = _check_procedure_codes(rows)
    assert errors == []
    assert cpt_codes == ["G0101"]
    assert total == 50.00


def test_check_procedure_codes_missing():
    errors, warnings, cpt_codes, total = _check_procedure_codes([])
    assert len(errors) == 1
    assert errors[0]["check"] == "procedure_codes"
    assert errors[0]["severity"] == "error"
    assert cpt_codes == []
    assert total == 0.0


def test_check_procedure_codes_zero_fee_warning():
    rows = [_make_billing_row(fee=0)]
    errors, warnings, cpt_codes, total = _check_procedure_codes(rows)
    assert errors == []
    assert len(warnings) == 1
    assert warnings[0]["check"] == "fees"
    assert warnings[0]["severity"] == "warning"
    assert "99213" in warnings[0]["message"]
    assert total == 0.0


def test_check_procedure_codes_none_fee_warning():
    rows = [_make_billing_row(fee=None)]
    errors, warnings, cpt_codes, total = _check_procedure_codes(rows)
    assert len(warnings) == 1
    assert "no fee assigned" in warnings[0]["message"]


def test_check_procedure_codes_mixed_fees():
    rows = [
        _make_billing_row(code="99213", fee=75.00),
        _make_billing_row(code="85025", fee=0),
    ]
    errors, warnings, cpt_codes, total = _check_procedure_codes(rows)
    assert errors == []
    assert len(warnings) == 1
    assert "85025" in warnings[0]["message"]
    assert total == 75.00


# -- individual check tests: rendering provider --------------------------------


def test_check_rendering_provider_present():
    enc = make_encounter(provider_id=1)
    errors, name = _check_rendering_provider(enc)
    assert errors == []
    assert name == "Provider #1"


def test_check_rendering_provider_missing():
    enc = make_encounter(provider_id=None)
    errors, name = _check_rendering_provider(enc)
    assert len(errors) == 1
    assert errors[0]["check"] == "rendering_provider"
    assert name == ""


def test_check_rendering_provider_zero():
    enc = make_encounter(provider_id=0)
    errors, name = _check_rendering_provider(enc)
    assert len(errors) == 1
    assert name == ""


def test_check_rendering_provider_string_zero():
    enc = make_encounter(provider_id="0")
    errors, name = _check_rendering_provider(enc)
    assert len(errors) == 1


# -- individual check tests: billing facility ----------------------------------


def test_check_billing_facility_present():
    enc = make_encounter(billing_facility=3, billing_facility_name="Main Clinic")
    errors, name = _check_billing_facility(enc)
    assert errors == []
    assert name == "Main Clinic"


def test_check_billing_facility_fallback_to_facility():
    enc = make_encounter(billing_facility=3, billing_facility_name="", facility="Fallback Clinic")
    errors, name = _check_billing_facility(enc)
    assert errors == []
    assert name == "Fallback Clinic"


def test_check_billing_facility_missing():
    enc = make_encounter(billing_facility=None)
    errors, name = _check_billing_facility(enc)
    assert len(errors) == 1
    assert errors[0]["check"] == "billing_facility"
    assert name == ""


def test_check_billing_facility_zero():
    enc = make_encounter(billing_facility=0)
    errors, name = _check_billing_facility(enc)
    assert len(errors) == 1
    assert name == ""


# -- individual check tests: demographics -------------------------------------


def test_check_demographics_complete():
    patient = make_patient()
    errors = _check_demographics(patient)
    assert errors == []


def test_check_demographics_missing_fields():
    patient = make_patient(street="", city="", postal_code="")
    errors = _check_demographics(patient)
    assert len(errors) == 1
    assert errors[0]["check"] == "patient_demographics"
    assert "street address" in errors[0]["message"]
    assert "city" in errors[0]["message"]
    assert "zip code" in errors[0]["message"]


def test_check_demographics_missing_all():
    patient = {
        "pid": 10, "uuid": "patient-uuid-1234", "pubpid": "MRN001",
    }
    errors = _check_demographics(patient)
    assert len(errors) == 1
    assert "first name" in errors[0]["message"]
    assert "last name" in errors[0]["message"]
    assert "date of birth" in errors[0]["message"]
    assert "sex" in errors[0]["message"]


def test_check_demographics_none_values():
    patient = make_patient(fname=None, DOB=None)
    errors = _check_demographics(patient)
    assert len(errors) == 1
    assert "first name" in errors[0]["message"]
    assert "date of birth" in errors[0]["message"]


def test_check_demographics_whitespace_only():
    patient = make_patient(street="   ", city="\t")
    errors = _check_demographics(patient)
    assert len(errors) == 1
    assert "street address" in errors[0]["message"]
    assert "city" in errors[0]["message"]


# -- individual check tests: insurance ----------------------------------------


def test_check_insurance_primary_present():
    insurance = [_make_insurance(type="primary")]
    warnings = _check_insurance(insurance)
    assert warnings == []


def test_check_insurance_case_insensitive():
    insurance = [_make_insurance(type="PRIMARY")]
    warnings = _check_insurance(insurance)
    assert warnings == []


def test_check_insurance_no_primary():
    insurance = [_make_insurance(type="secondary")]
    warnings = _check_insurance(insurance)
    assert len(warnings) == 1
    assert warnings[0]["check"] == "insurance"
    assert warnings[0]["severity"] == "warning"
    assert "self-pay" in warnings[0]["message"]


def test_check_insurance_empty():
    warnings = _check_insurance([])
    assert len(warnings) == 1


def test_check_insurance_multiple_with_primary():
    insurance = [
        _make_insurance(type="primary"),
        _make_insurance(type="secondary"),
    ]
    warnings = _check_insurance(insurance)
    assert warnings == []


# -- full implementation: happy path -------------------------------------------


async def test_validate_all_pass(mock_claim_client):
    """Complete encounter with all data → ready=true, no errors."""
    patient = make_patient()
    encounter = make_encounter()
    billing_rows = [_make_dx_row(), _make_billing_row(fee=75.00)]
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client,
        patient_id=10,
        encounter_id=5,
        billing_rows=billing_rows,
        insurance_list=insurance,
    )

    assert result["encounter_id"] == 5
    assert result["ready"] is True
    assert result["errors"] == []
    assert result["warnings"] == []
    assert result["summary"]["dx_codes"] == ["J06.9"]
    assert result["summary"]["cpt_codes"] == ["99213"]
    assert result["summary"]["provider"] == "Provider #1"
    assert result["summary"]["facility"] == "Main Clinic"
    assert result["summary"]["total_charges"] == 75.00


# -- full implementation: error cases ------------------------------------------


async def test_validate_missing_dx_codes(mock_claim_client):
    patient = make_patient()
    encounter = make_encounter()
    billing_rows = [_make_billing_row()]  # CPT only, no ICD
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )

    assert result["ready"] is False
    checks = [e["check"] for e in result["errors"]]
    assert "diagnosis_codes" in checks


async def test_validate_missing_cpt_codes(mock_claim_client):
    patient = make_patient()
    encounter = make_encounter()
    billing_rows = [_make_dx_row()]  # ICD only, no CPT
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )

    assert result["ready"] is False
    checks = [e["check"] for e in result["errors"]]
    assert "procedure_codes" in checks


async def test_validate_missing_provider(mock_claim_client):
    patient = make_patient()
    encounter = make_encounter(provider_id=0)
    billing_rows = [_make_dx_row(), _make_billing_row()]
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )

    assert result["ready"] is False
    checks = [e["check"] for e in result["errors"]]
    assert "rendering_provider" in checks
    assert result["summary"]["provider"] == ""


async def test_validate_missing_billing_facility(mock_claim_client):
    patient = make_patient()
    encounter = make_encounter(billing_facility=0)
    billing_rows = [_make_dx_row(), _make_billing_row()]
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )

    assert result["ready"] is False
    checks = [e["check"] for e in result["errors"]]
    assert "billing_facility" in checks
    assert result["summary"]["facility"] == ""


async def test_validate_incomplete_demographics(mock_claim_client):
    patient = make_patient(street="", postal_code="")
    encounter = make_encounter()
    billing_rows = [_make_dx_row(), _make_billing_row()]
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )

    assert result["ready"] is False
    checks = [e["check"] for e in result["errors"]]
    assert "patient_demographics" in checks
    demo_error = next(e for e in result["errors"] if e["check"] == "patient_demographics")
    assert "street address" in demo_error["message"]
    assert "zip code" in demo_error["message"]


async def test_validate_no_insurance_is_warning(mock_claim_client):
    """Missing insurance is a warning, not an error — ready can still be true."""
    patient = make_patient()
    encounter = make_encounter()
    billing_rows = [_make_dx_row(), _make_billing_row()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=[],
    )

    assert result["ready"] is True
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["check"] == "insurance"


async def test_validate_zero_fee_is_warning(mock_claim_client):
    """CPT code with $0 fee is a warning, not an error."""
    patient = make_patient()
    encounter = make_encounter()
    billing_rows = [_make_dx_row(), _make_billing_row(fee=0)]
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )

    assert result["ready"] is True
    fee_warnings = [w for w in result["warnings"] if w["check"] == "fees"]
    assert len(fee_warnings) == 1
    assert "99213" in fee_warnings[0]["message"]


async def test_validate_no_billing_data(mock_claim_client):
    """No billing rows at all → errors for both dx and CPT codes."""
    patient = make_patient()
    encounter = make_encounter()

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=[], insurance_list=[_make_insurance()],
    )

    assert result["ready"] is False
    checks = [e["check"] for e in result["errors"]]
    assert "diagnosis_codes" in checks
    assert "procedure_codes" in checks
    assert result["summary"]["dx_codes"] == []
    assert result["summary"]["cpt_codes"] == []
    assert result["summary"]["total_charges"] == 0.0


async def test_validate_all_failures(mock_claim_client):
    """Every check fails → all errors and warnings present."""
    patient = make_patient(fname="", street="", city="", state="", postal_code="")
    encounter = make_encounter(provider_id=0, billing_facility=0)

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=[], insurance_list=[],
    )

    assert result["ready"] is False
    error_checks = {e["check"] for e in result["errors"]}
    assert "diagnosis_codes" in error_checks
    assert "procedure_codes" in error_checks
    assert "rendering_provider" in error_checks
    assert "billing_facility" in error_checks
    assert "patient_demographics" in error_checks

    warning_checks = {w["check"] for w in result["warnings"]}
    assert "insurance" in warning_checks


# -- error paths: patient / encounter not found --------------------------------


async def test_patient_not_found(mock_claim_client):
    client = mock_claim_client(patients=[])

    with pytest.raises(ToolException, match="No patient found with ID 99"):
        await _validate_claim_impl(
            client, patient_id=99, encounter_id=1,
            billing_rows=[], insurance_list=[],
        )


async def test_patient_no_uuid(mock_claim_client):
    patient = make_patient(uuid="")
    client = mock_claim_client(patients=[patient])

    with pytest.raises(ToolException, match="Patient 10 has no UUID"):
        await _validate_claim_impl(
            client, patient_id=10, encounter_id=5,
            billing_rows=[], insurance_list=[],
        )


async def test_encounter_not_found(mock_claim_client):
    patient = make_patient()
    client = mock_claim_client(patients=[patient], encounters=[])

    with pytest.raises(ToolException, match="No encounter found with ID 999"):
        await _validate_claim_impl(
            client, patient_id=10, encounter_id=999,
            billing_rows=[], insurance_list=[],
        )


async def test_encounter_string_id_match(mock_claim_client):
    """OpenEMR API may return IDs as strings — must still match int encounter_id."""
    patient = make_patient()
    encounter = make_encounter(id="5")
    billing_rows = [_make_dx_row(), _make_billing_row()]
    insurance = [_make_insurance()]

    client = mock_claim_client(patients=[patient], encounters=[encounter])

    result = await _validate_claim_impl(
        client, patient_id=10, encounter_id=5,
        billing_rows=billing_rows, insurance_list=insurance,
    )

    assert result["encounter_id"] == 5
    assert result["ready"] is True


# -- input schema validation --------------------------------------------------


def test_input_schema_valid():
    inp = ValidateClaimInput(encounter_id=5, patient_id=10)
    assert inp.encounter_id == 5
    assert inp.patient_id == 10


def test_input_schema_missing_encounter_id():
    with pytest.raises(Exception):
        ValidateClaimInput(patient_id=10)


def test_input_schema_missing_patient_id():
    with pytest.raises(Exception):
        ValidateClaimInput(encounter_id=5)


# -- wrapper unit tests -------------------------------------------------------


async def test_wrapper_fetches_billing_via_http_and_delegates(mock_claim_client):
    """The @tool wrapper fetches billing via internal HTTP endpoint and delegates to _impl."""
    from unittest.mock import patch, AsyncMock as AM

    billing_rows = [
        {"code_type": "ICD10", "code": "J06.9", "code_text": "URI", "fee": 0, "modifier": "", "units": 1},
        {"code_type": "CPT4", "code": "99213", "code_text": "Office visit", "fee": 75.0, "modifier": "", "units": 1},
    ]

    mock_settings = AM()
    mock_settings.agent_base_url = "http://localhost:8000"

    patient = make_patient()
    encounter = make_encounter()
    insurance = [{"type": "primary", "provider": "1", "policy_number": "POL1"}]

    # Build a client mock that handles both insurance pre-fetch and _impl calls
    client_mock = AsyncMock()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        if "/insurance" in path:
            return {"data": insurance}
        if "/encounter" in path:
            return {"data": [encounter]}
        if "/patient" in path:
            return {"data": [patient]}
        return {"data": []}

    client_mock.get = AsyncMock(side_effect=mock_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    # Mock the httpx.AsyncClient for the billing endpoint call
    billing_response = MagicMock()
    billing_response.status_code = 200
    billing_response.raise_for_status = MagicMock()
    billing_response.json.return_value = {"data": billing_rows}

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=billing_response)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("ai_agent.tools.validate_claim_completeness.httpx.AsyncClient", return_value=mock_http_client),
        patch("ai_agent.tools.validate_claim_completeness.OpenEMRClient") as MockClient,
        patch("ai_agent.config.get_settings", return_value=mock_settings),
    ):
        MockClient.from_settings.return_value = client_mock
        result = await validate_claim_ready_completeness.ainvoke(
            {"encounter_id": 5, "patient_id": 10}
        )

    assert result["ready"] is True
    mock_http_client.get.assert_called_once()


async def test_wrapper_graceful_on_billing_http_error():
    """Billing endpoint returns HTTP error → billing_rows=[] → dx and cpt errors, not a crash."""
    from unittest.mock import patch, AsyncMock as AM

    mock_settings = AM()
    mock_settings.agent_base_url = "http://localhost:8000"

    patient = make_patient()
    encounter = make_encounter()

    client_mock = AsyncMock()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        if "/insurance" in path:
            return {"data": [{"type": "primary", "provider": "1"}]}
        if "/encounter" in path:
            return {"data": [encounter]}
        if "/patient" in path:
            return {"data": [patient]}
        return {"data": []}

    client_mock.get = AsyncMock(side_effect=mock_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    # Mock httpx.AsyncClient to raise HTTPStatusError for billing endpoint
    billing_response = httpx.Response(502, request=httpx.Request("GET", "http://localhost:8000/internal/billing"))
    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("Bad Gateway", request=billing_response.request, response=billing_response)
    )
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("ai_agent.tools.validate_claim_completeness.httpx.AsyncClient", return_value=mock_http_client),
        patch("ai_agent.tools.validate_claim_completeness.OpenEMRClient") as MockClient,
        patch("ai_agent.config.get_settings", return_value=mock_settings),
    ):
        MockClient.from_settings.return_value = client_mock
        result = await validate_claim_ready_completeness.ainvoke(
            {"encounter_id": 5, "patient_id": 10}
        )

    assert result["ready"] is False
    error_checks = {e["check"] for e in result["errors"]}
    assert "diagnosis_codes" in error_checks
    assert "procedure_codes" in error_checks
    assert any("billing_fetch_failed" in w for w in result["data_warnings"])


async def test_wrapper_graceful_on_insurance_timeout():
    """Insurance API timeout → insurance_list=[] → warning, billing data still valid."""
    from unittest.mock import patch, AsyncMock as AM

    billing_rows = [
        {"code_type": "ICD10", "code": "J06.9", "code_text": "URI", "fee": 0, "modifier": "", "units": 1},
        {"code_type": "CPT4", "code": "99213", "code_text": "Office visit", "fee": 75.0, "modifier": "", "units": 1},
    ]

    mock_settings = AM()
    mock_settings.agent_base_url = "http://localhost:8000"

    patient = make_patient()
    encounter = make_encounter()

    client_mock = AsyncMock()

    async def mock_get(path: str, params: dict | None = None) -> dict:
        if "/insurance" in path:
            raise httpx.TimeoutException("Connection timed out")
        if "/encounter" in path:
            return {"data": [encounter]}
        if "/patient" in path:
            return {"data": [patient]}
        return {"data": []}

    client_mock.get = AsyncMock(side_effect=mock_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    # Mock httpx.AsyncClient for successful billing endpoint call
    billing_response = MagicMock()
    billing_response.status_code = 200
    billing_response.raise_for_status = MagicMock()
    billing_response.json.return_value = {"data": billing_rows}

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=billing_response)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("ai_agent.tools.validate_claim_completeness.httpx.AsyncClient", return_value=mock_http_client),
        patch("ai_agent.tools.validate_claim_completeness.OpenEMRClient") as MockClient,
        patch("ai_agent.config.get_settings", return_value=mock_settings),
    ):
        MockClient.from_settings.return_value = client_mock
        result = await validate_claim_ready_completeness.ainvoke(
            {"encounter_id": 5, "patient_id": 10}
        )

    # Billing data is complete, so ready should be True
    assert result["ready"] is True
    # But insurance warning should be present
    warning_checks = {w["check"] for w in result["warnings"]}
    assert "insurance" in warning_checks
