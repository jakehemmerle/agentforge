"""LangGraph ReAct agent for OpenEMR clinical assistant."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, SystemMessage, trim_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from ai_agent.config import get_settings
from ai_agent.config_data.loader import get_prompts
from ai_agent.tools.draft_encounter_note import draft_encounter_note
from ai_agent.tools.find_appointments import find_appointments
from ai_agent.tools.get_encounter_context import get_encounter_context
from ai_agent.tools.get_patient_summary import get_patient_summary
from ai_agent.tools.validate_claim_completeness import validate_claim_ready_completeness
from ai_agent.verification.node import verify_final_response

SYSTEM_PROMPT = get_prompts().agent_system_prompt
logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """State flowing through the agent graph."""

    messages: Annotated[list, add_messages]
    user_id: str
    error: str | None
    verification: dict[str, Any] | None


# -- tools ---------------------------------------------------------------------

tools = [
    find_appointments,
    get_encounter_context,
    get_patient_summary,
    draft_encounter_note,
    validate_claim_ready_completeness,
]

# -- model ---------------------------------------------------------------------

_settings = get_settings()
model = ChatAnthropic(
    model=_settings.model_name,
    temperature=0,
    api_key=_settings.anthropic_api_key,
)
model_with_tools = model.bind_tools(tools)

# -- nodes ---------------------------------------------------------------------


def _compact_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Trim long conversations before sending history back to the model."""
    compacted = messages

    if (
        _settings.max_history_messages > 0
        and len(compacted) > _settings.max_history_messages
    ):
        compacted = compacted[-_settings.max_history_messages :]

    if _settings.max_history_tokens > 0:
        trimmed = trim_messages(
            compacted,
            max_tokens=_settings.max_history_tokens,
            token_counter="approximate",
            strategy="last",
            allow_partial=False,
        )
        if trimmed:
            compacted = trimmed

    if len(compacted) < len(messages):
        logger.info(
            "Compacted conversation history from %d to %d messages",
            len(messages),
            len(compacted),
        )

    return compacted


async def call_llm(state: AgentState) -> dict[str, Any]:
    """Invoke the LLM with the system prompt and conversation history."""
    conversation = _compact_history(state["messages"])
    system_msg = SystemMessage(
        content=SYSTEM_PROMPT.format(today=date.today().isoformat())
    )
    response = await model_with_tools.ainvoke([system_msg] + conversation)
    return {"messages": [response]}


def route(state: AgentState) -> str:
    """Route to tools if needed; otherwise verify before ending."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return "verify"


# -- graph construction --------------------------------------------------------

builder = StateGraph(AgentState)
builder.add_node("agent", call_llm)
builder.add_node("tools", ToolNode(tools, handle_tool_errors=True))
builder.add_node("verify", verify_final_response)
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", route, {"tools": "tools", "verify": "verify"})
builder.add_edge("tools", "agent")
builder.add_edge("verify", END)

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer, name="chat_request")
