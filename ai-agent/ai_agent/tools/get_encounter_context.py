"""get_encounter_context tool — retrieve full clinical context for a patient encounter."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field, model_validator

from ai_agent.openemr_client import OpenEMRClient
from ai_agent.tools._logging import logged_tool

logger = logging.getLogger(__name__)


class GetEncounterContextInput(BaseModel):
    """Input schema for the get_encounter_context tool."""

    encounter_id: Optional[int] = Field(
        default=None,
        description="Direct encounter ID (integer). Requires patient_id.",
    )
    patient_id: int = Field(
        description="Patient ID (integer). Required to resolve encounter.",
    )
    date: Optional[str] = Field(
        default=None,
        description="Encounter date in YYYY-MM-DD format. Used to find encounter when encounter_id is not provided.",
    )

    @model_validator(mode="after")
    def require_encounter_id_or_date(self) -> GetEncounterContextInput:
        if self.encounter_id is None and self.date is None:
            raise ValueError("Either encounter_id or date must be provided.")
        return self


# -- FHIR response parsers ----------------------------------------------------


def _parse_conditions(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract active problems from a FHIR Condition Bundle."""
    results = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        coding = (resource.get("code") or {}).get("coding", [{}])
        first_code = coding[0] if coding else {}
        results.append({
            "code": first_code.get("code", ""),
            "description": first_code.get("display", resource.get("code", {}).get("text", "")),
            "onset_date": resource.get("onsetDateTime", ""),
        })
    return results


def _parse_medications(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract medications from a FHIR MedicationRequest Bundle."""
    results = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        coding = (resource.get("medicationCodeableConcept") or {}).get("coding", [{}])
        first_code = coding[0] if coding else {}
        dosage = resource.get("dosageInstruction", [{}])
        first_dosage = dosage[0] if dosage else {}
        dose_quant = first_dosage.get("doseAndRate", [{}])
        first_dose = dose_quant[0] if dose_quant else {}
        dose_val = first_dose.get("doseQuantity", {})
        timing = first_dosage.get("timing", {}).get("code", {})
        results.append({
            "drug_name": first_code.get("display", resource.get("medicationCodeableConcept", {}).get("text", "")),
            "dose": f"{dose_val.get('value', '')} {dose_val.get('unit', '')}".strip(),
            "frequency": timing.get("text", ""),
        })
    return results


def _parse_allergies(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract allergies from a FHIR AllergyIntolerance Bundle."""
    results = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        coding = (resource.get("code") or {}).get("coding", [{}])
        first_code = coding[0] if coding else {}
        reactions = resource.get("reaction", [])
        first_reaction = reactions[0] if reactions else {}
        manifestation = first_reaction.get("manifestation", [{}])
        first_manif = manifestation[0] if manifestation else {}
        manif_coding = first_manif.get("coding", [{}])
        first_manif_code = manif_coding[0] if manif_coding else {}
        results.append({
            "substance": first_code.get("display", resource.get("code", {}).get("text", "")),
            "reaction": first_manif_code.get("display", ""),
            "severity": first_reaction.get("severity", ""),
        })
    return results


# -- response formatters -------------------------------------------------------


def _format_vitals(vitals_list: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Format the most recent vitals record."""
    if not vitals_list:
        return None
    latest = vitals_list[-1]
    bp_parts = [latest.get("bps", ""), latest.get("bpd", "")]
    bp = "/".join(p for p in bp_parts if p) if any(bp_parts) else ""
    return {
        "temp": latest.get("temperature", ""),
        "bp": bp,
        "hr": latest.get("pulse", ""),
        "rr": latest.get("respiration", ""),
        "spo2": latest.get("oxygen_saturation", ""),
        "weight": latest.get("weight", ""),
        "height": latest.get("height", ""),
    }


def _format_soap_notes(notes_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format SOAP notes into the output shape."""
    results = []
    for note in notes_list:
        parts = []
        for section in ("subjective", "objective", "assessment", "plan"):
            text = note.get(section, "")
            if text:
                parts.append(f"{section.upper()}: {text}")
        results.append({
            "type": "SOAP",
            "date": note.get("date", ""),
            "summary": "; ".join(parts) if parts else "",
        })
    return results


def _format_encounter(enc: dict[str, Any]) -> dict[str, Any]:
    """Format raw encounter data into the output shape."""
    return {
        "id": enc.get("id") or enc.get("eid"),
        "date": enc.get("date", ""),
        "reason": enc.get("reason", ""),
        "provider": {
            "name": "",
            "id": enc.get("provider_id"),
        },
        "facility": {
            "name": enc.get("facility", ""),
            "id": enc.get("facility_id"),
        },
        "class_code": enc.get("class_code", ""),
        "status": enc.get("pc_catname", ""),
    }


def _format_patient(patient: dict[str, Any]) -> dict[str, Any]:
    """Format raw patient data into the output shape."""
    return {
        "id": patient.get("pid"),
        "name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
        "dob": patient.get("DOB", ""),
        "sex": patient.get("sex", ""),
        "mrn": patient.get("pubpid", ""),
    }


def _format_billing_status(enc: dict[str, Any]) -> dict[str, Any]:
    """Extract available billing metadata from the encounter response."""
    return {
        "has_dx_codes": False,
        "has_cpt_codes": False,
        "dx_codes": [],
        "cpt_codes": [],
        "billing_note": enc.get("billing_note", ""),
        "last_level_billed": enc.get("last_level_billed", ""),
        "last_level_closed": enc.get("last_level_closed", ""),
    }


# -- core implementation -------------------------------------------------------


@logged_tool
async def _get_encounter_context_impl(
    client: OpenEMRClient,
    patient_id: int,
    encounter_id: int | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Core implementation, separated from the @tool wrapper for testability."""

    # 1. Resolve patient UUID via standard API
    patient_resp = await client.get(
        "/apis/default/api/patient", params={"pid": patient_id}
    )
    patients = patient_resp.get("data", patient_resp) if isinstance(patient_resp, dict) else patient_resp
    patients = patients if isinstance(patients, list) else []

    # OpenEMR may return a broader patient list even when pid is provided.
    # Match client-side to avoid selecting the wrong patient.
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
    encounters = enc_resp.get("data", enc_resp) if isinstance(enc_resp, dict) else enc_resp
    encounters = encounters if isinstance(encounters, list) else []

    matched_enc = None
    if encounter_id is not None:
        for enc in encounters:
            if str(enc.get("id") or enc.get("eid")) == str(encounter_id):
                matched_enc = enc
                break
        if matched_enc is None:
            raise ToolException(
                f"No encounter found with ID {encounter_id} for patient {patient_id}"
            )
    elif date is not None:
        date_matches = [e for e in encounters if (e.get("date") or "").startswith(date)]
        if not date_matches:
            raise ToolException(
                f"No encounters found on {date} for patient {patient_id}"
            )
        if len(date_matches) > 1:
            return {
                "message": f"Multiple encounters found on {date}. Please specify encounter_id.",
                "encounters": [
                    {"id": e.get("id") or e.get("eid"), "date": e.get("date"), "reason": e.get("reason", "")}
                    for e in date_matches
                ],
            }
        matched_enc = date_matches[0]

    enc = matched_enc
    eid = enc.get("id") or enc.get("eid")
    pid = enc.get("pid", patient_id)

    # 3. Fetch clinical context in parallel
    #    Each fetcher returns (result, warnings) to avoid shared mutable state.

    async def _fetch_conditions() -> tuple[list[dict[str, Any]], list[str]]:
        try:
            bundle = await client.get(
                f"/apis/default/fhir/Condition", params={"patient": puuid}
            )
            return _parse_conditions(bundle), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning("Failed to fetch conditions for patient %s: %s", puuid, detail)
            return [], [f"conditions_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching conditions for patient %s", puuid)
            return [], ["conditions_fetch_failed: request timed out"]

    async def _fetch_medications() -> tuple[list[dict[str, Any]], list[str]]:
        try:
            bundle = await client.get(
                f"/apis/default/fhir/MedicationRequest",
                params={"patient": puuid, "status": "active"},
            )
            return _parse_medications(bundle), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning("Failed to fetch medications for patient %s: %s", puuid, detail)
            return [], [f"medications_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching medications for patient %s", puuid)
            return [], ["medications_fetch_failed: request timed out"]

    async def _fetch_allergies() -> tuple[list[dict[str, Any]], list[str]]:
        try:
            bundle = await client.get(
                f"/apis/default/fhir/AllergyIntolerance", params={"patient": puuid}
            )
            return _parse_allergies(bundle), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning("Failed to fetch allergies for patient %s: %s", puuid, detail)
            return [], [f"allergies_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching allergies for patient %s", puuid)
            return [], ["allergies_fetch_failed: request timed out"]

    async def _fetch_vitals() -> tuple[dict[str, Any] | None, list[str]]:
        try:
            resp = await client.get(
                f"/apis/default/api/patient/{pid}/encounter/{eid}/vital"
            )
            data = resp.get("data", resp) if isinstance(resp, dict) else resp
            vitals_list = data if isinstance(data, list) else []
            return _format_vitals(vitals_list), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning("Failed to fetch vitals for encounter %s: %s", eid, detail)
            return None, [f"vitals_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching vitals for encounter %s", eid)
            return None, ["vitals_fetch_failed: request timed out"]

    async def _fetch_soap_notes() -> tuple[list[dict[str, Any]], list[str]]:
        try:
            resp = await client.get(
                f"/apis/default/api/patient/{pid}/encounter/{eid}/soap_note"
            )
            data = resp.get("data", resp) if isinstance(resp, dict) else resp
            notes_list = data if isinstance(data, list) else []
            return _format_soap_notes(notes_list), []
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            logger.warning("Failed to fetch SOAP notes for encounter %s: %s", eid, detail)
            return [], [f"soap_notes_fetch_failed: {detail}"]
        except httpx.TimeoutException:
            logger.warning("Timed out fetching SOAP notes for encounter %s", eid)
            return [], ["soap_notes_fetch_failed: request timed out"]

    (conditions, cond_w), (medications, med_w), (allergies, allergy_w), (vitals, vitals_w), (soap_notes, soap_w) = await asyncio.gather(
        _fetch_conditions(),
        _fetch_medications(),
        _fetch_allergies(),
        _fetch_vitals(),
        _fetch_soap_notes(),
    )
    data_warnings = [*cond_w, *med_w, *allergy_w, *vitals_w, *soap_w]

    # 4. Assemble response
    return {
        "encounter": _format_encounter(enc),
        "patient": _format_patient(patient),
        "clinical_context": {
            "active_problems": conditions,
            "medications": medications,
            "allergies": allergies,
            "vitals": vitals,
            "existing_notes": soap_notes,
        },
        "billing_status": _format_billing_status(enc),
        "data_warnings": data_warnings,
    }


@tool("get_encounter_context", args_schema=GetEncounterContextInput)
async def get_encounter_context(
    patient_id: int,
    encounter_id: int | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Retrieve full clinical context for a patient encounter.

    Returns encounter details, patient demographics, active problems,
    medications, allergies, vitals, existing notes, and billing status.
    Use this when you need comprehensive encounter information for
    clinical note drafting or claim validation.
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
            return await _get_encounter_context_impl(
                client,
                patient_id=patient_id,
                encounter_id=encounter_id,
                date=date,
            )
    except httpx.TimeoutException as exc:
        raise ToolException(
            f"OpenEMR API timed out: {exc}. Please try again."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ToolException(
            f"OpenEMR API error ({exc.response.status_code}): {exc.response.text}"
        ) from exc
