"""Pydantic models for final-response verification results."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Supported finding severities."""

    warning = "warning"
    error = "error"


class ConfidenceLevel(str, Enum):
    """Runtime confidence levels for final responses."""

    high = "high"
    medium = "medium"
    low = "low"


class VerificationFinding(BaseModel):
    """One verification issue detected for a response."""

    check_name: str
    severity: Severity
    message: str


class VerificationResult(BaseModel):
    """Aggregate verification output for one final response."""

    decision: str
    confidence: ConfidenceLevel
    findings: list[VerificationFinding] = Field(default_factory=list)


class ToolEvidence(BaseModel):
    """Normalized tool output used as grounding evidence."""

    tool_name: str
    output: dict[str, Any]
