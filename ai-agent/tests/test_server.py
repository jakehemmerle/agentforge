"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from ai_agent.server import app

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _clear_settings_cache():
    """Clear get_settings cache if it exists (safe to call before/after caching is added)."""
    from ai_agent.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()


@pytest.fixture
def authed_client(monkeypatch):
    """Client with API_KEY set — requests must include X-API-Key header."""
    monkeypatch.setenv("API_KEY", "test-secret-key")
    _clear_settings_cache()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        monkeypatch.delenv("API_KEY", raising=False)
        _clear_settings_cache()


# -- health endpoint ----------------------------------------------------------


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


# -- POST /api/chat -----------------------------------------------------------


def test_chat_returns_response(client):
    fake_result = {
        "messages": [
            AIMessage(content="Found 2 appointments for today."),
        ],
    }

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = client.post(
            "/api/chat",
            json={"message": "Show me today's appointments", "session_id": "s1"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s1"
    assert "appointments" in data["response"].lower()
    assert isinstance(data["tool_calls"], list)


def test_chat_collects_tool_calls(client):
    fake_result = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "find_appointments", "args": {"date": "2026-01-01"}, "id": "c1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="Here are the results."),
        ],
    }

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = client.post(
            "/api/chat",
            json={"message": "Find Jan 1 appointments", "session_id": "s2"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tool_calls"]) == 1
    assert data["tool_calls"][0]["name"] == "find_appointments"


def test_chat_requires_message_and_session_id(client):
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 422

    resp = client.post("/api/chat", json={"session_id": "s1"})
    assert resp.status_code == 422


# -- POST /api/stream ---------------------------------------------------------


def test_stream_returns_event_stream(client):
    async def fake_events(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": AIMessage(content="Hello")},
            "name": "",
        }
        yield {
            "event": "on_tool_start",
            "data": {},
            "name": "find_appointments",
        }
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": AIMessage(content=" there")},
            "name": "",
        }

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.astream_events = fake_events
        resp = client.post(
            "/api/stream",
            json={"message": "hello", "session_id": "s3"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "data: Hello" in body
    assert "data: [calling:find_appointments]" in body
    assert "data:  there" in body
    assert "data: [DONE]" in body


def test_stream_headers_disable_buffering(client):
    async def fake_events(*args, **kwargs):
        return
        yield  # make it an async generator

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.astream_events = fake_events
        resp = client.post(
            "/api/stream",
            json={"message": "hi", "session_id": "s4"},
        )

    assert resp.headers.get("x-accel-buffering") == "no"
    assert resp.headers.get("cache-control") == "no-cache"


# -- CORS headers --------------------------------------------------------------


def test_cors_allows_openemr_origin(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8300",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8300"


# -- API key authentication ---------------------------------------------------


def test_chat_rejects_missing_api_key(authed_client):
    """When API_KEY is configured, requests without X-API-Key get 401."""
    fake_result = {
        "messages": [AIMessage(content="Hello")],
    }
    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = authed_client.post(
            "/api/chat",
            json={"message": "hi", "session_id": "s1"},
        )
    assert resp.status_code == 401


def test_chat_rejects_wrong_api_key(authed_client):
    """When API_KEY is configured, requests with wrong key get 401."""
    fake_result = {
        "messages": [AIMessage(content="Hello")],
    }
    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = authed_client.post(
            "/api/chat",
            json={"message": "hi", "session_id": "s1"},
            headers={"X-API-Key": "wrong-key"},
        )
    assert resp.status_code == 401


def test_chat_accepts_correct_api_key(authed_client):
    """When API_KEY is configured, requests with correct key succeed."""
    fake_result = {
        "messages": [AIMessage(content="Hello")],
    }
    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = authed_client.post(
            "/api/chat",
            json={"message": "hi", "session_id": "s1"},
            headers={"X-API-Key": "test-secret-key"},
        )
    assert resp.status_code == 200


def test_stream_rejects_missing_api_key(authed_client):
    """SSE endpoint also requires API key."""
    async def fake_events(*args, **kwargs):
        return
        yield

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.astream_events = fake_events
        resp = authed_client.post(
            "/api/stream",
            json={"message": "hi", "session_id": "s1"},
        )
    assert resp.status_code == 401


def test_preflight_skips_api_key_auth(authed_client):
    """CORS preflight OPTIONS should not require X-API-Key."""
    resp = authed_client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:8300",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-api-key",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8300"


def test_health_does_not_require_api_key(authed_client):
    """Health endpoint is always open — no API key needed."""
    resp = authed_client.get("/health")
    assert resp.status_code == 200


def test_no_api_key_configured_allows_all(client):
    """When API_KEY is empty (dev mode), requests succeed without header."""
    fake_result = {
        "messages": [AIMessage(content="Hello")],
    }
    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = client.post(
            "/api/chat",
            json={"message": "hi", "session_id": "s1"},
        )
    assert resp.status_code == 200


# -- list content handling ----------------------------------------------------


def test_chat_extracts_text_from_list_content(client):
    """AIMessage.content can be a list of blocks when Claude uses tools."""
    fake_result = {
        "messages": [
            AIMessage(content=[
                {"type": "text", "text": "I'll look that up for you."},
            ]),
        ],
    }

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = client.post(
            "/api/chat",
            json={"message": "hi", "session_id": "s1"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["response"], str)
    assert "look that up" in data["response"]


def test_chat_extracts_text_from_mixed_list_content(client):
    """List content with multiple blocks should concatenate text blocks."""
    fake_result = {
        "messages": [
            AIMessage(content=[
                {"type": "text", "text": "Here are "},
                {"type": "text", "text": "the results."},
            ]),
        ],
    }

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        resp = client.post(
            "/api/chat",
            json={"message": "hi", "session_id": "s1"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Here are the results."


def test_stream_handles_list_content_chunks(client):
    """Streaming chunks with list content should yield text strings."""
    async def fake_events(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": AIMessage(content=[
                {"type": "text", "text": "streaming token"},
            ])},
            "name": "",
        }

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.astream_events = fake_events
        resp = client.post(
            "/api/stream",
            json={"message": "hello", "session_id": "s5"},
        )

    assert resp.status_code == 200
    body = resp.text
    assert "data: streaming token" in body


# -- graph error handling -----------------------------------------------------


def test_chat_handles_graph_error(client):
    """When graph.ainvoke raises RuntimeError, the server returns a 502 response."""
    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("Graph error"))
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "session_id": "err1"},
        )
    assert resp.status_code == 502
    assert "internal error" in resp.json()["detail"].lower()


def test_stream_handles_graph_error(client):
    """When graph.astream_events raises, the stream still sends [DONE] so clients don't hang."""
    async def failing_events(*args, **kwargs):
        raise RuntimeError("Graph error")
        yield  # make it an async generator

    with patch("ai_agent.server.graph") as mock_graph:
        mock_graph.astream_events = failing_events
        resp = client.post(
            "/api/stream",
            json={"message": "hello", "session_id": "err2"},
        )
    # Error happens during streaming; headers (200) are already committed.
    # The [DONE] terminator MUST still be sent so the client can clean up.
    assert "data: [DONE]" in resp.text
