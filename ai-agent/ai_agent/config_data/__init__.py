"""Config package — YAML-based configuration for rules and prompts."""

from ai_agent.config_data.loader import (
    get_claim_rules,
    get_prompts,
    get_verification_rules,
)

__all__ = ["get_claim_rules", "get_prompts", "get_verification_rules"]
