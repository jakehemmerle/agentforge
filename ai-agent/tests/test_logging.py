"""Tests for ai_agent.tools._logging — PHI sanitization and structured logging."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest
from langchain_core.tools import ToolException

from ai_agent.tools._logging import (
    _sanitize_dict,
    _sanitize_input,
    _sanitize_output,
    classify_error,
    logged_tool,
)


# ---------------------------------------------------------------------------
# _sanitize_dict()
# ---------------------------------------------------------------------------


class TestSanitizeDict:
    """Tests for _sanitize_dict()."""

    def test_redacts_phi_keys(self):
        """PHI keys like fname/lname are replaced with [REDACTED]."""
        result = _sanitize_dict({"fname": "John", "lname": "Doe", "encounter_id": 123})
        assert result["fname"] == "[REDACTED]"
        assert result["lname"] == "[REDACTED]"
        assert result["encounter_id"] == 123

    def test_phi_output_key_dict_value(self):
        """PHI output keys with dict values become '{...}'."""
        result = _sanitize_dict({"patient": {"fname": "John", "lname": "Doe"}})
        assert result["patient"] == "{...}"

    def test_phi_output_key_list_value(self):
        """PHI output keys with list values become '[N items]'."""
        result = _sanitize_dict(
            {"medications": [{"drug": "aspirin"}, {"drug": "tylenol"}]}
        )
        assert result["medications"] == "[2 items]"

    def test_phi_output_key_other_value(self):
        """PHI output keys with scalar values become '[REDACTED]'."""
        result = _sanitize_dict({"draft": "Patient John Doe has..."})
        assert result["draft"] == "[REDACTED]"

    def test_recurses_into_nested_dicts_at_depth_0(self):
        """Nested dicts are sanitized at depth=0."""
        result = _sanitize_dict({"data": {"fname": "John", "ok": True}})
        assert result["data"]["fname"] == "[REDACTED]"
        assert result["data"]["ok"] is True

    def test_stops_recursion_at_depth_1(self):
        """At depth=1, nested dicts are left as-is (not recursed)."""
        inner = {"fname": "John", "ok": True}
        result = _sanitize_dict({"data": inner}, depth=1)
        assert result["data"] == inner

    def test_empty_dict(self):
        """Empty dict returns empty dict."""
        assert _sanitize_dict({}) == {}


# ---------------------------------------------------------------------------
# _sanitize_input()
# ---------------------------------------------------------------------------


class TestSanitizeInput:
    def test_delegates_to_sanitize_dict(self):
        """_sanitize_input is a thin wrapper around _sanitize_dict."""
        result = _sanitize_input({"fname": "John", "encounter_id": 5})
        assert result["fname"] == "[REDACTED]"
        assert result["encounter_id"] == 5


# ---------------------------------------------------------------------------
# _sanitize_output()
# ---------------------------------------------------------------------------


class TestSanitizeOutput:
    def test_dict_input_sanitized_and_truncated(self):
        """Dict output is sanitized then truncated to 200 chars."""
        data = {"fname": "John", "status": "ok"}
        result = _sanitize_output(data)
        assert "[REDACTED]" in result
        assert len(result) <= 200

    def test_non_dict_input_truncated(self):
        """Non-dict output is converted to string and truncated."""
        long_string = "x" * 300
        result = _sanitize_output(long_string)
        assert len(result) == 200

    def test_dict_with_phi_redacted_in_output(self):
        """PHI values should not appear in the sanitized output string."""
        result = _sanitize_output({"fname": "SensitiveName", "code": "12345"})
        assert "SensitiveName" not in result
        assert "[REDACTED]" in result


# ---------------------------------------------------------------------------
# classify_error()
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_timeout_exception(self):
        assert classify_error(httpx.TimeoutException("timed out")) == "api_timeout"

    def test_http_401(self):
        resp = httpx.Response(401, request=httpx.Request("GET", "/test"))
        exc = httpx.HTTPStatusError("Unauthorized", request=resp.request, response=resp)
        assert classify_error(exc) == "auth_error"

    def test_http_403(self):
        resp = httpx.Response(403, request=httpx.Request("GET", "/test"))
        exc = httpx.HTTPStatusError("Forbidden", request=resp.request, response=resp)
        assert classify_error(exc) == "auth_error"

    def test_http_404(self):
        resp = httpx.Response(404, request=httpx.Request("GET", "/test"))
        exc = httpx.HTTPStatusError("Not Found", request=resp.request, response=resp)
        assert classify_error(exc) == "not_found"

    def test_tool_exception_validation(self):
        exc = ToolException("invalid input provided")
        assert classify_error(exc) == "validation_error"

    def test_runtime_error_unknown(self):
        assert classify_error(RuntimeError("unexpected")) == "unknown"

    def test_http_500_unknown(self):
        resp = httpx.Response(500, request=httpx.Request("GET", "/test"))
        exc = httpx.HTTPStatusError("Server Error", request=resp.request, response=resp)
        assert classify_error(exc) == "unknown"


# ---------------------------------------------------------------------------
# logged_tool()
# ---------------------------------------------------------------------------


class TestLoggedTool:
    async def test_success_logs_start_and_end(self, caplog):
        """Successful call logs tool_call_start and tool_call_end with status=success."""

        @logged_tool
        async def my_tool(**kwargs):
            return {"result": "ok"}

        with caplog.at_level(logging.INFO, logger="ai_agent.tools"):
            result = await my_tool(encounter_id=5)

        assert result == {"result": "ok"}

        messages = [r.message for r in caplog.records]
        assert "tool_call_start" in messages
        assert "tool_call_end" in messages

        end_record = next(r for r in caplog.records if r.message == "tool_call_end")
        assert end_record.__dict__["status"] == "success"
        assert end_record.__dict__["latency_ms"] >= 0

    async def test_error_propagates_and_logs(self, caplog):
        """Exception propagates and is logged as tool_call_error."""

        @logged_tool
        async def failing_tool(**kwargs):
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR, logger="ai_agent.tools"):
            with pytest.raises(ValueError, match="boom"):
                await failing_tool()

        error_records = [r for r in caplog.records if r.message == "tool_call_error"]
        assert len(error_records) == 1
        assert error_records[0].__dict__["error_type"] == "ValueError"

    async def test_input_phi_redacted_in_logs(self, caplog):
        """PHI keys in kwargs are [REDACTED] in the start log."""

        @logged_tool
        async def my_tool(**kwargs):
            return "ok"

        with caplog.at_level(logging.INFO, logger="ai_agent.tools"):
            await my_tool(fname="SensitiveFirst", lname="SensitiveLast", encounter_id=1)

        start_record = next(r for r in caplog.records if r.message == "tool_call_start")
        logged_input = start_record.__dict__["input"]
        assert logged_input["fname"] == "[REDACTED]"
        assert logged_input["lname"] == "[REDACTED]"
        assert logged_input["encounter_id"] == 1

    async def test_output_phi_redacted_in_logs(self, caplog):
        """PHI in return value is absent from end log's output_summary."""

        @logged_tool
        async def my_tool(**kwargs):
            return {"fname": "SensitiveName", "code": "ok"}

        with caplog.at_level(logging.INFO, logger="ai_agent.tools"):
            await my_tool()

        end_record = next(r for r in caplog.records if r.message == "tool_call_end")
        output_summary = end_record.__dict__["output_summary"]
        assert "SensitiveName" not in output_summary

    async def test_langsmith_enrichment_on_error(self, caplog):
        """On error, LangSmith run tree metadata is updated."""
        mock_rt = MagicMock()
        mock_rt.metadata = {}

        @logged_tool
        async def failing_tool(**kwargs):
            raise RuntimeError("test error")

        with patch(
            "ai_agent.tools._logging.get_current_run_tree",
            create=True,
        ):
            # We need to patch it in the right place — the function imports it inside the wrapper
            with patch(
                "langsmith.run_helpers.get_current_run_tree",
                return_value=mock_rt,
            ):
                with caplog.at_level(logging.ERROR, logger="ai_agent.tools"):
                    with pytest.raises(RuntimeError):
                        await failing_tool()

        assert mock_rt.metadata.get("error_type") == "RuntimeError"
        assert mock_rt.metadata.get("error_category") == "unknown"
        assert mock_rt.metadata.get("error_msg") == "test error"
