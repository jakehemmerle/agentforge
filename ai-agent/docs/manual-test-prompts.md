# Manual Test Prompts — AI Chat Widget

These prompts exercise each of the AI agent's five tools against the
seed data created by `scripts/seed_data.py`.  Run them in the chat
widget after a full `dev-setup up` (see `.claude/skills/dev-setup/`).

## Prerequisites

1. Local stack is running (`mysql`, `openemr`, `ai-agent` all healthy).
2. Seed data has been loaded:
   ```bash
   cd ai-agent
   OPENEMR_BASE_URL=http://localhost:8300 DB_HOST=127.0.0.1 DB_PORT=8320 \
     uv run python scripts/seed_data.py
   ```
3. Open http://localhost:8300, log in as `admin` / `pass`.
4. Click the chat bubble (bottom-right) to open the AI Assistant.

## Tool 1 — `find_appointments`

**Prompt:**
> What appointments does John Doe have today?

**Expected behaviour:**
- Agent calls `find_appointments` with `patient_name="John Doe"` and
  today's date.
- Returns two appointments (2:00 PM Arrived, 3:30 PM Open) with
  provider, status, category, and facility.

## Tool 2 — `get_patient_summary`

**Prompt:**
> Give me a summary of patient Maria Garcia

**Expected behaviour:**
- Agent resolves the patient name to ID 90004 (may call
  `find_appointments` first).
- Calls `get_patient_summary` and returns demographics (DOB, sex, MRN),
  active problems, medications, allergies, and recent appointment
  activity.

## Tool 3 — `get_encounter_context`

**Prompt:**
> Show me Robert Johnson's encounter details from today

**Expected behaviour:**
- Agent calls `find_appointments` to locate the patient and encounter.
- Calls `get_encounter_context` with the encounter date.
- Returns SOAP notes (acute low back pain M54.5), vitals, billing info,
  and hyperlipidemia (E78.5) with atorvastatin.

## Tool 4 — `draft_encounter_note`

**Prompt (continuation of Tool 3 conversation):**
> Yes, please draft a SOAP note for this encounter

**Expected behaviour:**
- Agent calls `draft_encounter_note` referencing the encounter from the
  previous turn.
- Returns a full SOAP note draft with Subjective, Objective, Assessment,
  and Plan sections.
- Includes "DRAFT NOTE — REQUIRES CLINICIAN REVIEW AND SIGNATURE"
  disclaimer and any data warnings.

## Tool 5 — `validate_claim_completeness`

**Prompt:**
> Is Jane Smith's encounter from today ready for claim submission?

**Expected behaviour:**
- Agent resolves the patient, finds the encounter.
- Calls `validate_claim_completeness`.
- Returns CPT code (99213), total charges ($110), and lists required
  actions (e.g. missing ICD-10 diagnosis codes, insurance verification).

## Seed Data Reference

| Patient ID | Name            | Key Data                                      |
|------------|-----------------|-----------------------------------------------|
| 90001      | John Doe        | 2 appts today, encounter yesterday, URI       |
| 90002      | Jane Smith      | 1 appt today (checked out), annual wellness   |
| 90003      | Robert Johnson  | 1 appt today, low back pain, hyperlipidemia   |
| 90004      | Maria Garcia    | 1 appt today (arrived), diabetes follow-up    |
| 90005      | James Wilson    | 1 appt today, COPD, CHF, A-fib, CKD          |
