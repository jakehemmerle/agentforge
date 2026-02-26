#!/usr/bin/env python3
"""Seed the OpenEMR dev database with synthetic data for the AI agent demo.

Usage:
    python seed_data.py             # Insert seed data (idempotent)
    python seed_data.py --clean     # Delete existing seed data then re-insert

Connects to MySQL via host/port from env vars or defaults suitable for
connecting from the host machine to the Docker dev environment.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

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

PROVIDER_ID = 1  # admin user
FACILITY_ID = 3  # "Your Clinic Name Here" (default facility)
FACILITY_NAME = "Your Clinic Name Here"

# Patient IDs in a high range to avoid collisions
PIDS = list(range(90001, 90006))
ENCOUNTER_IDS = [900001, 900002]

# ---------------------------------------------------------------------------
# Dates — relative to today so data always looks fresh
# ---------------------------------------------------------------------------

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def _dt(d: date, hour: int = 10, minute: int = 0) -> str:
    """Format a date + time as a MySQL datetime string."""
    return datetime(d.year, d.month, d.day, hour, minute).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


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
        # 5. Robert Johnson — today 11:00 AM — cancelled
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
            "pc_apptstatus": "x",
            "pc_facility": FACILITY_ID,
            "pc_billing_location": FACILITY_ID,
            "pc_eventstatus": 1,
            "pc_sharing": 1,
            "pc_informant": "1",
            "pc_multiple": 0,
        },
        # 6. Maria Garcia — today 1:00 PM — arrived
        {
            "pc_catid": 5,
            "pc_aid": "1",
            "pc_pid": "90004",
            "pc_title": "Office Visit",
            "pc_hometext": "Headache and fatigue",
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
            print(f"  Patient {p['pubpid']} ({p['fname']} {p['lname']}) exists, skipping")
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
    cur.execute(
        f"DELETE FROM openemr_postcalendar_events WHERE pc_pid IN ({pids_str})"
    )
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


def seed_encounters(cur) -> None:
    """Seed two encounters with forms registry entries."""
    print("Seeding encounters …")

    encounters = [
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
    ]

    for enc in encounters:
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


def seed_soap_note(cur) -> None:
    """Seed SOAP note for encounter 900001 (John Doe yesterday)."""
    print("Seeding SOAP note …")

    encounter_id = 900001
    pid = 90001

    # Check if a SOAP form already exists for this encounter
    cur.execute(
        "SELECT 1 FROM forms WHERE encounter = %s AND formdir = 'soap' LIMIT 1",
        (encounter_id,),
    )
    if cur.fetchone():
        print("  SOAP note for encounter 900001 exists, skipping")
        return

    # Step 1: Insert form_soap
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
            "Patient reports persistent cough for 3 days with low-grade fever. "
            "No shortness of breath. Mild sore throat.",
            "Temp 99.8F, BP 128/82, HR 76, RR 16, SpO2 98%. "
            "Oropharynx mildly erythematous. "
            "Lungs clear to auscultation bilaterally.",
            "Acute upper respiratory infection (J06.9)",
            "Rest and adequate fluids. OTC antipyretics for fever. "
            "Follow up in 1 week if symptoms persist or worsen.",
        ),
    )
    soap_id = cur.lastrowid

    # Step 2: Register in forms table
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
    print("  Inserted SOAP note for encounter 900001")


def seed_vitals(cur) -> None:
    """Seed vitals for encounter 900001 (John Doe yesterday)."""
    print("Seeding vitals …")

    encounter_id = 900001
    pid = 90001

    cur.execute(
        "SELECT 1 FROM forms WHERE encounter = %s AND formdir = 'vitals' LIMIT 1",
        (encounter_id,),
    )
    if cur.fetchone():
        print("  Vitals for encounter 900001 exist, skipping")
        return

    # Step 1: Insert form_vitals
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
            "128",       # systolic BP
            "82",        # diastolic BP
            180.0,       # weight (lbs)
            70.0,        # height (inches)
            99.8,        # temperature (F)
            "Oral",      # temp method
            76.0,        # pulse
            16.0,        # respiration
            98.0,        # SpO2
        ),
    )
    vitals_id = cur.lastrowid

    # Step 2: Register in forms table
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
    print("  Inserted vitals for encounter 900001")


def seed_billing(cur) -> None:
    """Seed billing codes for encounters 900001 and 900002.

    Encounter 900001 (John Doe): COMPLETE billing — ICD-10 + CPT with justify.
    Encounter 900002 (Jane Smith): INCOMPLETE billing — missing CPT (for
    validate_claim_ready demo).
    """
    print("Seeding billing …")

    # --- Encounter 900001: COMPLETE billing ---
    enc1 = 900001
    pid1 = 90001

    cur.execute(
        "SELECT 1 FROM billing WHERE encounter = %s LIMIT 1", (enc1,)
    )
    if cur.fetchone():
        print("  Billing for encounter 900001 exists, skipping")
    else:
        billing_rows_enc1 = [
            # ICD-10: Acute URI
            {
                "code_type": "ICD10",
                "code": "J06.9",
                "code_text": "Acute upper respiratory infection, unspecified",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            # ICD-10: Type 2 Diabetes
            {
                "code_type": "ICD10",
                "code": "E11.9",
                "code_text": "Type 2 diabetes mellitus without complications",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            # ICD-10: Essential Hypertension
            {
                "code_type": "ICD10",
                "code": "I10",
                "code_text": "Essential (primary) hypertension",
                "fee": 0.00,
                "justify": "",
                "modifier": "",
            },
            # CPT: Office visit level 3 (justified by J06.9)
            {
                "code_type": "CPT4",
                "code": "99213",
                "code_text": "Office/outpatient visit, est patient, low complexity",
                "fee": 75.00,
                "justify": "J06.9:",
                "modifier": "",
            },
        ]

        for row in billing_rows_enc1:
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
                    pid1,
                    PROVIDER_ID,
                    PROVIDER_ID,  # user is int(11) in billing table
                    enc1,
                    row["fee"],
                    row["justify"],
                    row["modifier"],
                ),
            )
        print("  Inserted COMPLETE billing for encounter 900001 (3x ICD-10 + 1x CPT)")

    # --- Encounter 900002: INCOMPLETE billing (missing CPT) ---
    enc2 = 900002
    pid2 = 90002

    cur.execute(
        "SELECT 1 FROM billing WHERE encounter = %s LIMIT 1", (enc2,)
    )
    if cur.fetchone():
        print("  Billing for encounter 900002 exists, skipping")
    else:
        # Only CPT procedure, no ICD-10 diagnosis — intentionally incomplete
        cur.execute(
            """
            INSERT INTO billing
                (date, code_type, code, code_text, pid, provider_id, user,
                 groupname, authorized, encounter, billed, activity,
                 units, fee, justify, modifier)
            VALUES
                (NOW(), 'CPT4', '99214',
                 'Office/outpatient visit, est patient, moderate complexity',
                 %s, %s, %s,
                 'Default', 1, %s, 0, 1,
                 1, 110.00, '', '')
            """,
            (pid2, PROVIDER_ID, PROVIDER_ID, enc2),
        )
        print(
            "  Inserted INCOMPLETE billing for encounter 900002 "
            "(CPT only, no ICD-10 diagnosis)"
        )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def clean_seed_data(cur) -> None:
    """Delete all seed data (PIDs 90001-90005, encounters 900001-900002)."""
    print("Cleaning seed data …")

    pids_str = ",".join(str(pid) for pid in PIDS)
    enc_str = ",".join(str(eid) for eid in ENCOUNTER_IDS)

    deletes = [
        ("billing", f"encounter IN ({enc_str})"),
        ("forms", f"encounter IN ({enc_str})"),
        ("form_soap", f"pid IN ({pids_str})"),
        ("form_vitals", f"pid IN ({pids_str})"),
        ("form_encounter", f"encounter IN ({enc_str})"),
        ("openemr_postcalendar_events", f"pc_pid IN ({pids_str})"),
        ("patient_data", f"pid IN ({pids_str})"),
    ]

    for table, where in deletes:
        cur.execute(f"DELETE FROM `{table}` WHERE {where}")
        if cur.rowcount:
            print(f"  Deleted {cur.rowcount} rows from {table}")

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

            seed_patients(cur)
            seed_appointments(cur)
            seed_encounters(cur)
            seed_soap_note(cur)
            seed_vitals(cur)
            seed_billing(cur)

            conn.commit()
            print("\nSeed data complete!")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
