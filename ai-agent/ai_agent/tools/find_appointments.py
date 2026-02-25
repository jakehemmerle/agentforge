"""find_appointments tool — search OpenEMR appointments by flexible criteria."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from ai_agent.openemr_client import OpenEMRClient
from ai_agent.tools._logging import logged_tool

logger = logging.getLogger(__name__)

# OpenEMR appointment status codes → human labels.
_STATUS_LABELS: dict[str, str] = {
    "-": "Open",
    "@": "Arrived",
    "~": "Arrived late",
    "!": "Left w/o being seen",
    "#": "Ins/fin issue",
    "<": "In exam room",
    ">": "Checked out",
    "$": "Coding done",
    "%": "Cancelled",
    "x": "No show",
    "^": "Pending",
}


class FindAppointmentsInput(BaseModel):
    """Input schema for the find_appointments tool."""

    patient_name: Optional[str] = Field(
        default=None,
        description="Patient name to search for (first or last name).",
    )
    date: Optional[str] = Field(
        default=None,
        description="Appointment date in YYYY-MM-DD format.",
    )
    provider_name: Optional[str] = Field(
        default=None,
        description="Provider/practitioner name to filter by.",
    )
    status: Optional[str] = Field(
        default=None,
        description="Appointment status code (e.g. '-' for open, '@' for arrived, '%' for cancelled).",
    )
    patient_id: Optional[int] = Field(
        default=None,
        description="Direct patient ID if already known.",
    )


def _format_appointment(appt: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw API appointment record into the tool's output shape."""
    status_code = appt.get("pc_apptstatus", "")
    provider_parts = [
        appt.get("pce_aid_fname", ""),
        appt.get("pce_aid_lname", ""),
    ]
    return {
        "appointment_id": appt.get("pc_eid"),
        "patient_name": f"{appt.get('fname', '')} {appt.get('lname', '')}".strip(),
        "patient_id": appt.get("pc_pid") or appt.get("pid"),
        "provider_name": " ".join(p for p in provider_parts if p),
        "date": appt.get("pc_eventDate", ""),
        "start_time": appt.get("pc_startTime", ""),
        "end_time": appt.get("pc_endTime", ""),
        "status": status_code,
        "status_label": _STATUS_LABELS.get(status_code, status_code),
        "category": appt.get("pc_title", ""),
        "facility": appt.get("facility_name", ""),
        "reason": appt.get("pc_hometext", ""),
    }


def _matches_provider(appt: dict[str, Any], provider_name: str) -> bool:
    """Case-insensitive check if provider name appears in the appointment."""
    needle = provider_name.lower()
    haystack = f"{appt.get('pce_aid_fname', '')} {appt.get('pce_aid_lname', '')}".lower()
    return needle in haystack


async def _search_patients(
    client: OpenEMRClient, name: str
) -> list[dict[str, Any]]:
    """Search patients by name. Splits into first/last when possible."""
    parts = name.strip().split()

    # If two+ words, try fname + lname together first
    if len(parts) >= 2:
        fname, lname = parts[0], " ".join(parts[1:])
        resp = await client.get(
            "/apis/default/api/patient", params={"fname": fname, "lname": lname}
        )
        patients = resp.get("data", resp) if isinstance(resp, dict) else resp
        if patients:
            return patients if isinstance(patients, list) else []

    # Fall back: try as last name only
    resp = await client.get("/apis/default/api/patient", params={"lname": name})
    patients = resp.get("data", resp) if isinstance(resp, dict) else resp

    if not patients:
        # Fall back: try as first name only
        resp = await client.get("/apis/default/api/patient", params={"fname": name})
        patients = resp.get("data", resp) if isinstance(resp, dict) else resp

    return patients if isinstance(patients, list) else []


async def _fetch_appointments_for_patient(
    client: OpenEMRClient, pid: int
) -> list[dict[str, Any]]:
    """Fetch appointments for a specific patient."""
    try:
        resp = await client.get(f"/apis/default/api/patient/{pid}/appointment")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Non-existent patient or no appointment endpoint match.
            return []
        raise
    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    return data if isinstance(data, list) else []


async def _fetch_all_appointments(
    client: OpenEMRClient,
) -> list[dict[str, Any]]:
    """Fetch all appointments."""
    resp = await client.get("/apis/default/api/appointment")
    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    return data if isinstance(data, list) else []


@logged_tool
async def _find_appointments_impl(
    client: OpenEMRClient,
    patient_name: str | None = None,
    date: str | None = None,
    provider_name: str | None = None,
    status: str | None = None,
    patient_id: int | None = None,
) -> dict[str, Any]:
    """Core implementation, separated from the @tool wrapper for testability."""

    # -- resolve patient_name → patient_id(s) if needed -----------------------
    resolved_pids: list[int] = []
    if patient_id is not None:
        resolved_pids = [patient_id]
    elif patient_name:
        patients = await _search_patients(client, patient_name)
        if not patients:
            return {
                "appointments": [],
                "total_count": 0,
                "message": f"No patients found matching '{patient_name}'.",
            }
        if len(patients) > 5:
            matches = [
                {
                    "patient_id": p.get("pid"),
                    "name": f"{p.get('fname', '')} {p.get('lname', '')}".strip(),
                    "DOB": p.get("DOB", ""),
                }
                for p in patients[:10]
            ]
            return {
                "appointments": [],
                "total_count": 0,
                "message": f"Multiple patients match '{patient_name}'. Please clarify which patient.",
                "matching_patients": matches,
            }
        resolved_pids = [p["pid"] for p in patients if p.get("pid")]

    # -- fetch appointments ----------------------------------------------------
    raw_appointments: list[dict[str, Any]] = []
    if resolved_pids:
        for pid in resolved_pids:
            raw_appointments.extend(
                await _fetch_appointments_for_patient(client, pid)
            )
    else:
        raw_appointments = await _fetch_all_appointments(client)

    # -- client-side filtering -------------------------------------------------
    filtered = raw_appointments

    if date:
        filtered = [a for a in filtered if a.get("pc_eventDate") == date]

    if status:
        filtered = [a for a in filtered if a.get("pc_apptstatus") == status]

    if provider_name:
        filtered = [a for a in filtered if _matches_provider(a, provider_name)]

    appointments = [_format_appointment(a) for a in filtered]

    result: dict[str, Any] = {
        "appointments": appointments,
        "total_count": len(appointments),
    }
    if not appointments:
        result["message"] = "No appointments found matching criteria."
    return result


@tool("find_appointments", args_schema=FindAppointmentsInput)
async def find_appointments(
    patient_name: str | None = None,
    date: str | None = None,
    provider_name: str | None = None,
    status: str | None = None,
    patient_id: int | None = None,
) -> dict[str, Any]:
    """Search OpenEMR for appointments matching the given criteria.

    You can search by patient name, date, provider, status, or patient ID.
    If a patient name matches multiple patients, you'll get a list to clarify.
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
            return await _find_appointments_impl(
                client,
                patient_name=patient_name,
                date=date,
                provider_name=provider_name,
                status=status,
                patient_id=patient_id,
            )
    except httpx.TimeoutException as exc:
        raise ToolException(
            f"OpenEMR API timed out: {exc}. Please try again."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ToolException(
            f"OpenEMR API error ({exc.response.status_code}): {exc.response.text}"
        ) from exc
