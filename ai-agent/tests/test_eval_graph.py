"""Tests for eval graph behavior parity with production routing."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from evals import eval_graph as eval_graph_module

pytestmark = pytest.mark.unit


class _FakeBoundModel:
    async def ainvoke(self, _messages):
        # No tool calls -> route() should send this through "verify".
        return AIMessage(content="Please provide a patient name or ID.")


class _FakeModel:
    def __init__(self, *args, **kwargs):
        pass

    def bind_tools(self, _tools):
        return _FakeBoundModel()


async def test_eval_graph_handles_verify_route(monkeypatch):
    monkeypatch.setattr(eval_graph_module, "ChatAnthropic", _FakeModel)

    graph = eval_graph_module.create_eval_graph("ambiguous_patient_query")
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="Show me the patient's appointments")]},
        config={"configurable": {"thread_id": "eval-route-test"}},
    )

    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert "patient name" in final.content.lower()
