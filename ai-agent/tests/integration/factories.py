"""DB-level scenario builders for integration tests.

Each factory function accepts a live ``pymysql`` connection and returns a
cleanup callable (or tuple containing one) so the caller can undo the
side-effects in a ``finally`` block or pytest fixture teardown.
"""

from __future__ import annotations

from typing import Any, Callable

import pymysql
import pymysql.cursors


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------


def insert_billing_row(
    conn: pymysql.connections.Connection,
    encounter_id: int,
    patient_id: int,
    **kwargs: Any,
) -> tuple[int, Callable[[], None]]:
    """Insert a row into the ``billing`` table and return its id + cleanup.

    Parameters
    ----------
    conn:
        An open pymysql connection (with autocommit or explicit commit).
    encounter_id:
        The encounter to attach the billing row to.
    patient_id:
        The patient (pid) for the billing row.
    **kwargs:
        Override any default column value.  Accepted keys mirror the
        ``billing`` table columns (e.g. ``code_type``, ``code``, ``fee``).

    Returns
    -------
    tuple[int, Callable[[], None]]
        ``(row_id, cleanup)`` where *cleanup* deletes the inserted row
        and commits.
    """
    _USE_NOW = object()  # sentinel for MySQL NOW()

    defaults: dict[str, Any] = {
        "date": _USE_NOW,
        "code_type": "CPT4",
        "code": "99999",
        "code_text": "TEST",
        "fee": 0.00,
        "modifier": "",
        "units": 1,
        "activity": 1,
        "authorized": 1,
    }
    defaults.update(kwargs)

    # Build the INSERT dynamically so callers can add arbitrary columns.
    columns = ["encounter", "pid"] + list(defaults.keys())
    placeholders: list[str] = ["%s", "%s"]
    values: list[Any] = [encounter_id, patient_id]

    for col in defaults:
        if defaults[col] is _USE_NOW:
            # Use the MySQL NOW() function directly.
            placeholders.append("NOW()")
        else:
            placeholders.append("%s")
            values.append(defaults[col])

    sql = (
        f"INSERT INTO billing ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)})"
    )

    cur = conn.cursor()
    cur.execute(sql, values)
    conn.commit()
    row_id: int = cur.lastrowid
    cur.close()

    def _cleanup() -> None:
        c = conn.cursor()
        c.execute("DELETE FROM billing WHERE id = %s", (row_id,))
        conn.commit()
        c.close()

    return row_id, _cleanup


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------


def insert_insurance(
    conn: pymysql.connections.Connection,
    patient_id: int,
    **kwargs: Any,
) -> tuple[int, Callable[[], None]]:
    """Insert a row into ``insurance_data`` and return its id + cleanup.

    Parameters
    ----------
    conn:
        An open pymysql connection.
    patient_id:
        The patient (pid) for the insurance row.
    **kwargs:
        Override any default column value.

    Returns
    -------
    tuple[int, Callable[[], None]]
        ``(row_id, cleanup)`` where *cleanup* deletes the inserted row
        and commits.
    """
    defaults: dict[str, Any] = {
        "type": "primary",
        "provider": "1",
        "plan_name": "Test Plan",
        "policy_number": "POL-TEST",
        "group_number": "GRP-TEST",
        "subscriber_lname": "Test",
        "subscriber_fname": "Patient",
        "subscriber_DOB": "1985-01-01",
        "date": "2025-01-01",
    }
    defaults.update(kwargs)

    columns = ["pid"] + list(defaults.keys())
    placeholders = ["%s"] + ["%s"] * len(defaults)
    values: list[Any] = [patient_id] + list(defaults.values())

    sql = (
        f"INSERT INTO insurance_data ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)})"
    )

    cur = conn.cursor()
    cur.execute(sql, values)
    conn.commit()
    row_id: int = cur.lastrowid
    cur.close()

    def _cleanup() -> None:
        c = conn.cursor()
        c.execute("DELETE FROM insurance_data WHERE id = %s", (row_id,))
        conn.commit()
        c.close()

    return row_id, _cleanup


# ---------------------------------------------------------------------------
# Insurance convenience helpers
# ---------------------------------------------------------------------------


def ensure_insurance_for_patient(
    conn: pymysql.connections.Connection,
    patient_id: int,
) -> Callable[[], None]:
    """Ensure ``patient_id`` has at least one primary insurance row.

    If a primary insurance row already exists for the patient this is a
    no-op and the returned cleanup callable does nothing.  Otherwise a
    new row is inserted via :func:`insert_insurance` and the cleanup
    callable will delete it.

    Returns
    -------
    Callable[[], None]
        A cleanup callable that undoes any changes made by this function.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM insurance_data "
        "WHERE pid = %s AND type = 'primary'",
        (patient_id,),
    )
    row = cur.fetchone()
    cur.close()

    # DictCursor returns dict, regular cursor returns tuple.
    count = row["cnt"] if isinstance(row, dict) else row[0]

    if count > 0:
        # Insurance already present -- nothing to do or undo.
        return lambda: None

    _row_id, cleanup = insert_insurance(conn, patient_id)
    return cleanup


def clear_insurance_for_patient(
    conn: pymysql.connections.Connection,
    patient_id: int,
) -> list[dict[str, Any]]:
    """Remove all insurance rows for ``patient_id`` and return saved copies.

    The caller can use the returned list to restore the rows later if
    needed (e.g. in a fixture teardown that re-inserts them).

    Returns
    -------
    list[dict[str, Any]]
        The insurance rows that were deleted, as dictionaries.  Empty
        list if the patient had no insurance.
    """
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute(
        "SELECT * FROM insurance_data WHERE pid = %s",
        (patient_id,),
    )
    saved_rows: list[dict[str, Any]] = cur.fetchall()

    cur.execute(
        "DELETE FROM insurance_data WHERE pid = %s",
        (patient_id,),
    )
    conn.commit()
    cur.close()

    return saved_rows
