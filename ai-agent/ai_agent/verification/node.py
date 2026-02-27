"""LangGraph node that verifies final LLM responses against tool evidence."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_agent.config_data.loader import get_verification_rules
from ai_agent.verification.checks import collect_data_warnings, compute_confidence
from ai_agent.verification.models import ToolEvidence, VerificationResult
from ai_agent.verification.registry import RESPONSE_CHECKS


def _extract_text(content: Any) -> str:
    """Extract plain text from AI content (string or content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def _parse_tool_output(content: Any) -> dict[str, Any]:
    """Parse ToolMessage content into a dictionary for deterministic checks."""
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"raw_content": content}
    if isinstance(content, list):
        return {"raw_content": content}
    return {"raw_content": str(content)}


def _collect_turn_tool_evidence(messages: list) -> list[ToolEvidence]:
    """Collect ToolMessage evidence for the most recent user turn only."""
    last_human_idx = -1
    for idx in range(len(messages) - 1, -1, -1):
        if isinstance(messages[idx], HumanMessage):
            last_human_idx = idx
            break

    turn_messages = messages[last_human_idx + 1 :]
    evidence: list[ToolEvidence] = []
    for msg in turn_messages:
        if not isinstance(msg, ToolMessage):
            continue
        evidence.append(
            ToolEvidence(
                tool_name=msg.name or "unknown_tool",
                output=_parse_tool_output(msg.content),
            )
        )
    return evidence


def _augment_response_for_verification(
    response_text: str, result: VerificationResult
) -> str:
    """Attach verification caveats (warn) or replace unsafe output (fail)."""
    issue_lines = [f"- {finding.message}" for finding in result.findings]
    if result.decision == "warn":
        return f"{response_text}\n\nVerification caveat:\n" + "\n".join(issue_lines)
    if result.decision == "fail":
        return (
            "I cannot provide a reliable final answer from the available evidence.\n\n"
            "Verification blocked this response for safety:\n"
            + "\n".join(issue_lines)
            + "\n\nPlease review the encounter with a clinician or billing specialist."
        )
    return response_text


async def verify_final_response(state: dict[str, Any]) -> dict[str, Any]:
    """Verify the latest final AI response against same-turn tool evidence."""
    messages = state.get("messages", [])
    if not messages:
        return {}

    last = messages[-1]
    if not isinstance(last, AIMessage):
        return {}
    if getattr(last, "tool_calls", None):
        return {}

    response_text = _extract_text(last.content)
    evidence = _collect_turn_tool_evidence(messages)
    rules = get_verification_rules()

    findings = []
    for check in RESPONSE_CHECKS:
        findings.extend(check(response_text, evidence, rules))

    warning_count = len(collect_data_warnings(evidence))
    confidence = compute_confidence(findings, warning_count, rules)
    decision = "pass"
    if any(f.severity.value == "error" for f in findings):
        decision = "fail"
    elif findings:
        decision = "warn"

    result = VerificationResult(
        decision=decision,
        confidence=confidence,
        findings=findings,
    )
    payload = {"verification": result.model_dump(mode="json")}
    if decision == "pass":
        return payload

    updated_content = _augment_response_for_verification(response_text, result)
    kwargs: dict[str, Any] = {}
    if getattr(last, "id", None):
        kwargs["id"] = last.id
    payload["messages"] = [AIMessage(content=updated_content, **kwargs)]
    return payload
