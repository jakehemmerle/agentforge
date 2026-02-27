"""Code-based evaluators for the OpenEMR AI agent eval harness.

Each evaluator follows the LangSmith signature: (run, example) -> dict
with keys ``key`` (str) and ``score`` (float 0.0–1.0).

Extracted and improved from ``run_evals.py``, plus five new evaluators:
- ``no_unwanted_tool_calls``: penalises tool usage when none was expected
- ``response_well_formed``: catches raw JSON / tracebacks in user-facing text
- ``no_prohibited_content``: fails if prohibited keywords appear in response
- ``verification_decision_correct``: checks verify node produced expected decision
- ``tool_call_precision``: penalises calling extra/unexpected tools

Expected data layout in ``example.outputs`` (matches ``eval_cases.yaml``):

.. code-block:: python

    {
        "expected": {
            "tools": [...],
            "keywords": [...],
            "prohibited_keywords": [...],       # optional
            "verification_decision": "pass",    # optional: pass | warn | fail
            "hallucination_markers": [...],     # optional, overrides global list
        },
        "no_hallucination": True,   # optional
    }

Legacy flat keys (``expected_tools``, ``expected_keywords``) are also
accepted for backward compatibility.
"""

from __future__ import annotations

import re
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Typing helpers — keeps evaluators testable without importing LangSmith
# ---------------------------------------------------------------------------


class _HasOutputs(Protocol):
    outputs: dict[str, Any]


class _HasOutputsAndMetadata(Protocol):
    outputs: dict[str, Any]
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# Output accessors — support both nested and legacy flat keys
# ---------------------------------------------------------------------------


def _get_expected_tools(example: _HasOutputsAndMetadata) -> list[str]:
    """Return expected tools from example outputs (nested or flat)."""
    expected = example.outputs.get("expected", {})
    if isinstance(expected, dict) and "tools" in expected:
        return expected["tools"]
    return example.outputs.get("expected_tools", [])


def _get_expected_keywords(example: _HasOutputsAndMetadata) -> list[str]:
    """Return expected keywords from example outputs (nested or flat)."""
    expected = example.outputs.get("expected", {})
    if isinstance(expected, dict) and "keywords" in expected:
        return expected["keywords"]
    return example.outputs.get("expected_keywords", [])


def _get_prohibited_keywords(example: _HasOutputsAndMetadata) -> list[str]:
    """Return prohibited keywords from example outputs (must NOT appear in response)."""
    expected = example.outputs.get("expected", {})
    if isinstance(expected, dict):
        return expected.get("prohibited_keywords", [])
    return []


def _get_verification_decision(example: _HasOutputsAndMetadata) -> str | None:
    """Return expected verification decision (pass/warn/fail) or None if not set."""
    expected = example.outputs.get("expected", {})
    if isinstance(expected, dict):
        return expected.get("verification_decision")
    return None


def _get_hallucination_markers(example: _HasOutputsAndMetadata) -> list[str]:
    """Return per-case hallucination markers, or empty list if not set."""
    expected = example.outputs.get("expected", {})
    if isinstance(expected, dict):
        return expected.get("hallucination_markers", [])
    return []


# Hallucination markers — specific details the model shouldn't fabricate.
_HALLUCINATION_MARKERS: list[str] = [
    "09:00",
    "10:00",
    "office visit",
    "checkup",
    "scheduled for",
    "follow-up appointment on",
]

# Patterns that indicate raw/unformatted machine output leaked into the
# user-facing response.
_BAD_RESPONSE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE),
    re.compile(r"^\s*\{[\s\S]{20,}\}\s*$"),  # entire response is a JSON blob
    re.compile(r"\b(KeyError|TypeError|ValueError|AttributeError)\b:?\s"),
    re.compile(r"httpx\.(ReadTimeout|ConnectError|HTTPStatusError)"),
]


# ---------------------------------------------------------------------------
# Evaluator 1 — expected_tools_called (migrated + improved)
# ---------------------------------------------------------------------------


def expected_tools_called(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """Fraction of expected tools that actually appeared in the run.

    Score = |expected ∩ actual| / |expected|.  When no tools are expected the
    score is 1.0 (vacuously true — use ``no_unwanted_tool_calls`` to guard the
    complementary case).
    """
    expected: set[str] = set(_get_expected_tools(example))
    actual: set[str] = set(run.outputs.get("tool_calls", []))
    if not expected:
        score = 1.0
    else:
        score = len(expected & actual) / len(expected)
    return {"key": "expected_tools_called", "score": score}


# ---------------------------------------------------------------------------
# Evaluator 2 — has_final_response (migrated)
# ---------------------------------------------------------------------------


def has_final_response(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """Binary check that the agent produced a non-empty final text response."""
    response = run.outputs.get("response", "")
    score = 1.0 if response and response.strip() else 0.0
    return {"key": "has_final_response", "score": score}


# ---------------------------------------------------------------------------
# Evaluator 3 — response_has_keywords (migrated + improved)
# ---------------------------------------------------------------------------


def response_has_keywords(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """Fraction of expected keywords found (case-insensitive) in the response.

    Keywords are treated as substrings, not whole words, so ``"prescri"``
    matches ``"prescribe"`` and ``"prescription"``.
    """
    response: str = (run.outputs.get("response", "") or "").lower()
    keywords: list[str] = _get_expected_keywords(example)
    if not keywords:
        score = 1.0
    else:
        found = sum(1 for kw in keywords if str(kw).lower() in response)
        score = found / len(keywords)
    return {"key": "response_has_keywords", "score": score}


# ---------------------------------------------------------------------------
# Evaluator 4 — no_hallucinated_data (migrated + expanded markers)
# ---------------------------------------------------------------------------


def no_hallucinated_data(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """For nonexistent-resource cases, verify the response contains no fabricated details.

    Checks against a list of hallucination markers (specific times, visit
    types, scheduling phrases).  Non-applicable cases score 1.0.

    Uses per-case ``hallucination_markers`` when present; otherwise falls back
    to the global ``_HALLUCINATION_MARKERS`` list.

    Applicability is determined by the ``no_hallucination`` flag in
    ``example.outputs`` (set in ``eval_cases.yaml``).
    """
    if not example.outputs.get("no_hallucination", False):
        return {"key": "no_hallucinated_data", "score": 1.0}

    response: str = (run.outputs.get("response", "") or "").lower()
    markers = _get_hallucination_markers(example) or _HALLUCINATION_MARKERS
    found = [m for m in markers if m.lower() in response]
    score = 0.0 if found else 1.0
    return {"key": "no_hallucinated_data", "score": score}


# ---------------------------------------------------------------------------
# Evaluator 5 — no_unwanted_tool_calls  (NEW)
# ---------------------------------------------------------------------------


def no_unwanted_tool_calls(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """When no tools are expected, penalise any tool invocation.

    Complements ``expected_tools_called``: that evaluator checks recall (did
    we call what we should?), this one checks precision for the zero-tool
    cases — the agent should *not* invoke tools when the query is ambiguous
    or out of scope.

    For cases that *do* expect tools, the score is always 1.0 (not applicable).
    """
    expected: list[str] = _get_expected_tools(example)
    actual: list[str] = run.outputs.get("tool_calls", [])
    if expected:
        # This evaluator only applies when NO tools should be called.
        return {"key": "no_unwanted_tool_calls", "score": 1.0}
    score = 0.0 if actual else 1.0
    return {"key": "no_unwanted_tool_calls", "score": score}


# ---------------------------------------------------------------------------
# Evaluator 6 — response_well_formed  (NEW)
# ---------------------------------------------------------------------------


def response_well_formed(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """Verify the final response looks like user-facing prose, not raw machine output.

    Catches leaked tracebacks, raw JSON blobs, and Python exception class
    names that would indicate an unhandled error bubbled up to the user.
    """
    response: str = run.outputs.get("response", "") or ""
    if not response.strip():
        # Empty responses are caught by ``has_final_response``; don't
        # double-penalise here.
        return {"key": "response_well_formed", "score": 1.0}

    for pattern in _BAD_RESPONSE_PATTERNS:
        if pattern.search(response):
            return {"key": "response_well_formed", "score": 0.0}
    return {"key": "response_well_formed", "score": 1.0}


# ---------------------------------------------------------------------------
# Evaluator 7 — no_prohibited_content  (NEW)
# ---------------------------------------------------------------------------


def no_prohibited_content(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """Verify the response does NOT contain any prohibited keywords.

    Score is 0.0 if ANY prohibited keyword appears (case-insensitive).
    Returns 1.0 when the field is absent (not applicable).
    """
    prohibited = _get_prohibited_keywords(example)
    if not prohibited:
        return {"key": "no_prohibited_content", "score": 1.0}

    response: str = (run.outputs.get("response", "") or "").lower()
    for kw in prohibited:
        if str(kw).lower() in response:
            return {"key": "no_prohibited_content", "score": 0.0}
    return {"key": "no_prohibited_content", "score": 1.0}


# ---------------------------------------------------------------------------
# Evaluator 8 — verification_decision_correct  (NEW)
# ---------------------------------------------------------------------------


def verification_decision_correct(
    run: _HasOutputs, example: _HasOutputsAndMetadata
) -> dict:
    """Verify the verification node produced the expected decision.

    Compares ``run.outputs["verification"]["decision"]`` against
    ``expected.verification_decision``.  Returns 1.0 when the field is
    absent (not applicable).
    """
    expected_decision = _get_verification_decision(example)
    if expected_decision is None:
        return {"key": "verification_decision_correct", "score": 1.0}

    verification = run.outputs.get("verification")
    if not verification or not isinstance(verification, dict):
        return {"key": "verification_decision_correct", "score": 0.0}

    actual = verification.get("decision")
    score = 1.0 if actual == expected_decision else 0.0
    return {"key": "verification_decision_correct", "score": score}


# ---------------------------------------------------------------------------
# Evaluator 9 — tool_call_precision  (NEW)
# ---------------------------------------------------------------------------


def tool_call_precision(run: _HasOutputs, example: _HasOutputsAndMetadata) -> dict:
    """Precision of tool calls: |expected ∩ actual| / |actual|.

    Penalises calling extra (unexpected) tools.  Returns 1.0 when expected
    is empty (defers to ``no_unwanted_tool_calls``) or when actual is empty
    (defers to ``expected_tools_called``).
    """
    expected: set[str] = set(_get_expected_tools(example))
    actual: set[str] = set(run.outputs.get("tool_calls", []))
    if not expected or not actual:
        return {"key": "tool_call_precision", "score": 1.0}
    score = len(expected & actual) / len(actual)
    return {"key": "tool_call_precision", "score": score}


# ---------------------------------------------------------------------------
# Public list for easy import into the runner
# ---------------------------------------------------------------------------

ALL_EVALUATORS = [
    expected_tools_called,
    has_final_response,
    response_has_keywords,
    no_hallucinated_data,
    no_unwanted_tool_calls,
    response_well_formed,
    no_prohibited_content,
    verification_decision_correct,
    tool_call_precision,
]
