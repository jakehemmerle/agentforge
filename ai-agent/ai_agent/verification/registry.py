"""Registry for final-response verification checks."""

from ai_agent.verification.checks import (
    check_data_warning_disclosure,
    check_no_false_claim_ready,
    check_warning_specific_prohibited_claims,
)

RESPONSE_CHECKS = [
    check_data_warning_disclosure,
    check_no_false_claim_ready,
    check_warning_specific_prohibited_claims,
]
