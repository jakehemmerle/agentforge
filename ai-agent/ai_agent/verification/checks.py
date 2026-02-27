"""Deterministic checks for grounding final responses in tool evidence."""

from __future__ import annotations

import re

from ai_agent.config_data.loader import VerificationRules
from ai_agent.verification.models import (
    ConfidenceLevel,
    Severity,
    ToolEvidence,
    VerificationFinding,
)

_WARNING_PREFIX_ALIASES: dict[str, str] = {
    # Legacy aliases kept for backward compatibility.
    "allergy_fetch_failed": "allergies_fetch_failed",
    "soap_fetch_failed": "soap_notes_fetch_failed",
}


def _canonical_warning_prefix(prefix: str) -> str:
    """Normalize warning prefixes so rules can match stable canonical keys."""
    cleaned = prefix.strip()
    return _WARNING_PREFIX_ALIASES.get(cleaned, cleaned)


def collect_data_warnings(evidence: list[ToolEvidence]) -> list[str]:
    """Collect all data_warnings values from normalized tool evidence."""
    warnings: list[str] = []
    for item in evidence:
        values = item.output.get("data_warnings", [])
        if isinstance(values, list):
            warnings.extend(str(v) for v in values if v)
    return warnings


def check_data_warning_disclosure(
    response_text: str,
    evidence: list[ToolEvidence],
    rules: VerificationRules,
) -> list[VerificationFinding]:
    """Require caveat language when upstream tools reported degraded data."""
    warnings = collect_data_warnings(evidence)
    if not warnings:
        return []

    lowered = response_text.lower()
    if any(keyword.lower() in lowered for keyword in rules.disclosure_keywords):
        return []

    return [
        VerificationFinding(
            check_name="check_data_warning_disclosure",
            severity=Severity.warning,
            message="Final response did not disclose data_warnings from tool output.",
        )
    ]


def check_no_false_claim_ready(
    response_text: str,
    evidence: list[ToolEvidence],
    rules: VerificationRules,
) -> list[VerificationFinding]:
    """Block claim-ready assertions when claim evidence is not ready/degraded."""
    claim_items = [
        item
        for item in evidence
        if item.tool_name == "validate_claim_ready_completeness"
    ]
    if not claim_items:
        return []

    lowered = response_text.lower()
    has_positive = any(
        re.search(pattern, lowered) for pattern in rules.readiness_positive_patterns
    )
    has_negative = any(
        re.search(pattern, lowered) for pattern in rules.readiness_negative_patterns
    )
    if not has_positive or has_negative:
        return []

    for item in claim_items:
        ready = bool(item.output.get("ready", False))
        warnings = item.output.get("data_warnings", [])
        has_billing_failure = isinstance(warnings, list) and any(
            str(w).startswith("billing_fetch_failed") for w in warnings
        )
        if not ready or has_billing_failure:
            return [
                VerificationFinding(
                    check_name="check_no_false_claim_ready",
                    severity=Severity.error,
                    message=(
                        "Response asserted claim readiness, but claim verification "
                        "evidence does not support that conclusion."
                    ),
                )
            ]
    return []


def check_warning_specific_prohibited_claims(
    response_text: str,
    evidence: list[ToolEvidence],
    rules: VerificationRules,
) -> list[VerificationFinding]:
    """Block phrases that are incompatible with specific fetch-failure warnings."""
    warnings = collect_data_warnings(evidence)
    if not warnings:
        return []

    lowered = response_text.lower()
    matches: list[str] = []
    for warning in warnings:
        prefix = _canonical_warning_prefix(warning.split(":", 1)[0])
        guarded_patterns = rules.warning_phrase_guards.get(prefix, [])
        for pattern in guarded_patterns:
            if re.search(pattern, lowered):
                matches.append(f"{prefix} -> /{pattern}/")

    if not matches:
        return []

    return [
        VerificationFinding(
            check_name="check_warning_specific_prohibited_claims",
            severity=Severity.error,
            message=(
                "Response contains claims that conflict with degraded data: "
                + ", ".join(sorted(set(matches)))
            ),
        )
    ]


def compute_confidence(
    findings: list[VerificationFinding],
    warning_count: int,
    rules: VerificationRules,
) -> ConfidenceLevel:
    """Compute confidence based on finding severity and warning volume."""
    if any(f.severity == Severity.error for f in findings):
        return ConfidenceLevel.low
    if warning_count >= rules.confidence.warning_threshold_for_medium:
        return ConfidenceLevel.medium
    return ConfidenceLevel.high
