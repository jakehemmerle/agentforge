"""Structured logging decorator for tool implementation functions."""

from __future__ import annotations

import logging
import traceback
import time
from functools import wraps
from typing import Any, Callable

import httpx
from langchain_core.tools import ToolException

from ai_agent.openemr_client import OpenEMRAuthError

logger = logging.getLogger("ai_agent.tools")

# PHI keys that always get redacted to "[REDACTED]"
_PHI_KEYS = frozenset({
    "fname", "lname", "mname", "DOB", "ss",
    "street", "city", "state", "postal_code",
    "phone_cell", "phone_home", "phone_biz", "email",
    "pubpid", "subscriber_fname", "subscriber_lname",
    "subscriber_DOB", "policy_number",
})

# Output keys containing nested PHI data (type-dependent handling)
_PHI_OUTPUT_KEYS = frozenset({
    "patient", "medications", "allergies", "vitals",
    "problems", "notes", "draft", "narrative",
})


def _sanitize_dict(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Sanitize a dict by redacting PHI keys.

    Recurses into nested dicts at depth=0; stops at depth=1.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in _PHI_KEYS:
            result[key] = "[REDACTED]"
        elif key in _PHI_OUTPUT_KEYS:
            if isinstance(value, dict):
                result[key] = "{...}"
            elif isinstance(value, list):
                result[key] = f"[{len(value)} items]"
            else:
                result[key] = "[REDACTED]"
        elif isinstance(value, dict) and depth < 1:
            result[key] = _sanitize_dict(value, depth=depth + 1)
        else:
            result[key] = value
    return result


def _sanitize_input(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Sanitize tool input kwargs for logging."""
    return _sanitize_dict(kwargs)


def _sanitize_output(output: Any) -> str:
    """Sanitize tool output for logging, truncated to 200 chars."""
    if isinstance(output, dict):
        sanitized = _sanitize_dict(output)
        return str(sanitized)[:200]
    return str(output)[:200]


def classify_error(exc: Exception) -> str:
    """Map an exception to an error_type category.

    Categories:
        auth_error       – HTTP 401/403
        api_timeout      – httpx timeout
        not_found        – HTTP 404
        validation_error – ToolException with validation-related message
        unknown          – everything else
    """
    if isinstance(exc, OpenEMRAuthError):
        return "auth_error"
    if isinstance(exc, httpx.TimeoutException):
        return "api_timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "auth_error"
        if code == 404:
            return "not_found"
    if isinstance(exc, ToolException):
        msg = str(exc).lower()
        for keyword in ("validat", "invalid", "required", "must be", "either"):
            if keyword in msg:
                return "validation_error"
    return "unknown"


def logged_tool(func: Callable) -> Callable:
    """Add structured logging around a tool's inner implementation.

    Apply this to the ``_impl`` function (not the ``@tool`` wrapper) so it
    doesn't interfere with LangChain's callback/tracing pipeline.

    On error, attaches ``error_category`` metadata to the current LangSmith
    run (if one exists) so exceptions are fully visible in traces.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        tool_name = func.__name__
        logger.info(
            "tool_call_start",
            extra={"tool": tool_name, "input": _sanitize_input(kwargs)},
        )
        start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            latency_ms = round((time.monotonic() - start) * 1000)
            logger.info(
                "tool_call_end",
                extra={
                    "tool": tool_name,
                    "latency_ms": latency_ms,
                    "status": "success",
                    "output_summary": _sanitize_output(result),
                },
            )
            return result
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000)
            error_category = classify_error(e)
            logger.error(
                "tool_call_error",
                extra={
                    "tool": tool_name,
                    "latency_ms": latency_ms,
                    "status": "error",
                    "error_type": type(e).__name__,
                    "error_category": error_category,
                    "error_msg": str(e),
                    "stack_trace": traceback.format_exc(),
                },
            )

            # Enrich the active LangSmith run with error metadata
            try:
                from langsmith.run_helpers import get_current_run_tree

                rt = get_current_run_tree()
                if rt is not None:
                    rt.metadata = {
                        **(rt.metadata or {}),
                        "error_type": type(e).__name__,
                        "error_category": error_category,
                        "error_msg": str(e),
                        "tool_name": tool_name,
                    }
            except Exception:
                pass  # tracing enrichment is best-effort

            raise

    return wrapper
