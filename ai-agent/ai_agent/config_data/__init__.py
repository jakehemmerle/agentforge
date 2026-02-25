"""Config package — YAML-based configuration for claim rules and prompts."""

from ai_agent.config_data.loader import get_claim_rules, get_prompts

__all__ = ["get_claim_rules", "get_prompts"]
