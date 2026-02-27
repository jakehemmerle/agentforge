"""YAML config loader — loads rules and prompts at startup."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

_CONFIG_DIR = Path(__file__).parent


# -- Pydantic models ----------------------------------------------------------


class ClaimRules(BaseModel):
    """Validated claim validation rules."""

    required_demographics: dict[str, str]
    accepted_diagnosis_code_types: list[str]
    accepted_procedure_code_types: list[str]
    check_severities: dict[str, str]


class Prompts(BaseModel):
    """Validated prompt templates."""

    agent_system_prompt: str
    scribe_system_prompt: str
    note_type_templates: dict[str, str]


class VerificationConfidenceRules(BaseModel):
    """Thresholds for confidence scoring."""

    warning_threshold_for_medium: int = 1


class VerificationRules(BaseModel):
    """Validated runtime response-verification rules."""

    disclosure_keywords: list[str]
    readiness_positive_patterns: list[str]
    readiness_negative_patterns: list[str]
    warning_phrase_guards: dict[str, list[str]]
    confidence: VerificationConfidenceRules


# -- loaders ------------------------------------------------------------------


def _load_yaml(filename: str) -> dict[str, Any]:
    """Read and parse a YAML file from the config directory."""
    path = _CONFIG_DIR / filename
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"Config file is empty: {path}")
    return data


@lru_cache(maxsize=1)
def get_claim_rules() -> ClaimRules:
    """Load and validate claim_rules.yaml. Result is cached as a singleton."""
    data = _load_yaml("claim_rules.yaml")
    return ClaimRules(**data)


@lru_cache(maxsize=1)
def get_prompts() -> Prompts:
    """Load and validate prompts.yaml. Result is cached as a singleton."""
    data = _load_yaml("prompts.yaml")
    return Prompts(**data)


@lru_cache(maxsize=1)
def get_verification_rules() -> VerificationRules:
    """Load and validate verification_rules.yaml. Cached singleton."""
    data = _load_yaml("verification_rules.yaml")
    return VerificationRules(**data)
