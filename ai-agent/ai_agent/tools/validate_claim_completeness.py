"""validate_claim_completeness tool — check encounter readiness for claim submission."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from ai_agent.config_data.loader import get_claim_rules
from ai_agent.openemr_client import OpenEMRClient
from ai_agent.tools._logging import logged_tool

logger = logging.getLogger(__name__)


class ValidateClaimInput(BaseModel):
    """Input schema for the validate_claim_ready_completeness tool."""

    encounter_id: int = Field(
        description="Encounter ID (integer) to validate for claim readiness.",
    )
    patient_id: int = Field(
        description="Patient ID (integer). Required to resolve encounter and billing data.",
    )


# -- individual checks --------------------------------------------------------


def _check_diagnosis_codes(
    billing_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Check 1: At least one ICD-10 diagnosis code present."""
    rules = get_claim_rules()
    accepted_dx = {t.upper() for t in rules.accepted_diagnosis_code_types}
    dx_codes = [
        row["code"]
        for row in billing_rows
        if (row.get("code_type") or "").upper() in accepted_dx
    ]
    errors: list[dict[str, Any]] = []
    if not dx_codes:
        errors.append(
            {
                "check": "diagnosis_codes",
                "message": "Missing diagnosis codes (ICD-10). At least one required.",
                "severity": rules.check_severities.get("diagnosis_codes", "error"),
            }
        )
    return errors, dx_codes


def _check_procedure_codes(
    billing_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], float]:
    """Check 2 & 7: CPT procedure codes present and fees captured."""
    rules = get_claim_rules()
    accepted_proc = {t.upper() for t in rules.accepted_procedure_code_types}
    cpt_rows = [
        row
        for row in billing_rows
        if (row.get("code_type") or "").upper() in accepted_proc
    ]
    cpt_codes = [row["code"] for row in cpt_rows]

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    total_charges = 0.0

    if not cpt_codes:
        errors.append(
            {
                "check": "procedure_codes",
                "message": "Missing procedure codes (CPT). At least one required.",
                "severity": rules.check_severities.get("procedure_codes", "error"),
            }
        )
    else:
        for row in cpt_rows:
            try:
                fee = float(row.get("fee") or 0)
            except (ValueError, TypeError):
                fee = 0.0
            total_charges += fee
            if fee == 0:
                warnings.append(
                    {
                        "check": "fees",
                        "message": f"CPT code {row['code']} has no fee assigned.",
                        "severity": rules.check_severities.get("fees", "warning"),
                    }
                )

    return errors, warnings, cpt_codes, total_charges


def _check_rendering_provider(
    encounter: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Check 3: Rendering provider assigned to the encounter."""
    rules = get_claim_rules()
    provider_id = encounter.get("provider_id")
    errors: list[dict[str, Any]] = []
    provider_name = ""

    if not provider_id or str(provider_id) == "0":
        errors.append(
            {
                "check": "rendering_provider",
                "message": "No rendering provider assigned to encounter.",
                "severity": rules.check_severities.get("rendering_provider", "error"),
            }
        )
    else:
        provider_name = f"Provider #{provider_id}"

    return errors, provider_name


def _check_billing_facility(
    encounter: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Check 4: Billing facility set on the encounter."""
    rules = get_claim_rules()
    billing_facility = encounter.get("billing_facility")
    facility_name = encounter.get("billing_facility_name", "") or encounter.get(
        "facility", ""
    )
    errors: list[dict[str, Any]] = []

    if not billing_facility or str(billing_facility) == "0":
        errors.append(
            {
                "check": "billing_facility",
                "message": "No billing facility assigned to encounter.",
                "severity": rules.check_severities.get("billing_facility", "error"),
            }
        )
        facility_name = ""

    return errors, facility_name


def _check_demographics(patient: dict[str, Any]) -> list[dict[str, Any]]:
    """Check 5: Patient demographics complete for claim submission."""
    rules = get_claim_rules()
    missing = [
        label
        for field, label in rules.required_demographics.items()
        if not str(patient.get(field, "") or "").strip()
    ]
    errors: list[dict[str, Any]] = []
    if missing:
        errors.append(
            {
                "check": "patient_demographics",
                "message": f"Patient demographics incomplete: missing {', '.join(missing)}.",
                "severity": rules.check_severities.get("patient_demographics", "error"),
            }
        )
    return errors


def _check_insurance(insurance_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check 6: Primary insurance on file."""
    has_primary = any(
        (ins.get("type") or "").upper() == "PRIMARY" for ins in insurance_list
    )
    rules = get_claim_rules()
    warnings: list[dict[str, Any]] = []
    if not has_primary:
        warnings.append(
            {
                "check": "insurance",
                "message": "No primary insurance on file. Verify if self-pay.",
                "severity": rules.check_severities.get("insurance", "warning"),
            }
        )
    return warnings


# -- core implementation -------------------------------------------------------


@logged_tool
async def _validate_claim_impl(
    client: OpenEMRClient,
    patient_id: int,
    encounter_id: int,
    billing_rows: list[dict[str, Any]],
    insurance_list: list[dict[str, Any]],
    data_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Core implementation, separated from the @tool wrapper for testability.

    ``billing_rows`` and ``insurance_list`` are passed in so the @tool wrapper
    can handle DB / API fetching while keeping _impl purely testable with mocks.
    """

    # 1. Resolve patient UUID via standard API
    patient_resp = await client.get(
        "/apis/default/api/patient", params={"pid": patient_id}
    )
    patients = (
        patient_resp.get("data", patient_resp)
        if isinstance(patient_resp, dict)
        else patient_resp
    )
    patients = patients if isinstance(patients, list) else []

    # The API may not filter by pid — match client-side.
    patient = next(
        (p for p in patients if str(p.get("pid")) == str(patient_id)),
        None,
    )

    if patient is None:
        raise ToolException(f"No patient found with ID {patient_id}")
    puuid = patient.get("uuid", "")
    if not puuid:
        raise ToolException(f"Patient {patient_id} has no UUID")

    # 2. Find the encounter
    enc_resp = await client.get(f"/apis/default/api/patient/{puuid}/encounter")
    encounters = (
        enc_resp.get("data", enc_resp) if isinstance(enc_resp, dict) else enc_resp
    )
    encounters = encounters if isinstance(encounters, list) else []

    matched_enc = None
    for enc in encounters:
        enc_id = enc.get("id") or enc.get("eid")
        if str(enc_id) == str(encounter_id):
            matched_enc = enc
            break

    if matched_enc is None:
        raise ToolException(
            f"No encounter found with ID {encounter_id} for patient {patient_id}"
        )

    # 3. Run all validation checks
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    # Check 1: Diagnosis codes
    dx_errors, dx_codes = _check_diagnosis_codes(billing_rows)
    errors.extend(dx_errors)

    # Check 2 & 7: Procedure codes and fees
    cpt_errors, fee_warnings, cpt_codes, total_charges = _check_procedure_codes(
        billing_rows
    )
    errors.extend(cpt_errors)
    warnings.extend(fee_warnings)

    # Check 3: Rendering provider
    provider_errors, provider_name = _check_rendering_provider(matched_enc)
    errors.extend(provider_errors)

    # Check 4: Billing facility
    facility_errors, facility_name = _check_billing_facility(matched_enc)
    errors.extend(facility_errors)

    # Check 5: Patient demographics
    demo_errors = _check_demographics(patient)
    errors.extend(demo_errors)

    # Check 6: Insurance
    ins_warnings = _check_insurance(insurance_list)
    warnings.extend(ins_warnings)

    # 4. Build result
    return {
        "encounter_id": encounter_id,
        "ready": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "dx_codes": dx_codes,
            "cpt_codes": cpt_codes,
            "provider": provider_name,
            "facility": facility_name,
            "total_charges": total_charges,
        },
        "data_warnings": list(data_warnings or []),
    }


@tool("validate_claim_ready_completeness", args_schema=ValidateClaimInput)
async def validate_claim_ready_completeness(
    encounter_id: int,
    patient_id: int,
) -> dict[str, Any]:
    """Check whether an encounter has all required data for claim submission.

    Validates diagnosis codes, procedure codes, rendering provider, billing
    facility, patient demographics, and insurance information. Returns a
    readiness assessment with specific errors and warnings.
    """
    from ai_agent.config import get_settings

    settings = get_settings()

    fetch_data_warnings: list[str] = []

    # Fetch billing data via internal HTTP endpoint (avoids direct DB access).
    billing_rows: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            billing_resp = await http.get(
                f"{settings.agent_base_url.rstrip('/')}/internal/billing",
                params={"encounter_id": encounter_id, "patient_id": patient_id},
            )
            billing_resp.raise_for_status()
            billing_rows = billing_resp.json().get("data", [])
    except httpx.HTTPStatusError as exc:
        detail = f"HTTP {exc.response.status_code}"
        logger.warning("Failed to fetch billing data: %s", detail)
        fetch_data_warnings.append(f"billing_fetch_failed: {detail}")
    except httpx.TimeoutException:
        logger.warning("Timed out fetching billing data for encounter %s", encounter_id)
        fetch_data_warnings.append("billing_fetch_failed: request timed out")
    except (httpx.ConnectError, httpx.RequestError, OSError) as exc:
        logger.warning("Failed to fetch billing data: %s", exc)
        # Integration tests run without a standalone ai-agent HTTP server.
        # Fall back to the same internal DB query used by /internal/billing.
        agent_base_url = settings.agent_base_url.rstrip("/")
        use_integration_fallback = bool(
            os.environ.get("INTEGRATION_TEST")
        ) and agent_base_url in {"http://localhost:8350", "http://127.0.0.1:8350"}
        if use_integration_fallback:
            try:
                from ai_agent.server import _fetch_billing_rows

                billing_rows = await asyncio.to_thread(
                    _fetch_billing_rows,
                    db_host=settings.db_host,
                    db_port=settings.db_port,
                    db_name=settings.db_name,
                    db_user=settings.db_user,
                    db_password=settings.db_password,
                    encounter_id=encounter_id,
                    patient_id=patient_id,
                    db_unix_socket=settings.db_unix_socket,
                )
                logger.info(
                    "Fetched billing data via integration fallback for encounter %s",
                    encounter_id,
                )
            except Exception as fallback_exc:
                logger.warning(
                    "Integration fallback billing fetch failed: %s", fallback_exc
                )
                fetch_data_warnings.append(
                    "billing_fetch_failed: unexpected error retrieving billing codes"
                )
        else:
            fetch_data_warnings.append(
                "billing_fetch_failed: unexpected error retrieving billing codes"
            )

    client = OpenEMRClient.from_settings()

    try:
        async with client:
            # Pre-fetch insurance data via REST API
            insurance_list: list[dict[str, Any]] = []
            try:
                patient_resp = await client.get(
                    "/apis/default/api/patient", params={"pid": patient_id}
                )
                patients = (
                    patient_resp.get("data", patient_resp)
                    if isinstance(patient_resp, dict)
                    else patient_resp
                )
                patients = patients if isinstance(patients, list) else []
                matched = next(
                    (p for p in patients if str(p.get("pid")) == str(patient_id)),
                    None,
                )
                if matched:
                    puuid = matched.get("uuid", "")
                    if puuid:
                        ins_resp = await client.get(
                            f"/apis/default/api/patient/{puuid}/insurance"
                        )
                        ins_data = (
                            ins_resp.get("data", ins_resp)
                            if isinstance(ins_resp, dict)
                            else ins_resp
                        )
                        insurance_list = ins_data if isinstance(ins_data, list) else []
            except httpx.HTTPStatusError as exc:
                detail = f"HTTP {exc.response.status_code}"
                logger.warning("Failed to fetch insurance data: %s", detail)
                fetch_data_warnings.append(f"insurance_fetch_failed: {detail}")
            except httpx.TimeoutException:
                logger.warning(
                    "Timed out fetching insurance data for patient %s", patient_id
                )
                fetch_data_warnings.append("insurance_fetch_failed: request timed out")
            except httpx.RequestError as exc:
                logger.warning("Failed to fetch insurance data: %s", exc)
                fetch_data_warnings.append(
                    "insurance_fetch_failed: network error retrieving insurance"
                )

            return await _validate_claim_impl(
                client,
                patient_id=patient_id,
                encounter_id=encounter_id,
                billing_rows=billing_rows,
                insurance_list=insurance_list,
                data_warnings=fetch_data_warnings,
            )
    except httpx.TimeoutException as exc:
        raise ToolException(f"OpenEMR API timed out: {exc}. Please try again.") from exc
    except httpx.RequestError as exc:
        raise ToolException(
            f"OpenEMR API network error: {exc}. Please check connectivity and try again."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ToolException(
            f"OpenEMR API error ({exc.response.status_code}): {exc.response.text}"
        ) from exc
