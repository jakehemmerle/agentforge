#!/usr/bin/env python3
"""Seed the OpenEMR dev database with synthetic data for the AI agent demo.

Usage:
    python seed_data.py             # Insert seed data (idempotent)
    python seed_data.py --clean     # Delete existing seed data then re-insert
    python seed_data.py --sql-only  # Only run Phase 1 (SQL), skip REST API

Phase 1 (SQL): patients, appointments, encounters, vitals, SOAP notes,
               billing, insurance companies — direct MySQL inserts.
Phase 2 (REST API): medical problems, allergies, medications, insurance
                     policies — via OpenEMR REST API so data is properly
                     indexed for FHIR/REST reads.

Connects to MySQL via host/port from env vars or defaults suitable for
connecting from the host machine to the Docker dev environment.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

import httpx
import pymysql
import pymysql.cursors

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Keep defaults in sync with tests/integration/config.py
DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "8320")),
    "user": os.getenv("MYSQL_USER", "openemr"),
    "password": os.getenv("MYSQL_PASS", "openemr"),
    "database": os.getenv("MYSQL_DATABASE", "openemr"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

OPENEMR_BASE_URL = os.getenv("OPENEMR_BASE_URL", "http://localhost:8300")

PROVIDER_ID = 1  # admin user
FACILITY_ID = 3  # "Your Clinic Name Here" (default facility)
FACILITY_NAME = "Your Clinic Name Here"

# Patient IDs in a high range to avoid collisions
PIDS = list(range(90001, 90006))
ENCOUNTER_IDS = [900001, 900002, 900003, 900004, 900005]

# ---------------------------------------------------------------------------
# Dates — relative to today so data always looks fresh
# ---------------------------------------------------------------------------

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)
THREE_DAYS_AGO = TODAY - timedelta(days=3)


def _dt(d: date, hour: int = 10, minute: int = 0) -> str:
    """Format a date + time as a MySQL datetime string."""
    return datetime(d.year, d.month, d.day, hour, minute).strftime("%Y-%m-%d %H:%M:%S")


def _d(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Seed definitions
# ---------------------------------------------------------------------------

PATIENTS = [
    {
        "pid": 90001,
        "pubpid": "TEST001",
        "fname": "John",
        "lname": "Doe",
        "DOB": "1985-03-15",
        "sex": "Male",
        "street": "123 Main St",
        "city": "Anytown",
        "state": "CA",
        "postal_code": "90210",
        "phone_home": "555-0101",
        "phone_cell": "555-0102",
        "email": "john.doe@example.com",
    },
    {
        "pid": 90002,
        "pubpid": "TEST002",
        "fname": "Jane",
        "lname": "Smith",
        "DOB": "1990-07-22",
        "sex": "Female",
        "street": "456 Oak Ave",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62704",
        "phone_home": "555-0201",
        "phone_cell": "555-0202",
        "email": "jane.smith@example.com",
    },
    {
        "pid": 90003,
        "pubpid": "TEST003",
        "fname": "Robert",
        "lname": "Johnson",
        "DOB": "1978-11-03",
        "sex": "Male",
        "street": "789 Pine Rd",
        "city": "Riverside",
        "state": "CA",
        "postal_code": "92501",
        "phone_home": "555-0301",
        "phone_cell": "555-0302",
        "email": "robert.johnson@example.com",
    },
    {
        "pid": 90004,
        "pubpid": "TEST004",
        "fname": "Maria",
        "lname": "Garcia",
        "DOB": "1995-01-30",
        "sex": "Female",
        "street": "321 Elm St",
        "city": "Houston",
        "state": "TX",
        "postal_code": "77001",
        "phone_home": "555-0401",
        "phone_cell": "555-0402",
        "email": "maria.garcia@example.com",
    },
    {
        "pid": 90005,
        "pubpid": "TEST005",
        "fname": "James",
        "lname": "Wilson",
        "DOB": "1960-09-18",
        "sex": "Male",
        "street": "654 Maple Dr",
        "city": "Phoenix",
        "state": "AZ",
        "postal_code": "85001",
        "phone_home": "555-0501",
        "phone_cell": "555-0502",
        "email": "james.wilson@example.com",
    },
]


def _appointments() -> list[dict]:
    """Build appointment dicts with dates relative to today."""
    return [
        # 1. John Doe — today 2:00 PM — arrived (THE demo appointment)
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90001",
            "pc_title": "Office Visit",
            "pc_hometext": "Follow-up visit for cough",
            "pc_eventDate": _d(TODAY),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "14:00:00",
            "pc_endTime": "14:15:00",
            "pc_apptstatus": "@",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 2. John Doe — today 3:30 PM — scheduled
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90001",
            "pc_title": "Office Visit",
            "pc_hometext": "Routine check-up",
            "pc_eventDate": _d(TODAY),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "15:30:00",
            "pc_endTime": "15:45:00",
            "pc_apptstatus": "-",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 3. Jane Smith — today 10:00 AM — checked out
        {
            "pc_catid": 9,
            "pc_aid": "1",
            "pc_pid": "90002",
            "pc_title": "Established Patient",
            "pc_hometext": "Annual wellness exam",
            "pc_eventDate": _d(TODAY),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "10:00:00",
            "pc_endTime": "10:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 4. Jane Smith — tomorrow 9:00 AM — scheduled
        {
            "pc_catid": 9,
            "pc_aid": "1",
            "pc_pid": "90002",
            "pc_title": "Established Patient",
            "pc_hometext": "Follow-up labs review",
            "pc_eventDate": _d(TOMORROW),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "09:00:00",
            "pc_endTime": "09:15:00",
            "pc_apptstatus": "-",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 5. Robert Johnson — today 11:00 AM — checked out (has encounter 900003)
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90003",
            "pc_title": "Office Visit",
            "pc_hometext": "Back pain evaluation",
            "pc_eventDate": _d(TODAY),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "11:00:00",
            "pc_endTime": "11:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 6. Maria Garcia — today 1:00 PM — arrived (has encounter 900004)
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90004",
            "pc_title": "Office Visit",
            "pc_hometext": "Diabetes follow-up check",
            "pc_eventDate": _d(TODAY),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "13:00:00",
            "pc_endTime": "13:15:00",
            "pc_apptstatus": "@",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 7. James Wilson — today 4:00 PM — scheduled
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90005",
            "pc_title": "Office Visit",
            "pc_hometext": "Diabetes management follow-up",
            "pc_eventDate": _d(TODAY),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "16:00:00",
            "pc_endTime": "16:15:00",
            "pc_apptstatus": "-",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 8. John Doe — yesterday 10:00 AM — checked out (has encounter 900001)
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90001",
            "pc_title": "Office Visit",
            "pc_hometext": "Persistent cough evaluation",
            "pc_eventDate": _d(YESTERDAY),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "10:00:00",
            "pc_endTime": "10:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 9. Robert Johnson — 5 days ago — checked out (historical)
        {
            "pc_catid": 9,
            "pc_aid": "1",
            "pc_pid": "90003",
            "pc_title": "Established Patient",
            "pc_hometext": "Knee pain follow-up",
            "pc_eventDate": _d(TODAY - timedelta(days=5)),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "09:00:00",
            "pc_endTime": "09:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 10. James Wilson — 12 days ago — checked out (historical)
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90005",
            "pc_title": "Office Visit",
            "pc_hometext": "Blood pressure check",
            "pc_eventDate": _d(TODAY - timedelta(days=12)),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "14:00:00",
            "pc_endTime": "14:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 11. Maria Garcia — 20 days ago — checked out (historical)
        {
            "pc_catid": 9,
            "pc_aid": "1",
            "pc_pid": "90004",
            "pc_title": "Established Patient",
            "pc_hometext": "Allergy consultation",
            "pc_eventDate": _d(TODAY - timedelta(days=20)),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "11:00:00",
            "pc_endTime": "11:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 12. Jane Smith — 8 days ago — checked out (historical)
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90002",
            "pc_title": "Office Visit",
            "pc_hometext": "Sinus congestion",
            "pc_eventDate": _d(TODAY - timedelta(days=8)),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "15:00:00",
            "pc_endTime": "15:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 13. James Wilson — 3 days ago — checked out (has encounter 900005)
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90005",
            "pc_title": "Office Visit",
            "pc_hometext": "COPD exacerbation follow-up",
            "pc_eventDate": _d(THREE_DAYS_AGO),
            "pc_endDate": "0000-00-00",
            "pc_duration": 900,
            "pc_startTime": "14:00:00",
            "pc_endTime": "14:15:00",
            "pc_apptstatus": ">",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
    ]


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_UUID_EXPR = "UNHEX(REPLACE(UUID(),'-',''))"


def _exists(cur, table: str, column: str, value) -> bool:
    cur.execute(f"SELECT 1 FROM `{table}` WHERE `{column}` = %s LIMIT 1", (value,))
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------


def seed_patients(cur) -> None:
    print("Seeding patients …")
    for p in PATIENTS:
        if _exists(cur, "patient_data", "pubpid", p["pubpid"]):
            print(
                f"  Patient {p['pubpid']} ({p['fname']} {p['lname']}) exists, skipping"
            )
            continue
        cur.execute(
            f"""
            INSERT INTO patient_data
                (pid, pubpid, uuid, fname, lname, DOB, sex, street, city, state,
                 postal_code, phone_home, phone_cell, email, date, regdate, providerID)
            VALUES
                (%s, %s, {_UUID_EXPR}, %s, %s, %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, NOW(), NOW(), %s)
            """,
            (
                p["pid"],
                p["pubpid"],
                p["fname"],
                p["lname"],
                p["DOB"],
                p["sex"],
                p["street"],
                p["city"],
                p["state"],
                p["postal_code"],
                p["phone_home"],
                p["phone_cell"],
                p["email"],
                PROVIDER_ID,
            ),
        )
        print(f"  Inserted patient {p['pubpid']} ({p['fname']} {p['lname']})")


def seed_appointments(cur) -> None:
    print("Seeding appointments …")
    appts = _appointments()
    # Delete existing seed appointments for our PIDs so we can re-insert
    # with fresh dates. This makes the script idempotent for appointments
    # whose dates are relative to today.
    pids_str = ",".join(str(pid) for pid in PIDS)
    cur.execute(f"DELETE FROM openemr_postcalendar_events WHERE pc_pid IN ({pids_str})")
    deleted = cur.rowcount
    if deleted:
        print(f"  Cleared {deleted} existing seed appointments")

    for i, a in enumerate(appts, 1):
        cur.execute(
            f"""
            INSERT INTO openemr_postcalendar_events
                (uuid, pc_catid, pc_aid, pc_pid, pc_title, pc_time, pc_hometext,
                 pc_eventDate, pc_endDate, pc_duration, pc_startTime, pc_endTime,
                 pc_apptstatus, pc_facility, pc_billing_location, pc_eventstatus,
                 pc_sharing, pc_informant, pc_multiple)
            VALUES
                ({_UUID_EXPR}, %s, %s, %s, %s, NOW(), %s,
                 %s, %s, %s, %s, %s,
                 %s, %s, %s, %s,
                 %s, %s, %s)
            """,
            (
                a["pc_catid"],
                a["pc_aid"],
                a["pc_pid"],
                a["pc_title"],
                a["pc_hometext"],
                a["pc_eventDate"],
                a["pc_endDate"],
                a["pc_duration"],
                a["pc_startTime"],
                a["pc_endTime"],
                a["pc_apptstatus"],
                a["pc_facility"],
                a["pc_billing_location"],
                a["pc_eventstatus"],
                a["pc_sharing"],
                a["pc_informant"],
                a["pc_multiple"],
            ),
        )
        print(
            f"  [{i}/{len(appts)}] Appt: pid={a['pc_pid']} "
            f"date={a['pc_eventDate']} {a['pc_startTime']} status={a['pc_apptstatus']}"
        )


ENCOUNTERS = [
    {
        "encounter": 900001,
        "pid": 90001,
        "date": _dt(YESTERDAY, 10, 0),
        "reason": "Persistent cough for 3 days with low-grade fever",
        "pc_catid": 5,
    },
    {
        "encounter": 900002,
        "pid": 90002,
        "date": _dt(TODAY, 10, 0),
        "reason": "Annual wellness exam",
        "pc_catid": 9,
    },
    {
        "encounter": 900003,
        "pid": 90003,
        "date": _dt(TODAY, 11, 0),
        "reason": "Acute low back pain, worsening over 5 days",
        "pc_catid": 5,
    },
    {
        "encounter": 900004,
        "pid": 90004,
        "date": _dt(TODAY, 13, 0),
        "reason": "Diabetes follow-up with weight management and depression screen",
        "pc_catid": 5,
    },
    {
        "encounter": 900005,
        "pid": 90005,
        "date": _dt(THREE_DAYS_AGO, 14, 0),
        "reason": "COPD exacerbation follow-up with dyspnea and wheezing",
        "pc_catid": 5,
    },
]

# ---------------------------------------------------------------------------
# SOAP Notes — keyed by encounter_id (900002 intentionally omitted = sparse)
# ---------------------------------------------------------------------------

SOAP_NOTES = {
    900001: {
        "pid": 90001,
        "subjective": (
            "Patient reports persistent cough for 3 days with low-grade fever. "
            "No shortness of breath. Mild sore throat."
        ),
        "objective": (
            "Temp 99.8F, BP 128/82, HR 76, RR 16, SpO2 98%. "
            "Oropharynx mildly erythematous. "
            "Lungs clear to auscultation bilaterally."
        ),
        "assessment": "Acute upper respiratory infection (J06.9)",
        "plan": (
            "Rest and adequate fluids. OTC antipyretics for fever. "
            "Follow up in 1 week if symptoms persist or worsen."
        ),
    },
    900003: {
        "pid": 90003,
        "subjective": (
            "47-year-old male presents with low back pain for 5 days after "
            "lifting heavy boxes. Pain radiates to left buttock. Rates pain "
            "6/10. Denies numbness, tingling, or bowel/bladder changes. "
            "Ibuprofen provides partial relief."
        ),
        "objective": (
            "BP 122/78, HR 72. Lumbar paraspinal tenderness L4-L5. No midline "
            "tenderness. SLR negative bilaterally. Strength 5/5 lower "
            "extremities. Sensation intact. Gait normal."
        ),
        "assessment": (
            "1. Low back pain, acute (M54.5) - likely musculoskeletal strain\n"
            "2. Hyperlipidemia (E78.5) - stable on atorvastatin"
        ),
        "plan": (
            "1. Continue ibuprofen 600mg TID with food for 7 days\n"
            "2. Ice/heat alternating, gentle stretching\n"
            "3. Activity modification - avoid heavy lifting for 2 weeks\n"
            "4. Return if symptoms worsen or new neurological symptoms\n"
            "5. Continue atorvastatin 20mg daily"
        ),
    },
    900004: {
        "pid": 90004,
        "subjective": (
            "30-year-old female presents for diabetes follow-up. Reports "
            "increased thirst and urinary frequency over past 2 weeks. Admits "
            "difficulty with dietary adherence. Mood has been low with "
            "decreased energy and poor sleep for 1 month. Current medications: "
            "metformin 500mg BID, omeprazole 20mg daily, fluoxetine 20mg daily."
        ),
        "objective": (
            "BP 142/90, HR 84, Wt 248 lbs (up 5 lbs from 3 months ago), "
            "BMI 42.5. Alert, appears fatigued. Skin warm and dry. No "
            "acanthosis nigricans. Cardiopulmonary exam unremarkable. "
            "Extremities: no edema, pulses intact."
        ),
        "assessment": (
            "1. Type 2 DM with hyperglycemia (E11.65) - poorly controlled\n"
            "2. Morbid obesity (E66.01) - BMI 42.5, weight gain\n"
            "3. GERD (K21.0) - stable on omeprazole\n"
            "4. Major depressive disorder, moderate (F32.1) - persistent symptoms"
        ),
        "plan": (
            "1. Increase metformin to 1000mg BID if tolerated, recheck A1c "
            "in 3 months\n"
            "2. Nutrition referral for medical weight management\n"
            "3. PHQ-9 score 14 - consider increasing fluoxetine to 40mg, "
            "follow up in 4 weeks\n"
            "4. Continue omeprazole 20mg daily\n"
            "5. Labs: A1c, fasting lipid panel, comprehensive metabolic panel"
        ),
    },
    900005: {
        "pid": 90005,
        "subjective": (
            "65-year-old male with COPD, CHF, and afib presents for follow-up "
            "after COPD exacerbation 1 week ago. Reports improved breathing but "
            "still using albuterol 3-4 times daily. Mild bilateral ankle "
            "swelling. Takes all medications as prescribed. Denies chest pain, "
            "palpitations, or fever."
        ),
        "objective": (
            "BP 138/86, HR 92 (irregularly irregular), RR 22, Temp 98.2F, "
            "SpO2 93% on room air, Wt 165 lbs. Lungs: scattered expiratory "
            "wheezes bilaterally, no crackles. Heart: irregular rhythm, no "
            "murmurs. Extremities: 1+ bilateral ankle edema. No JVD."
        ),
        "assessment": (
            "1. COPD exacerbation, resolving (J44.1)\n"
            "2. Congestive heart failure (I50.9) - mild fluid retention\n"
            "3. Atrial fibrillation (I48.91) - rate controlled\n"
            "4. Type 2 diabetes (E11.9) - stable\n"
            "5. CKD stage 3 (N18.3) - baseline creatinine 1.8"
        ),
        "plan": (
            "1. Continue albuterol PRN, expect to wean over 1-2 weeks\n"
            "2. Increase furosemide to 60mg daily for 5 days then return "
            "to 40mg\n"
            "3. Continue warfarin 5mg, INR due next week\n"
            "4. Continue metformin 500mg daily (reduced dose for CKD)\n"
            "5. Continue amlodipine 5mg daily\n"
            "6. Recheck in 2 weeks, sooner if worsening dyspnea or edema"
        ),
    },
}

# ---------------------------------------------------------------------------
# Vitals — keyed by encounter_id (900002 intentionally omitted = sparse)
# ---------------------------------------------------------------------------

VITALS = {
    900001: {
        "pid": 90001,
        "bps": "128",
        "bpd": "82",
        "weight": 180.0,
        "height": 70.0,
        "temperature": 99.8,
        "temp_method": "Oral",
        "pulse": 76.0,
        "respiration": 16.0,
        "oxygen_saturation": 98.0,
    },
    900003: {
        "pid": 90003,
        "bps": "122",
        "bpd": "78",
        "weight": 195.0,
        "height": 72.0,
        "temperature": 98.6,
        "temp_method": "Oral",
        "pulse": 72.0,
        "respiration": 14.0,
        "oxygen_saturation": 99.0,
    },
    900004: {
        "pid": 90004,
        "bps": "142",
        "bpd": "90",
        "weight": 248.0,
        "height": 64.0,
        "temperature": 98.4,
        "temp_method": "Oral",
        "pulse": 84.0,
        "respiration": 18.0,
        "oxygen_saturation": 97.0,
    },
    900005: {
        "pid": 90005,
        "bps": "138",
        "bpd": "86",
        "weight": 165.0,
        "height": 68.0,
        "temperature": 98.2,
        "temp_method": "Oral",
        "pulse": 92.0,
        "respiration": 22.0,
        "oxygen_saturation": 93.0,
    },
}

# ---------------------------------------------------------------------------
# Billing — keyed by encounter_id
# ---------------------------------------------------------------------------

BILLING = {
    900001: {
        "pid": 90001,
        "rows": [
            {
                "code_type": "ICD10",
                "code": "J06.9",
                "code_text": "Acute upper respiratory infection, unspecified",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "E11.9",
                "code_text": "Type 2 diabetes mellitus without complications",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "I10",
                "code_text": "Essential (primary) hypertension",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "CPT4",
                "code": "99213",
                "code_text": "Office/outpatient visit, est patient, low complexity",
                "fee": 75.00,
                "justify": "J06.9:",
                "modifier": "",
            },
        ],
    },
    900002: {
        "pid": 90002,
        "rows": [
            {
                "code_type": "CPT4",
                "code": "99214",
                "code_text": "Office/outpatient visit, est patient, moderate complexity",
                "fee": 110.00,
                "justify": "",
                "modifier": "",
            },
        ],
    },
    900003: {
        "pid": 90003,
        "rows": [
            {
                "code_type": "ICD10",
                "code": "M54.5",
                "code_text": "Low back pain, unspecified",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "E78.5",
                "code_text": "Hyperlipidemia, unspecified",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "CPT4",
                "code": "99213",
                "code_text": "Office/outpatient visit, est patient, low complexity",
                "fee": 75.00,
                "justify": "M54.5:",
                "modifier": "",
            },
            {
                "code_type": "CPT4",
                "code": "72100",
                "code_text": "Radiologic exam, lumbar spine, 2-3 views",
                "fee": 85.00,
                "justify": "M54.5:",
                "modifier": "",
            },
        ],
    },
    900004: {
        "pid": 90004,
        "rows": [
            {
                "code_type": "ICD10",
                "code": "E11.65",
                "code_text": "Type 2 DM with hyperglycemia",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "E66.01",
                "code_text": "Morbid (severe) obesity due to excess calories",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "K21.0",
                "code_text": "GERD with esophagitis",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "F32.1",
                "code_text": "Major depressive disorder, single episode, moderate",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "CPT4",
                "code": "99214",
                "code_text": "Office/outpatient visit, est patient, moderate complexity",
                "fee": 110.00,
                "justify": "E11.65:",
                "modifier": "",
            },
            {
                "code_type": "CPT4",
                "code": "96127",
                "code_text": "Brief emotional/behavioral assessment",
                "fee": 12.00,
                "justify": "F32.1:",
                "modifier": "",
            },
        ],
    },
    900005: {
        "pid": 90005,
        "rows": [
            {
                "code_type": "ICD10",
                "code": "J44.1",
                "code_text": "COPD with acute exacerbation",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "I50.9",
                "code_text": "Heart failure, unspecified",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "I48.91",
                "code_text": "Unspecified atrial fibrillation",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "E11.9",
                "code_text": "Type 2 diabetes mellitus without complications",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "ICD10",
                "code": "N18.3",
                "code_text": "Chronic kidney disease, stage 3",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            {
                "code_type": "CPT4",
                "code": "99215",
                "code_text": "Office/outpatient visit, est patient, high complexity",
                "fee": 150.00,
                "justify": "J44.1:",
                "modifier": "",
            },
            {
                "code_type": "CPT4",
                "code": "94640",
                "code_text": "Pressurized/nonpressurized inhalation treatment",
                "fee": 35.00,
                "justify": "J44.1:",
                "modifier": "",
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# Insurance companies (SQL Phase 1)
# ---------------------------------------------------------------------------

INSURANCE_COMPANIES = [
    {
        "id": 99001,
        "name": "Blue Cross Blue Shield",
        "cms_id": "BCBS001",
        "ins_type_code": 6,
    },
    {"id": 99002, "name": "United Healthcare", "cms_id": "UHC001", "ins_type_code": 17},
    {"id": 99003, "name": "Cigna Health", "cms_id": "CIGNA01", "ins_type_code": 17},
    {"id": 99004, "name": "Medicare", "cms_id": "MCARE01", "ins_type_code": 2},
    {"id": 99005, "name": "Aetna", "cms_id": "AETNA01", "ins_type_code": 17},
]

# ---------------------------------------------------------------------------
# Clinical data for REST API seeding (Phase 2)
# ---------------------------------------------------------------------------

MEDICAL_PROBLEMS: dict[int, list[dict]] = {
    90001: [
        {
            "title": "Acute upper respiratory infection, unspecified",
            "begdate": _d(YESTERDAY),
            "diagnosis": "ICD10:J06.9",
        },
        {
            "title": "Type 2 diabetes mellitus without complications",
            "begdate": "2020-06-15",
            "diagnosis": "ICD10:E11.9",
        },
        {
            "title": "Essential (primary) hypertension",
            "begdate": "2019-03-20",
            "diagnosis": "ICD10:I10",
        },
    ],
    90002: [
        {
            "title": "Allergic rhinitis, unspecified",
            "begdate": "2018-04-10",
            "diagnosis": "ICD10:J30.9",
        },
        {
            "title": "Generalized anxiety disorder",
            "begdate": "2021-09-01",
            "diagnosis": "ICD10:F41.1",
        },
    ],
    90003: [
        {
            "title": "Low back pain, unspecified",
            "begdate": _d(TODAY - timedelta(days=5)),
            "diagnosis": "ICD10:M54.5",
        },
        {
            "title": "Hyperlipidemia, unspecified",
            "begdate": "2022-01-20",
            "diagnosis": "ICD10:E78.5",
        },
    ],
    90004: [
        {
            "title": "Type 2 DM with hyperglycemia",
            "begdate": "2021-03-15",
            "diagnosis": "ICD10:E11.65",
        },
        {
            "title": "Morbid (severe) obesity due to excess calories",
            "begdate": "2020-08-01",
            "diagnosis": "ICD10:E66.01",
        },
        {
            "title": "GERD with esophagitis",
            "begdate": "2022-05-10",
            "diagnosis": "ICD10:K21.0",
        },
        {
            "title": "Major depressive disorder, single episode, moderate",
            "begdate": "2023-01-20",
            "diagnosis": "ICD10:F32.1",
        },
    ],
    90005: [
        {
            "title": "COPD with acute exacerbation",
            "begdate": _d(TODAY - timedelta(days=10)),
            "diagnosis": "ICD10:J44.1",
        },
        {
            "title": "Heart failure, unspecified",
            "begdate": "2019-11-15",
            "diagnosis": "ICD10:I50.9",
        },
        {
            "title": "Unspecified atrial fibrillation",
            "begdate": "2020-02-28",
            "diagnosis": "ICD10:I48.91",
        },
        {
            "title": "Type 2 diabetes mellitus without complications",
            "begdate": "2015-06-01",
            "diagnosis": "ICD10:E11.9",
        },
        {
            "title": "Chronic kidney disease, stage 3",
            "begdate": "2022-09-15",
            "diagnosis": "ICD10:N18.3",
        },
    ],
}

ALLERGIES: dict[int, list[dict]] = {
    90001: [
        {"title": "Penicillin", "reaction": "rash", "begdate": "2010-01-01"},
    ],
    90002: [
        {"title": "Latex", "reaction": "contact dermatitis", "begdate": "2015-06-01"},
    ],
    # 90003: NKDA — no entries
    90004: [
        {"title": "Sulfa drugs", "reaction": "hives", "begdate": "2018-03-15"},
        {
            "title": "Iodine contrast dye",
            "reaction": "anaphylaxis",
            "begdate": "2019-07-20",
        },
    ],
    90005: [
        {"title": "Aspirin", "reaction": "GI bleeding", "begdate": "2017-11-01"},
        {
            "title": "Codeine",
            "reaction": "nausea and vomiting",
            "begdate": "2012-05-15",
        },
    ],
}

MEDICATIONS: dict[int, list[dict]] = {
    90001: [
        {
            "drug": "Metformin 1000mg",
            "dosage": "1000mg",
            "size": "1000",
            "unit": "mg",
            "route": "by mouth",
            "interval": "twice a day",
            "begdate": "2020-06-15",
        },
        {
            "drug": "Lisinopril 10mg",
            "dosage": "10mg",
            "size": "10",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2019-03-20",
        },
    ],
    90002: [
        {
            "drug": "Cetirizine 10mg",
            "dosage": "10mg",
            "size": "10",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2018-04-10",
        },
        {
            "drug": "Sertraline 50mg",
            "dosage": "50mg",
            "size": "50",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2021-09-01",
        },
    ],
    90003: [
        {
            "drug": "Ibuprofen 600mg",
            "dosage": "600mg",
            "size": "600",
            "unit": "mg",
            "route": "by mouth",
            "interval": "three times a day",
            "begdate": _d(TODAY - timedelta(days=5)),
        },
        {
            "drug": "Atorvastatin 20mg",
            "dosage": "20mg",
            "size": "20",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2022-01-20",
        },
    ],
    90004: [
        {
            "drug": "Metformin 500mg",
            "dosage": "500mg",
            "size": "500",
            "unit": "mg",
            "route": "by mouth",
            "interval": "twice a day",
            "begdate": "2021-03-15",
        },
        {
            "drug": "Omeprazole 20mg",
            "dosage": "20mg",
            "size": "20",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2022-05-10",
        },
        {
            "drug": "Fluoxetine 20mg",
            "dosage": "20mg",
            "size": "20",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2023-01-20",
        },
    ],
    90005: [
        {
            "drug": "Albuterol inhaler",
            "dosage": "2 puffs",
            "size": "2",
            "unit": "puffs",
            "route": "inhaled",
            "interval": "every 4 hours",
            "begdate": "2018-05-01",
        },
        {
            "drug": "Furosemide 40mg",
            "dosage": "40mg",
            "size": "40",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2019-11-15",
        },
        {
            "drug": "Warfarin 5mg",
            "dosage": "5mg",
            "size": "5",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2020-02-28",
        },
        {
            "drug": "Metformin 500mg",
            "dosage": "500mg",
            "size": "500",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2015-06-01",
        },
        {
            "drug": "Amlodipine 5mg",
            "dosage": "5mg",
            "size": "5",
            "unit": "mg",
            "route": "by mouth",
            "interval": "once a day",
            "begdate": "2020-06-01",
        },
    ],
}

# Insurance policies — keyed by pid. 90002 intentionally omitted (no insurance).
INSURANCE_POLICIES: dict[int, dict] = {
    90001: {
        "type": "primary",
        "provider": "99001",
        "plan_name": "Blue Cross PPO",
        "policy_number": "BCBS-90001-A",
        "group_number": "GRP-BCBS-001",
        "subscriber_lname": "Doe",
        "subscriber_fname": "John",
        "subscriber_DOB": "1985-03-15",
        "subscriber_relationship": "self",
        "date": "2024-01-01",
    },
    90003: {
        "type": "primary",
        "provider": "99002",
        "plan_name": "United Choice Plus POS",
        "policy_number": "UHC-90003-B",
        "group_number": "GRP-UHC-042",
        "subscriber_lname": "Johnson",
        "subscriber_fname": "Robert",
        "subscriber_DOB": "1978-11-03",
        "subscriber_relationship": "self",
        "date": "2024-01-01",
    },
    90004: {
        "type": "primary",
        "provider": "99003",
        "plan_name": "Cigna Open Access Plus",
        "policy_number": "CIG-90004-C",
        "group_number": "GRP-CIG-078",
        "subscriber_lname": "Garcia",
        "subscriber_fname": "Maria",
        "subscriber_DOB": "1995-01-30",
        "subscriber_relationship": "self",
        "date": "2024-01-01",
    },
    90005: {
        "type": "primary",
        "provider": "99004",
        "plan_name": "Medicare Part B",
        "policy_number": "1EG4-TE5-MK72",
        "group_number": "",
        "subscriber_lname": "Wilson",
        "subscriber_fname": "James",
        "subscriber_DOB": "1960-09-18",
        "subscriber_relationship": "self",
        "date": "2023-01-01",
    },
}


# ---------------------------------------------------------------------------
# Phase 1: SQL seed functions
# ---------------------------------------------------------------------------


def seed_encounters(cur) -> None:
    """Seed encounters with forms registry entries."""
    print("Seeding encounters …")

    for enc in ENCOUNTERS:
        if _exists(cur, "form_encounter", "encounter", enc["encounter"]):
            print(f"  Encounter {enc['encounter']} exists, skipping")
            continue

        # Step 1: Insert form_encounter
        cur.execute(
            f"""
            INSERT INTO form_encounter
                (uuid, date, reason, facility, facility_id, pid, encounter,
                 pc_catid, provider_id, billing_facility, pos_code, class_code)
            VALUES
                ({_UUID_EXPR}, %s, %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s)
            """,
            (
                enc["date"],
                enc["reason"],
                FACILITY_NAME,
                FACILITY_ID,
                enc["pid"],
                enc["encounter"],
                enc["pc_catid"],
                PROVIDER_ID,
                FACILITY_ID,
                11,  # pos_code: Office
                "AMB",
            ),
        )
        form_encounter_id = cur.lastrowid

        # Step 2: Register in forms table
        cur.execute(
            """
            INSERT INTO forms
                (date, encounter, form_name, form_id, pid, user, groupname,
                 authorized, deleted, formdir, provider_id)
            VALUES
                (NOW(), %s, 'New Patient Encounter', %s, %s, 'admin', 'Default',
                 1, 0, 'newpatient', %s)
            """,
            (enc["encounter"], form_encounter_id, enc["pid"], PROVIDER_ID),
        )
        print(f"  Inserted encounter {enc['encounter']} for pid={enc['pid']}")


def seed_soap_notes(cur) -> None:
    """Seed SOAP notes for all encounters in the SOAP_NOTES dict."""
    print("Seeding SOAP notes …")

    for encounter_id, note in SOAP_NOTES.items():
        pid = note["pid"]

        cur.execute(
            "SELECT 1 FROM forms WHERE encounter = %s AND formdir = 'soap' LIMIT 1",
            (encounter_id,),
        )
        if cur.fetchone():
            print(f"  SOAP note for encounter {encounter_id} exists, skipping")
            continue

        cur.execute(
            """
            INSERT INTO form_soap
                (date, pid, user, groupname, authorized, activity,
                 subjective, objective, assessment, plan)
            VALUES
                (NOW(), %s, 'admin', 'Default', 1, 1, %s, %s, %s, %s)
            """,
            (
                pid,
                note["subjective"],
                note["objective"],
                note["assessment"],
                note["plan"],
            ),
        )
        soap_id = cur.lastrowid

        cur.execute(
            """
            INSERT INTO forms
                (date, encounter, form_name, form_id, pid, user, groupname,
                 authorized, deleted, formdir, provider_id)
            VALUES
                (NOW(), %s, 'SOAP', %s, %s, 'admin', 'Default',
                 1, 0, 'soap', %s)
            """,
            (encounter_id, soap_id, pid, PROVIDER_ID),
        )
        print(f"  Inserted SOAP note for encounter {encounter_id}")


def seed_all_vitals(cur) -> None:
    """Seed vitals for all encounters in the VITALS dict."""
    print("Seeding vitals …")

    for encounter_id, v in VITALS.items():
        pid = v["pid"]

        cur.execute(
            "SELECT 1 FROM forms WHERE encounter = %s AND formdir = 'vitals' LIMIT 1",
            (encounter_id,),
        )
        if cur.fetchone():
            print(f"  Vitals for encounter {encounter_id} exist, skipping")
            continue

        cur.execute(
            f"""
            INSERT INTO form_vitals
                (uuid, date, pid, user, groupname, authorized, activity,
                 bps, bpd, weight, height, temperature, temp_method,
                 pulse, respiration, oxygen_saturation)
            VALUES
                ({_UUID_EXPR}, NOW(), %s, 'admin', 'Default', 1, 1,
                 %s, %s, %s, %s, %s, %s,
                 %s, %s, %s)
            """,
            (
                pid,
                v["bps"],
                v["bpd"],
                v["weight"],
                v["height"],
                v["temperature"],
                v["temp_method"],
                v["pulse"],
                v["respiration"],
                v["oxygen_saturation"],
            ),
        )
        vitals_id = cur.lastrowid

        cur.execute(
            """
            INSERT INTO forms
                (date, encounter, form_name, form_id, pid, user, groupname,
                 authorized, deleted, formdir, provider_id)
            VALUES
                (NOW(), %s, 'Vitals', %s, %s, 'admin', 'Default',
                 1, 0, 'vitals', %s)
            """,
            (encounter_id, vitals_id, pid, PROVIDER_ID),
        )
        print(f"  Inserted vitals for encounter {encounter_id}")


def seed_billing(cur) -> None:
    """Seed billing codes for all encounters in the BILLING dict.

    900001: COMPLETE (3x ICD-10 + 1x CPT)
    900002: INCOMPLETE (CPT only, no ICD-10 — for validate_claim demo)
    900003: COMPLETE (2x ICD-10 + 2x CPT)
    900004: COMPLETE (4x ICD-10 + 2x CPT)
    900005: COMPLETE (5x ICD-10 + 2x CPT)
    """
    print("Seeding billing …")

    for enc_id, enc_data in BILLING.items():
        pid = enc_data["pid"]
        rows = enc_data["rows"]

        cur.execute("SELECT 1 FROM billing WHERE encounter = %s LIMIT 1", (enc_id,))
        if cur.fetchone():
            print(f"  Billing for encounter {enc_id} exists, skipping")
            continue

        for row in rows:
            cur.execute(
                """
                INSERT INTO billing
                    (date, code_type, code, code_text, pid, provider_id, user,
                     groupname, authorized, encounter, billed, activity,
                     units, fee, justify, modifier)
                VALUES
                    (NOW(), %s, %s, %s, %s, %s, %s,
                     'Default', 1, %s, 0, 1,
                     1, %s, %s, %s)
                """,
                (
                    row["code_type"],
                    row["code"],
                    row["code_text"],
                    pid,
                    PROVIDER_ID,
                    PROVIDER_ID,
                    enc_id,
                    row["fee"],
                    row["justify"],
                    row["modifier"],
                ),
            )

        icd_count = sum(1 for r in rows if r["code_type"] == "ICD10")
        cpt_count = sum(1 for r in rows if r["code_type"] == "CPT4")
        print(
            f"  Inserted billing for encounter {enc_id} "
            f"({icd_count}x ICD-10 + {cpt_count}x CPT)"
        )


def seed_insurance_companies(cur) -> None:
    """Seed insurance company records."""
    print("Seeding insurance companies …")

    for ic in INSURANCE_COMPANIES:
        if _exists(cur, "insurance_companies", "id", ic["id"]):
            print(f"  Insurance company {ic['id']} ({ic['name']}) exists, skipping")
            continue

        cur.execute(
            """
            INSERT INTO insurance_companies (id, name, cms_id, ins_type_code)
            VALUES (%s, %s, %s, %s)
            """,
            (ic["id"], ic["name"], ic["cms_id"], ic["ins_type_code"]),
        )
        print(f"  Inserted insurance company {ic['id']} ({ic['name']})")


# ---------------------------------------------------------------------------
# Phase 2: REST API seeder
# ---------------------------------------------------------------------------

SEEDER_CLIENT_NAME = "seed-data-client"
SEEDER_SCOPES = (
    "openid api:oemr "
    "user/patient.read "
    "user/medical_problem.write "
    "user/allergy.write "
    "user/medication.write "
    "user/insurance.write"
)


class OpenEMRSeeder:
    """Seeds clinical data via OpenEMR REST API for FHIR-compatible records."""

    def __init__(self, base_url: str, db_conn: pymysql.connections.Connection):
        self.base_url = base_url.rstrip("/")
        self.db_conn = db_conn
        self.client_id = ""
        self.client_secret = ""
        self.access_token = ""
        self._http = httpx.Client(base_url=self.base_url, timeout=30)
        self._patient_uuids: dict[int, str] = {}

    def close(self) -> None:
        self._http.close()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _api_get(self, path: str, params: dict | None = None) -> dict:
        resp = self._http.get(path, params=params, headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, path: str, json_data: dict) -> dict:
        resp = self._http.post(path, json=json_data, headers=self._auth_headers())
        if resp.status_code >= 400:
            print(f"    POST {path} failed ({resp.status_code}): {resp.text[:200]}")
        resp.raise_for_status()
        return resp.json()

    def register_and_authenticate(self) -> None:
        """Register an OAuth2 client with write scopes, enable it, get token."""
        # Clean up any previous seed client
        with self.db_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM oauth_clients WHERE client_name = %s",
                (SEEDER_CLIENT_NAME,),
            )
        self.db_conn.commit()

        # Register
        resp = self._http.post(
            "/oauth2/default/registration",
            json={
                "application_type": "private",
                "client_name": SEEDER_CLIENT_NAME,
                "redirect_uris": ["https://localhost"],
                "scope": SEEDER_SCOPES,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self.client_id = data["client_id"]
        self.client_secret = data.get("client_secret", "")

        # Enable client in DB
        with self.db_conn.cursor() as cur:
            cur.execute(
                "UPDATE oauth_clients SET is_enabled=1 WHERE client_name=%s",
                (SEEDER_CLIENT_NAME,),
            )
        self.db_conn.commit()

        # Get token
        resp = self._http.post(
            "/oauth2/default/token",
            data={
                "grant_type": "password",
                "username": "admin",
                "password": "pass",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": SEEDER_SCOPES,
                "user_role": "users",
            },
        )
        resp.raise_for_status()
        self.access_token = resp.json()["access_token"]

    def lookup_patient_uuids(self) -> None:
        """Resolve PIDs to UUIDs via REST API."""
        for pid in PIDS:
            data = self._api_get("/apis/default/api/patient", params={"pid": pid})
            patients = data.get("data", [])
            if not patients:
                raise RuntimeError(f"Patient pid={pid} not found via REST API")
            self._patient_uuids[pid] = patients[0]["uuid"]

    def seed_medical_problems(self) -> None:
        print("Seeding medical problems …")
        for pid, problems in MEDICAL_PROBLEMS.items():
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM lists "
                    "WHERE pid=%s AND type='medical_problem'",
                    (pid,),
                )
                count = cur.fetchone()["cnt"]
            if count > 0:
                print(f"  Medical problems for pid={pid} exist ({count}), skipping")
                continue

            puuid = self._patient_uuids[pid]
            for prob in problems:
                self._api_post(
                    f"/apis/default/api/patient/{puuid}/medical_problem", prob
                )
            print(f"  Inserted {len(problems)} medical problems for pid={pid}")

    def seed_allergies(self) -> None:
        print("Seeding allergies …")
        for pid, allergies in ALLERGIES.items():
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM lists WHERE pid=%s AND type='allergy'",
                    (pid,),
                )
                count = cur.fetchone()["cnt"]
            if count > 0:
                print(f"  Allergies for pid={pid} exist ({count}), skipping")
                continue

            puuid = self._patient_uuids[pid]
            for allergy in allergies:
                self._api_post(f"/apis/default/api/patient/{puuid}/allergy", allergy)
            print(f"  Inserted {len(allergies)} allergies for pid={pid}")

    def seed_medications(self) -> None:
        print("Seeding medications …")
        for pid, meds in MEDICATIONS.items():
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM prescriptions WHERE patient_id=%s",
                    (pid,),
                )
                count = cur.fetchone()["cnt"]
            if count > 0:
                print(f"  Medications for pid={pid} exist ({count}), skipping")
                continue

            puuid = self._patient_uuids[pid]
            for med in meds:
                self._api_post(f"/apis/default/api/patient/{puuid}/medication", med)
            print(f"  Inserted {len(meds)} medications for pid={pid}")

    def seed_insurance_policies(self) -> None:
        print("Seeding insurance policies …")
        for pid, policy in INSURANCE_POLICIES.items():
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM insurance_data WHERE pid=%s",
                    (pid,),
                )
                count = cur.fetchone()["cnt"]
            if count > 0:
                print(f"  Insurance for pid={pid} exists ({count}), skipping")
                continue

            puuid = self._patient_uuids[pid]
            self._api_post(f"/apis/default/api/patient/{puuid}/insurance", policy)
            print(f"  Inserted insurance for pid={pid}")

    def seed_all(self) -> None:
        """Run the full REST API seeding pipeline."""
        print("\n--- Phase 2: REST API seeding ---")

        print("Registering OAuth client for seeding …")
        self.register_and_authenticate()
        print(f"  OAuth client registered ({self.client_id[:20]}…)")

        print("Looking up patient UUIDs …")
        self.lookup_patient_uuids()
        print(f"  Found UUIDs for {len(self._patient_uuids)} patients")

        self.seed_medical_problems()
        self.seed_allergies()
        self.seed_medications()
        self.seed_insurance_policies()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def clean_seed_data(cur) -> None:
    """Delete all seed data (PIDs 90001-90005, encounters 900001-900005)."""
    print("Cleaning seed data …")

    pids_str = ",".join(str(pid) for pid in PIDS)
    enc_str = ",".join(str(eid) for eid in ENCOUNTER_IDS)
    ins_co_ids = ",".join(str(ic["id"]) for ic in INSURANCE_COMPANIES)

    deletes = [
        ("billing", f"encounter IN ({enc_str})"),
        ("forms", f"encounter IN ({enc_str})"),
        ("form_soap", f"pid IN ({pids_str})"),
        ("form_vitals", f"pid IN ({pids_str})"),
        ("form_encounter", f"encounter IN ({enc_str})"),
        ("openemr_postcalendar_events", f"pc_pid IN ({pids_str})"),
        # Phase 2 data (REST API created)
        ("lists", f"pid IN ({pids_str})"),
        ("prescriptions", f"patient_id IN ({pids_str})"),
        ("insurance_data", f"pid IN ({pids_str})"),
        ("insurance_companies", f"id IN ({ins_co_ids})"),
        # Must be last: patients
        ("patient_data", f"pid IN ({pids_str})"),
    ]

    for table, where in deletes:
        cur.execute(f"DELETE FROM `{table}` WHERE {where}")
        if cur.rowcount:
            print(f"  Deleted {cur.rowcount} rows from {table}")

    # Clean up seed OAuth client
    cur.execute(
        "DELETE FROM oauth_clients WHERE client_name = %s",
        (SEEDER_CLIENT_NAME,),
    )
    if cur.rowcount:
        print("  Deleted seed OAuth client")

    print("Cleanup complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed OpenEMR dev database")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing seed data before inserting",
    )
    parser.add_argument(
        "--sql-only",
        action="store_true",
        help="Only run Phase 1 (SQL), skip REST API seeding",
    )
    args = parser.parse_args()

    print(f"Connecting to MySQL at {DB_CONFIG['host']}:{DB_CONFIG['port']} …")
    try:
        conn = pymysql.connect(**DB_CONFIG)
    except pymysql.err.OperationalError as e:
        print(f"Error: Could not connect to MySQL: {e}", file=sys.stderr)
        print(
            "Ensure Docker is running and MySQL is accessible on "
            f"{DB_CONFIG['host']}:{DB_CONFIG['port']}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            if args.clean:
                clean_seed_data(cur)
                conn.commit()

            # Phase 1: SQL seeding
            print("\n--- Phase 1: SQL seeding ---")
            seed_patients(cur)
            seed_appointments(cur)
            seed_encounters(cur)
            seed_soap_notes(cur)
            seed_all_vitals(cur)
            seed_billing(cur)
            seed_insurance_companies(cur)
            conn.commit()
            print("\nPhase 1 (SQL) complete!")

        # Phase 2: REST API seeding
        if not args.sql_only:
            seeder = OpenEMRSeeder(OPENEMR_BASE_URL, conn)
            try:
                seeder.seed_all()
            finally:
                seeder.close()
            print("\nPhase 2 (REST API) complete!")

        print("\nSeed data complete!")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
