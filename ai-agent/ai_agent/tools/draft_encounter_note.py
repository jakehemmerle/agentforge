"""draft_encounter_note tool — generate a draft clinical note from encounter context."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from ai_agent.config_data.loader import get_prompts
from ai_agent.openemr_client import OpenEMRClient
from ai_agent.tools._logging import logged_tool
from ai_agent.tools.get_encounter_context import _get_encounter_context_impl

logger = logging.getLogger(__name__)


class DraftEncounterNoteInput(BaseModel):
    """Input schema for the draft_encounter_note tool."""

    encounter_id: int = Field(
        description="Encounter ID (integer). Required.",
    )
    patient_id: int = Field(
        description="Patient ID (integer). Required to fetch encounter context.",
    )
    note_type: Optional[str] = Field(
        default="SOAP",
        description="Type of note to generate: 'SOAP', 'progress', or 'brief'. Defaults to 'SOAP'.",
    )
    additional_context: Optional[str] = Field(
        default=None,
        description="Extra context from user conversation to incorporate into the note.",
    )


def _build_encounter_summary(context: dict[str, Any]) -> str:
    """Build a human-readable summary of encounter context for the LLM prompt."""
    parts: list[str] = []

    # Patient demographics
    patient = context.get("patient", {})
    if patient:
        parts.append(
            f"PATIENT: {patient.get('name', 'Unknown')}, "
            f"DOB: {patient.get('dob', 'Unknown')}, "
            f"Sex: {patient.get('sex', 'Unknown')}, "
            f"MRN: {patient.get('mrn', '')}"
        )

    # Encounter info
    enc = context.get("encounter", {})
    if enc:
        parts.append(
            f"ENCOUNTER: Date: {enc.get('date', 'Unknown')}, "
            f"Reason: {enc.get('reason', 'Not specified')}, "
            f"Facility: {enc.get('facility', {}).get('name', 'Unknown')}, "
            f"Status: {enc.get('status', '')}"
        )

    clinical = context.get("clinical_context", {})

    # Active problems
    problems = clinical.get("active_problems", [])
    if problems:
        problem_lines = [
            f"  - {p.get('description', '')} ({p.get('code', '')}) onset {p.get('onset_date', '')}"
            for p in problems
        ]
        parts.append("ACTIVE PROBLEMS:\n" + "\n".join(problem_lines))
    else:
        parts.append("ACTIVE PROBLEMS: None documented")

    # Medications
    meds = clinical.get("medications", [])
    if meds:
        med_lines = [
            f"  - {m.get('drug_name', '')} {m.get('dose', '')} {m.get('frequency', '')}"
            for m in meds
        ]
        parts.append("MEDICATIONS:\n" + "\n".join(med_lines))
    else:
        parts.append("MEDICATIONS: None documented")

    # Allergies
    allergies = clinical.get("allergies", [])
    if allergies:
        allergy_lines = [
            f"  - {a.get('substance', '')}: {a.get('reaction', '')} ({a.get('severity', '')})"
            for a in allergies
        ]
        parts.append("ALLERGIES:\n" + "\n".join(allergy_lines))
    else:
        parts.append("ALLERGIES: NKDA (None documented)")

    # Vitals
    vitals = clinical.get("vitals")
    if vitals:
        vitals_str = (
            f"  Temp: {vitals.get('temp', 'N/A')}, "
            f"BP: {vitals.get('bp', 'N/A')}, "
            f"HR: {vitals.get('hr', 'N/A')}, "
            f"RR: {vitals.get('rr', 'N/A')}, "
            f"SpO2: {vitals.get('spo2', 'N/A')}, "
            f"Wt: {vitals.get('weight', 'N/A')}, "
            f"Ht: {vitals.get('height', 'N/A')}"
        )
        parts.append(f"VITALS:\n{vitals_str}")
    else:
        parts.append("VITALS: Not recorded")

    # Existing notes
    notes = clinical.get("existing_notes", [])
    if notes:
        note_lines = [
            f"  - [{n.get('date', '')}] {n.get('summary', '')}" for n in notes
        ]
        parts.append("EXISTING NOTES:\n" + "\n".join(note_lines))

    return "\n\n".join(parts)


def _parse_llm_response(content: str, note_type: str) -> tuple[dict[str, Any], bool]:
    """Parse the LLM's JSON response, handling common formatting issues.

    Returns (parsed_dict, failed) where *failed* is True when JSON parsing
    fell back to a raw-text wrapper.
    """
    text = content.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove only the opening and closing fence lines
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text), False
    except json.JSONDecodeError:
        # Fallback: wrap the raw text in the expected structure
        if note_type == "SOAP":
            return {
                "subjective": text,
                "objective": "No data available",
                "assessment": "No data available",
                "plan": "No data available",
            }, True
        elif note_type == "progress":
            return {"narrative": text}, True
        else:
            return {"summary": text}, True


def _format_full_text(content: dict[str, Any], note_type: str) -> str:
    """Format the structured content into a readable full-text note."""
    if note_type == "SOAP":
        sections = []
        for key in ("subjective", "objective", "assessment", "plan"):
            label = key[0].upper()
            text = content.get(key, "No data available")
            sections.append(f"{label}: {text}")
        return "\n\n".join(sections)
    elif note_type == "progress":
        return content.get("narrative", "")
    else:
        return content.get("summary", "")


@logged_tool
async def _draft_encounter_note_impl(
    client: OpenEMRClient,
    llm: ChatAnthropic,
    encounter_id: int,
    patient_id: int,
    note_type: str = "SOAP",
    additional_context: str | None = None,
) -> dict[str, Any]:
    """Core implementation, separated from the @tool wrapper for testability."""
    prompts = get_prompts()
    warnings: list[str] = []

    # Validate note_type
    valid_note_types = set(prompts.note_type_templates.keys())
    if note_type not in valid_note_types:
        note_type = "SOAP"
        warnings.append("Invalid note type requested; defaulting to SOAP.")

    # 1. Fetch encounter context
    context = await _get_encounter_context_impl(
        client, patient_id=patient_id, encounter_id=encounter_id
    )

    # If we got a disambiguation response (multiple encounters), re-raise
    if "message" in context and "encounters" in context:
        raise ToolException(context["message"])

    # Extract upstream data_warnings from get_encounter_context
    data_warnings: list[str] = list(context.get("data_warnings", []))

    # 2. Build the prompt
    encounter_summary = _build_encounter_summary(context)
    template = prompts.note_type_templates[note_type]

    prompt_parts = [f"ENCOUNTER CONTEXT:\n{encounter_summary}"]
    if additional_context:
        prompt_parts.append(
            f"ADDITIONAL CONTEXT FROM CONVERSATION:\n{additional_context}"
        )
    prompt_parts.append(template)

    user_prompt = "\n\n".join(prompt_parts)

    # 3. Check for missing data and add warnings
    #    Distinguish "genuinely absent" from "fetch failed" using data_warnings.
    clinical = context.get("clinical_context", {})
    if not clinical.get("vitals"):
        if any(w.startswith("vitals_fetch_failed") for w in data_warnings):
            warnings.append("Vitals unavailable \u2014 fetch from EHR failed.")
        else:
            warnings.append("No vitals recorded for this encounter.")
    if not clinical.get("active_problems"):
        if any(w.startswith("conditions_fetch_failed") for w in data_warnings):
            warnings.append("Active problems unavailable \u2014 fetch from EHR failed.")
        else:
            warnings.append("No active problems documented.")
    if not clinical.get("medications"):
        if any(w.startswith("medications_fetch_failed") for w in data_warnings):
            warnings.append("Medications unavailable \u2014 fetch from EHR failed.")
        else:
            warnings.append("No medications documented.")

    # 4. Call LLM
    messages = [
        SystemMessage(content=prompts.scribe_system_prompt),
        HumanMessage(content=user_prompt),
    ]
    response = await llm.ainvoke(messages)
    if isinstance(response.content, str):
        raw_content = response.content
    elif isinstance(response.content, list):
        raw_content = "".join(
            block["text"]
            for block in response.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        raw_content = str(response.content)

    # 5. Parse response
    content, parse_failed = _parse_llm_response(raw_content, note_type)
    if parse_failed:
        data_warnings.append(
            "llm_response_parse_failed: LLM did not return valid JSON; "
            "raw text was wrapped in fallback structure"
        )
    full_text = _format_full_text(content, note_type)

    patient_name = context.get("patient", {}).get("name", "Unknown")

    return {
        "draft_note": {
            "type": note_type,
            "content": content,
            "full_text": full_text,
            "encounter_id": encounter_id,
            "patient_name": patient_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "warnings": warnings,
        "data_warnings": data_warnings,
        "disclaimer": "This is an AI-generated draft. Review and edit before saving.",
    }


@tool("draft_encounter_note", args_schema=DraftEncounterNoteInput)
async def draft_encounter_note(
    encounter_id: int,
    patient_id: int,
    note_type: str = "SOAP",
    additional_context: str | None = None,
) -> dict[str, Any]:
    """Generate a draft clinical note from encounter context.

    Produces a DRAFT note only — does NOT save to the database.
    The note must be reviewed and edited by a clinician before use.
    Supports SOAP, progress, and brief note formats.
    """
    from ai_agent.config import get_settings

    settings = get_settings()

    client = OpenEMRClient.from_settings()

    llm = ChatAnthropic(
        model=settings.model_name,
        temperature=0,
        api_key=settings.anthropic_api_key or None,
    )

    try:
        async with client:
            return await _draft_encounter_note_impl(
                client,
                llm,
                encounter_id=encounter_id,
                patient_id=patient_id,
                note_type=note_type,
                additional_context=additional_context,
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
