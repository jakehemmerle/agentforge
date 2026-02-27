"""Eval graph factory — builds LangGraph with mock tools per scenario."""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_core.tools import ToolException, tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ai_agent.agent import AgentState, route
from ai_agent.config import get_settings
from ai_agent.config_data.loader import get_prompts
from ai_agent.tools.draft_encounter_note import (
    draft_encounter_note as real_draft_encounter_note,
)
from ai_agent.tools.find_appointments import (
    find_appointments as real_find_appointments,
)
from ai_agent.tools.get_encounter_context import (
    get_encounter_context as real_get_encounter_context,
)
from ai_agent.tools.validate_claim_completeness import (
    validate_claim_ready_completeness as real_validate_claim,
)
from ai_agent.verification.node import verify_final_response

from evals.fixtures.registry import get_fixture

SYSTEM_PROMPT = get_prompts().agent_system_prompt

_REAL_TOOLS = [
    real_find_appointments,
    real_get_encounter_context,
    real_draft_encounter_note,
    real_validate_claim,
]


def _make_mock_tool(real_tool, scenario_name: str):
    """Create a mock @tool with identical name/schema that returns fixture data."""
    _tool_name = real_tool.name
    _scenario = scenario_name

    @tool(_tool_name, args_schema=real_tool.args_schema)
    async def _mock(**kwargs: Any) -> dict[str, Any]:
        """Mock tool — returns fixture data."""
        fixture = get_fixture(_scenario, _tool_name)
        if fixture is None:
            raise ToolException(
                f"Tool {_tool_name} has no fixture in scenario {_scenario}"
            )
        if "_error" in fixture:
            raise ToolException(fixture["_error"])
        return fixture

    # Copy the real tool's description so the LLM sees identical tool definitions
    _mock.description = real_tool.description
    return _mock


def _make_call_llm(model_with_tools):
    """Create the agent node function bound to a specific model."""

    async def call_llm(state: AgentState) -> dict[str, Any]:
        system_msg = SystemMessage(
            content=SYSTEM_PROMPT.format(today=date.today().isoformat())
        )
        response = await model_with_tools.ainvoke([system_msg] + state["messages"])
        return {"messages": [response]}

    return call_llm


def create_eval_graph(scenario_name: str):
    """Build a LangGraph with mock tools for the given scenario.

    The graph is structurally identical to the production graph in agent.py,
    but tool execution returns canned fixture data instead of making HTTP calls.
    """
    settings = get_settings()

    # Build mock tools
    mock_tools = [_make_mock_tool(t, scenario_name) for t in _REAL_TOOLS]

    # Create model + bind mock tools
    model = ChatAnthropic(
        model=settings.model_name,
        temperature=0,
        api_key=settings.anthropic_api_key or None,
    )
    model_with_tools = model.bind_tools(mock_tools)

    # Build graph (mirrors agent.py lines 68-76)
    builder = StateGraph(AgentState)
    builder.add_node("agent", _make_call_llm(model_with_tools))
    builder.add_node("tools", ToolNode(mock_tools, handle_tool_errors=True))
    builder.add_node("verify", verify_final_response)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent", route, {"tools": "tools", "verify": "verify"}
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("verify", END)

    return builder.compile(checkpointer=MemorySaver(), name="eval_chat")
