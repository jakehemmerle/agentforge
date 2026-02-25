# Research Report: get_encounter_context Tool (bd-1as)

## Issue Summary

Implement `get_encounter_context` tool that retrieves full clinical context for a patient encounter. This tool pulls comprehensive encounter data from OpenEMR to provide context for clinical note drafting and claim validation.

**File:** `ai-agent/ai_agent/tools/get_encounter_context.py`

**Blocked by:** bd-2us (OAuth client) — already implemented.
**Blocks:** bd-1ff (draft_encounter_note), bd-3a8 (tests for new tools), bd-1uu (register tools with agent)

---

## Existing Tool Pattern (find_appointments)

The `find_appointments` tool at `ai-agent/ai_agent/tools/find_appointments.py` establishes a clear, consistent pattern:

### Structure

1. **Pydantic `BaseModel`** for input schema (`FindAppointmentsInput`) with `Field` descriptors for each parameter
2. **`@tool` decorator** from `langchain_core.tools` with `args_schema=InputClass`
3. **Separated `_impl` function** from the `@tool` wrapper for testability — the impl takes an `OpenEMRClient` as its first argument
4. **Client instantiation** happens inside the `@tool` wrapper using `get_settings()`, not in the impl
5. **Async throughout** — both the `@tool` function and `_impl` are `async`

### Error Handling

- `httpx.TimeoutException` → `ToolException("OpenEMR API timed out: ...")`
- `httpx.HTTPStatusError` → `ToolException("OpenEMR API error ({status}): {body}")`
- Business logic errors (no patients found, ambiguous matches) → return dict with `message` field, not exceptions

### Response Format

Returns a `dict[str, Any]` with structured data. Helper functions (e.g., `_format_appointment`) normalize raw API responses into the tool's output shape.

### Test Pattern

Tests at `ai-agent/tests/test_find_appointments.py`:
- Mock `OpenEMRClient` with `AsyncMock` and a `side_effect` function routing by URL path
- Test the `_impl` function directly (not the `@tool` wrapper) to avoid needing settings
- Helper functions like `_make_appointment()` and `_make_patient()` create test data with overrides
- `pytest.mark.asyncio` for async tests

---

## Available REST API Endpoints

### Standard API (scope: `user/encounter.read`)

| Endpoint | Params | Notes |
|----------|--------|-------|
| `GET /apis/default/api/patient/:puuid/encounter` | puuid (UUID) | List all encounters for patient |
| `GET /apis/default/api/patient/:puuid/encounter/:euuid` | puuid, euuid (UUIDs) | Single encounter detail |
| `GET /apis/default/api/patient/:pid/encounter/:eid/vital` | pid, eid (integers) | Vitals for encounter |
| `GET /apis/default/api/patient/:pid/encounter/:eid/soap_note` | pid, eid (integers) | SOAP notes for encounter |
| `GET /apis/default/api/patient` | fname, lname, pid params | Patient search/lookup |

### FHIR API (require additional scopes)

| Endpoint | Scope Required | Returns |
|----------|---------------|---------|
| `GET /apis/default/fhir/Condition?patient={puuid}` | `user/Condition.read` | Active problems/diagnoses |
| `GET /apis/default/fhir/MedicationRequest?patient={puuid}&status=active` | `user/MedicationRequest.read` | Current medications |
| `GET /apis/default/fhir/AllergyIntolerance?patient={puuid}` | `user/AllergyIntolerance.read` | Allergies |
| `GET /apis/default/fhir/Encounter?patient={puuid}` | (uses encounter scope) | Encounter in FHIR format |

### UUID vs Integer ID Inconsistency

**Critical finding:** The encounter list/detail endpoints use UUIDs (`puuid`, `euuid`), but the vitals and soap_note sub-resource endpoints use integer IDs (`pid`, `eid`).

The encounter response includes both:
- `id` (integer encounter ID)
- `uuid` (UUID string)
- `pid` (integer patient ID)

So after fetching an encounter by UUID, we can extract the integer IDs needed for vitals/SOAP calls.

### Missing: Billing REST API

There is **no billing REST API**. No `BillingRestController` or billing-specific REST endpoint exists. The `billing` table data (dx codes, CPT codes) is not exposed through any REST endpoint.

The encounter response does include some billing-adjacent fields:
- `billing_note` — free-text billing note
- `last_level_billed` — last billing level
- `last_level_closed` — last closed level
- `billing_facility` / `billing_facility_name`

---

## Data Structures & Database Tables

### form_encounter (encounter metadata)

| Column | Type | Description |
|--------|------|-------------|
| encounter | int | Encounter ID (PK) |
| date | datetime | Encounter date |
| pid | int | Patient ID (FK) |
| provider_id | int | Provider ID (FK → users) |
| facility_id | int | Facility ID (FK) |
| reason | text | Visit reason |
| class_code | varchar | e.g., 'AMB' for ambulatory |
| sensitivity | varchar | Sensitivity level |
| billing_note | text | Billing notes |

### form_soap (SOAP notes)

| Column | Type | Description |
|--------|------|-------------|
| id | int | SOAP note ID |
| pid | int | Patient ID |
| subjective | text | Subjective section |
| objective | text | Objective section |
| assessment | text | Assessment section |
| plan | text | Plan section |

Linked via `forms` table: `forms.encounter = form_encounter.encounter AND forms.form_id = form_soap.id AND forms.formdir = 'soap'`

### form_vitals

| Column | Type | Description |
|--------|------|-------------|
| id | int | Vitals form ID |
| pid | int | Patient ID |
| bps | varchar | Systolic BP |
| bpd | varchar | Diastolic BP |
| weight | varchar | Weight (lb) |
| height | varchar | Height (inches) |
| temperature | varchar | Temperature |
| pulse | varchar | Heart rate |
| respiration | varchar | Respiratory rate |
| oxygen_saturation | varchar | SpO2 |

### billing

| Column | Type | Description |
|--------|------|-------------|
| encounter | int | Encounter ID |
| code_type | varchar | e.g., 'ICD10', 'CPT4' |
| code | varchar | The billing code |
| modifier | varchar | Code modifier |
| units | int | Number of units |
| fee | decimal | Fee amount |

**Note:** This table has no REST API exposure.

---

## Encounter Response Shape (from API)

The standard API encounter response includes:
```
id, uuid, date, reason, facility, facility_id, pid,
provider_id, supervisor_id, class_code, class_title,
billing_note, last_level_billed, last_level_closed,
pc_catid, pc_catname, billing_facility, billing_facility_name,
onset_date, sensitivity, stmt_count, last_stmt_date
```

---

## OAuth Scopes

### Current scopes (`openemr_client.py`)

```
openid api:oemr user/appointment.read user/encounter.read user/patient.read
```

### Additional scopes needed

```
user/AllergyIntolerance.read
user/Condition.read
user/MedicationRequest.read
```

These must be added to `DEFAULT_SCOPES` in `ai-agent/ai_agent/openemr_client.py`. Adding scopes is backwards-compatible — existing tools will continue to work with the expanded scope set.

---

## Proposed Implementation Approach

### Input Schema

```python
class GetEncounterContextInput(BaseModel):
    encounter_id: Optional[int]  # direct encounter ID
    patient_id: Optional[int]    # patient ID, combined with date
    date: Optional[str]          # YYYY-MM-DD, used with patient_id
```

At least one of `encounter_id` or `patient_id` must be provided.

### Implementation Flow (`_get_encounter_context_impl`)

1. **Resolve patient UUID:**
   - `GET /api/patient?pid={patient_id}` to get patient UUID and demographics
   - Or if only `encounter_id` is given, `patient_id` is still required (see open questions)

2. **Resolve encounter:**
   - If `encounter_id` given: `GET /api/patient/{puuid}/encounter`, filter by `id == encounter_id`
   - If `patient_id` + `date`: same endpoint, filter by date
   - If multiple encounters match on same day → return list for clarification

3. **Fetch clinical context (parallel with `asyncio.gather`):**
   - `GET /fhir/Condition?patient={puuid}` → active problems
   - `GET /fhir/MedicationRequest?patient={puuid}&status=active` → medications
   - `GET /fhir/AllergyIntolerance?patient={puuid}` → allergies
   - `GET /api/patient/{pid}/encounter/{eid}/vital` → vitals
   - `GET /api/patient/{pid}/encounter/{eid}/soap_note` → existing notes

4. **Assemble structured response** matching the issue spec shape

### Error Handling

- No encounter found → `ToolException("No encounter found with ID {eid}")`
- Multiple encounters on same day → return list with clarification message
- Partial data (no vitals, no notes) → return `null`/empty fields gracefully
- API timeouts/errors → `ToolException` per existing pattern

---

## Open Questions & Decisions

### 1. Billing Status Data

**Problem:** No billing REST API exists. The `billing` table (dx/CPT codes) is not exposed.

**Options:**
- **(a)** Stub `billing_status` with empty arrays and a note that it's unavailable via API
- **(b)** Extract what we can from encounter response fields (`billing_note`, `last_level_billed`)
- **(c)** Skip `billing_status` entirely from v1

**Recommendation:** Option (b) — return available billing metadata from the encounter response, with empty `dx_codes`/`cpt_codes` arrays.

### 2. UUID Resolution Strategy

**Problem:** The issue spec says `encounter_id (int)` but the encounter API uses UUIDs.

**Approach:** Accept integer encounter IDs. Internally, list all encounters for the patient and match by integer `id` field to get the UUID. This requires `patient_id` to be provided alongside `encounter_id`.

### 3. Patient ID Requirement

**Problem:** If only `encounter_id` is given without `patient_id`, we can't look up the encounter (the API requires `puuid` in the path).

**Options:**
- **(a)** Require `patient_id` always — simplest, document it clearly
- **(b)** Try FHIR `Encounter` endpoint for global lookup — may work but adds complexity
- **(c)** Accept both `encounter_id` alone (FHIR lookup) and `patient_id+encounter_id` (standard API)

**Recommendation:** Option (a) for v1 — require `patient_id` and validate in the input schema.

### 4. FHIR Response Parsing

The FHIR endpoints return FHIR Bundle resources with nested structures. We'll need parser/normalizer functions to extract:
- Condition → `{code, description, onset_date}`
- MedicationRequest → `{drug_name, dose, frequency}`
- AllergyIntolerance → `{substance, reaction, severity}`

These are more complex than the standard API responses and will need careful mapping.
