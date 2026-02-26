"""Render the VM startup script from a template with placeholder substitution."""

from __future__ import annotations

import base64
from pathlib import Path

_TEMPLATE = (Path(__file__).parent / "startup_script.sh.tpl").read_text()


def render_startup_script(
    *,
    project_id: str,
    cloud_sql_connection: str,
    db_password: str,
    openemr_image: str,
    ai_agent_image: str,
    static_ip: str,
) -> str:
    """Return a fully-interpolated startup script.

    Reads ``startup_script.sh.tpl`` and replaces ``__PLACEHOLDER__`` markers
    with the supplied values.  The database password is base64-encoded before
    substitution so it never appears in plain text inside the script.
    """
    db_password_b64 = base64.b64encode(db_password.encode("utf-8")).decode("ascii")

    return (
        _TEMPLATE
        .replace("__PROJECT_ID__", project_id)
        .replace("__CLOUD_SQL_CONNECTION__", cloud_sql_connection)
        .replace("__DB_PASSWORD_B64__", db_password_b64)
        .replace("__OPENEMR_IMAGE__", openemr_image)
        .replace("__AI_AGENT_IMAGE__", ai_agent_image)
        .replace("__STATIC_IP__", static_ip)
    )
