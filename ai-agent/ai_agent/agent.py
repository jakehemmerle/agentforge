"""LangGraph ReAct agent for OpenEMR clinical assistant."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from ai_agent.config import get_settings
from ai_agent.config_data.loader import get_prompts
from ai_agent.tools.draft_encounter_note import draft_encounter_note
from ai_agent.tools.find_appointments import find_appointments
from ai_agent.tools.get_encounter_context import get_encounter_context
from ai_agent.tools.validate_claim_completeness import validate_claim_ready_completeness

SYSTEM_PROMPT = get_prompts().agent_system_prompt


class AgentState(TypedDict):
    """State flowing through the agent graph."""

    messages: Annotated[list, add_messages]
    user_id: str
    error: str | None


# -- tools ---------------------------------------------------------------------

tools = [
    find_appointments,
    get_encounter_context,
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


async def call_llm(state: AgentState) -> dict[str, Any]:
    """Invoke the LLM with the system prompt and conversation history."""
    system_msg = SystemMessage(
        content=SYSTEM_PROMPT.format(today=date.today().isoformat())
    )
    response = await model_with_tools.ainvoke([system_msg] + state["messages"])
    return {"messages": [response]}


def route(state: AgentState) -> str:
    """Route to tools if the last message has tool calls, otherwise end."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


# -- graph construction --------------------------------------------------------

builder = StateGraph(AgentState)
builder.add_node("agent", call_llm)
builder.add_node("tools", ToolNode(tools, handle_tool_errors=True))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", route, {"tools": "tools", END: END})
builder.add_edge("tools", "agent")

checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer, name="chat_request")
