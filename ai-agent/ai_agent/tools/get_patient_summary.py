"""get_patient_summary tool — retrieve patient overview without encounter context."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from ai_agent.openemr_client import OpenEMRClient
from ai_agent.tools._logging import logged_tool
from ai_agent.tools.get_encounter_context import (
    _parse_allergies,
    _parse_conditions,
    _parse_medications,
    _format_patient,
)

logger = logging.getLogger(__name__)


class GetPatientSummaryInput(BaseModel):
    """Input schema for the get_patient_summary tool."""

    patient_id: int = Field(
        description="Patient ID (integer). Required to look up the patient.",
    )


# -- core implementation -------------------------------------------------------


@logged_tool
async def _get_patient_summary_impl(
    client: OpenEMRClient,
    patient_id: int,
) -> dict[str, Any]:
    """Core implementation, separated from the @tool wrapper for testability."""

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

    patient = next(
        (p for p in patients if str(p.get("pid")) == str(patient_id)),
        None,
    )

    if patient is None:
        raise ToolException(f"No patient found with ID {patient_id}")
    puuid = patient.get("uuid", "")
    if not puuid:
        raise ToolException(f"Patient {patient_id} has no UUID")

    # 2. Fetch clinical data in parallel

    async def _fetch_conditions() -> tuple[list[dict[str, Any]], list[str]]:
        try:
            bundle = await client.get(
                "/apis/default/fhir/Condition", params={"patient": puuid}
            )
            return _parse_conditions(bundle), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning(
                "Failed to fetch conditions for patient %s: %s", puuid, detail
            )
            return [], [f"conditions_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching conditions for patient %s", puuid)
            return [], ["conditions_fetch_failed: request timed out"]
        except httpx.RequestError as exc:
            logger.warning(
                "Network error fetching conditions for patient %s: %s", puuid, exc
            )
            return [], ["conditions_fetch_failed: network error retrieving conditions"]

    async def _fetch_medications() -> tuple[list[dict[str, Any]], list[str]]:
        try:
            bundle = await client.get(
                "/apis/default/fhir/MedicationRequest",
                params={"patient": puuid, "status": "active"},
            )
            return _parse_medications(bundle), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning(
                "Failed to fetch medications for patient %s: %s", puuid, detail
            )
            return [], [f"medications_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching medications for patient %s", puuid)
            return [], ["medications_fetch_failed: request timed out"]
        except httpx.RequestError as exc:
            logger.warning(
                "Network error fetching medications for patient %s: %s", puuid, exc
            )
            return [], [
                "medications_fetch_failed: network error retrieving medications"
            ]

    async def _fetch_allergies() -> tuple[list[dict[str, Any]], list[str]]:
        try:
            bundle = await client.get(
                "/apis/default/fhir/AllergyIntolerance", params={"patient": puuid}
            )
            return _parse_allergies(bundle), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning(
                "Failed to fetch allergies for patient %s: %s", puuid, detail
            )
            return [], [f"allergies_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching allergies for patient %s", puuid)
            return [], ["allergies_fetch_failed: request timed out"]
        except httpx.RequestError as exc:
            logger.warning(
                "Network error fetching allergies for patient %s: %s", puuid, exc
            )
            return [], ["allergies_fetch_failed: network error retrieving allergies"]

    (
        (conditions, cond_w),
        (medications, med_w),
        (allergies, allergy_w),
    ) = await asyncio.gather(
        _fetch_conditions(),
        _fetch_medications(),
        _fetch_allergies(),
    )
    data_warnings = [*cond_w, *med_w, *allergy_w]

    # 3. Assemble response
    return {
        "patient": _format_patient(patient),
        "active_problems": conditions,
        "medications": medications,
        "allergies": allergies,
        "data_warnings": data_warnings,
    }


@tool("get_patient_summary", args_schema=GetPatientSummaryInput)
async def get_patient_summary(
    patient_id: int,
) -> dict[str, Any]:
    """Retrieve a patient overview including demographics, active problems, medications, and allergies.

    Use this when the user asks about a patient's current medications,
    allergies, or conditions without needing encounter-specific details.
    """
    from ai_agent.config import get_settings

    settings = get_settings()

    client = OpenEMRClient(
        base_url=settings.openemr_base_url,
        client_id=settings.openemr_client_id,
        client_secret=settings.openemr_client_secret,
        username=settings.openemr_username,
        password=settings.openemr_password,
    )

    try:
        async with client:
            return await _get_patient_summary_impl(
                client,
                patient_id=patient_id,
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
