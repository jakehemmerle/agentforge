"""Tests for the LangGraph ReAct agent structure."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ai_agent.agent import (
    SYSTEM_PROMPT,
    AgentState,
    call_llm,
    graph,
    route,
    tools,
)

import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.unit


# -- graph structure -----------------------------------------------------------


def test_graph_compiles():
    assert graph is not None
    assert type(graph).__name__ == "CompiledStateGraph"


def test_graph_has_expected_nodes():
    node_names = set(graph.nodes.keys())
    assert "agent" in node_names
    assert "tools" in node_names


def test_tools_list_contains_find_appointments():
    tool_names = [t.name for t in tools]
    assert "find_appointments" in tool_names


def test_state_has_expected_keys():
    keys = list(AgentState.__annotations__.keys())
    assert "messages" in keys
    assert "user_id" in keys
    assert "error" in keys


# -- system prompt -------------------------------------------------------------


def test_system_prompt_mentions_role():
    assert "clinical assistant" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_tools():
    assert "find_appointments" in SYSTEM_PROMPT


def test_system_prompt_warns_against_fabrication():
    assert "fabricate" in SYSTEM_PROMPT.lower()


# -- route function ------------------------------------------------------------


def test_route_returns_end_for_plain_message():
    state: AgentState = {
        "messages": [AIMessage(content="Hello")],
        "user_id": "test",
        "error": None,
    }
    assert route(state) == "__end__"


def test_route_returns_tools_for_tool_calls():
    msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "find_appointments", "args": {}, "id": "call_1", "type": "tool_call"}
        ],
    )
    state: AgentState = {
        "messages": [msg],
        "user_id": "test",
        "error": None,
    }
    assert route(state) == "tools"


def test_route_returns_end_for_empty_tool_calls():
    msg = AIMessage(content="Done", tool_calls=[])
    state: AgentState = {
        "messages": [msg],
        "user_id": "test",
        "error": None,
    }
    assert route(state) == "__end__"


# -- error & edge case tests ---------------------------------------------------


def test_route_handles_non_ai_message():
    """HumanMessage (no tool_calls attr) should route to __end__."""
    state: AgentState = {
        "messages": [HumanMessage(content="Hello")],
        "user_id": "test",
        "error": None,
    }
    assert route(state) == "__end__"


async def test_call_llm_returns_messages_key():
    """call_llm should return a dict with 'messages' key."""
    with patch("ai_agent.agent.model_with_tools") as mock_model:
        mock_model.ainvoke = AsyncMock(
            return_value=AIMessage(content="Hello there")
        )
        result = await call_llm(
            {"messages": [HumanMessage(content="hi")], "user_id": "u1", "error": None}
        )
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == "Hello there"


async def test_call_llm_includes_system_prompt():
    """call_llm should prepend a SystemMessage containing 'clinical assistant'."""
    with patch("ai_agent.agent.model_with_tools") as mock_model:
        mock_model.ainvoke = AsyncMock(
            return_value=AIMessage(content="response")
        )
        await call_llm(
            {"messages": [HumanMessage(content="hello")], "user_id": "u1", "error": None}
        )
    call_args = mock_model.ainvoke.call_args[0][0]
    assert isinstance(call_args[0], SystemMessage)
    assert "clinical assistant" in call_args[0].content.lower()


async def test_call_llm_propagates_llm_error():
    """RuntimeError from the LLM should propagate."""
    import pytest as _pytest

    with patch("ai_agent.agent.model_with_tools") as mock_model:
        mock_model.ainvoke = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )
        with _pytest.raises(RuntimeError, match="LLM unavailable"):
            await call_llm(
                {"messages": [HumanMessage(content="hi")], "user_id": "u1", "error": None}
            )


def test_tools_list_contains_all_expected_tools():
    """All 4 registered tools should be present."""
    tool_names = sorted(t.name for t in tools)
    assert tool_names == [
        "draft_encounter_note",
        "find_appointments",
        "get_encounter_context",
        "validate_claim_ready_completeness",
    ]


async def test_call_llm_with_empty_messages():
    """Empty messages list → only SystemMessage is sent to the model."""
    with patch("ai_agent.agent.model_with_tools") as mock_model:
        mock_model.ainvoke = AsyncMock(
            return_value=AIMessage(content="I'm here to help")
        )
        await call_llm(
            {"messages": [], "user_id": "u1", "error": None}
        )
    call_args = mock_model.ainvoke.call_args[0][0]
    # Only the SystemMessage should be in the list
    assert len(call_args) == 1
    assert isinstance(call_args[0], SystemMessage)
