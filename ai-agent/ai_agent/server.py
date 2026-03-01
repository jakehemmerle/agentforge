"""FastAPI server for the OpenEMR AI agent."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from pythonjsonlogger.json import JsonFormatter

from ai_agent.agent import graph
from ai_agent.config import get_settings


def _extract_text(content: Any) -> str:
    """Extract plain text from AIMessage content (str or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content)


# -- logging config ------------------------------------------------------------

_json_formatter = JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
    rename_fields={"asctime": "timestamp", "levelname": "level"},
)

_handler = logging.StreamHandler()
_handler.setFormatter(_json_formatter)

logging.root.handlers.clear()
logging.root.addHandler(_handler)
logging.root.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# -- app -----------------------------------------------------------------------

app = FastAPI(title="OpenEMR AI Agent", version="0.1.0")

_settings = get_settings()
_cors_origins = [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- auth middleware -----------------------------------------------------------


@app.middleware("http")
async def check_api_key(request: Request, call_next):
    """Enforce API key auth when API_KEY is configured."""
    # Let CORS preflight requests pass through without API-key checks.
    # Browsers do not send custom auth headers on preflight.
    if request.method == "OPTIONS":
        return await call_next(request)

    settings = get_settings()
    if request.url.path.startswith("/internal/"):
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "::1"):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    elif settings.api_key and request.url.path not in ("/health",):
        key = request.headers.get("X-API-Key", "")
        if key != settings.api_key:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


# -- request models ------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    session_id: str


# -- endpoints -----------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    request_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": req.session_id},
        "metadata": {
            "session_id": req.session_id,
            "request_id": request_id,
        },
        "run_name": "chat_request",
    }

    try:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=req.message)]},
            config=config,
        )
    except Exception:
        logger.exception("graph.ainvoke failed for session %s", req.session_id)
        return JSONResponse(
            status_code=502,
            content={"detail": "The AI agent encountered an internal error."},
        )

    # Extract the final AI response and all tool calls from messages.
    # The last AIMessage with content is the agent's final answer.
    response_text = ""
    tool_calls: list[dict[str, Any]] = []
    for msg in reversed(result.get("messages", [])):
        if (
            hasattr(msg, "content")
            and msg.content
            and not response_text
            and getattr(msg, "type", None) == "ai"
        ):
            response_text = _extract_text(msg.content)
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({"name": tc["name"], "args": tc["args"]})

    return {
        "session_id": req.session_id,
        "response": response_text,
        "tool_calls": tool_calls,
    }


@app.post("/api/stream")
async def stream(req: ChatRequest):
    request_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": req.session_id},
        "metadata": {
            "session_id": req.session_id,
            "request_id": request_id,
        },
        "run_name": "chat_request",
    }

    async def event_generator():
        # Track active tool depth so we can suppress LLM tokens that
        # originate from nested LLM calls *inside* tools (e.g. the
        # scribe model in draft_encounter_note).  Only the outer
        # agent's LLM tokens should be streamed to the client.
        tool_depth = 0
        try:
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=req.message)]},
                config=config,
                version="v2",
            ):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    if tool_depth > 0:
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        text = _extract_text(chunk.content)
                        if text:
                            # JSON-encode to preserve newlines in SSE framing
                            yield f"data: {json.dumps(text)}\n\n"
                elif kind == "on_tool_start":
                    tool_depth += 1
                    name = event.get("name", "")
                    if name:
                        yield f"data: [calling:{name}]\n\n"
                elif kind == "on_tool_end":
                    tool_depth = max(tool_depth - 1, 0)
                    name = event.get("name", "")
                    output = event.get("data", {}).get("output")
                    if name and not output:
                        # Tool errored — still notify the client so the
                        # spinner is replaced with a status indicator.
                        logger.warning(
                            "on_tool_end for %s had no output; data=%s",
                            name,
                            event.get("data"),
                        )
                        payload = json.dumps({"name": name, "content": "(error)"})
                        yield f"data: [tool_done]{payload}\n\n"
                    if name and output:
                        content = (
                            output.content
                            if hasattr(output, "content")
                            else str(output)
                        )
                        if isinstance(content, list):
                            content = json.dumps(content, indent=2)
                        elif not isinstance(content, str):
                            content = str(content)
                        if len(content) > 2000:
                            content = content[:2000] + "\n..."
                        payload = json.dumps({"name": name, "content": content})
                        yield f"data: [tool_done]{payload}\n\n"
        except Exception:
            logger.exception("Streaming error for session %s", req.session_id)
            yield "data: [ERROR]\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -- internal endpoints (not exposed via chat widget) -------------------------


def _fetch_billing_rows(
    db_host: str,
    db_port: int,
    db_name: str,
    db_user: str,
    db_password: str,
    encounter_id: int,
    patient_id: int,
    db_unix_socket: str = "",
) -> list[dict[str, Any]]:
    """Query the billing table directly via pymysql."""
    import pymysql
    import pymysql.cursors

    connect_kwargs: dict[str, Any] = {
        "host": db_host,
        "port": db_port,
        "database": db_name,
        "user": db_user,
        "password": db_password,
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
        "read_timeout": 10,
    }
    if db_unix_socket:
        connect_kwargs["unix_socket"] = db_unix_socket

    conn = pymysql.connect(**connect_kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code_type, code, code_text, fee, modifier, units "
                "FROM billing "
                "WHERE encounter = %s AND pid = %s AND activity = 1 "
                "ORDER BY code_type, date ASC",
                (encounter_id, patient_id),
            )
            return list(cur.fetchall())
    finally:
        conn.close()


@app.get("/internal/billing")
async def internal_billing(
    encounter_id: int = Query(..., description="Encounter ID"),
    patient_id: int = Query(..., description="Patient ID"),
):
    """Return billing rows for an encounter from the MySQL billing table.

    Internal-only endpoint used by agent tools to avoid direct DB access.
    """
    settings = get_settings()
    try:
        rows = await asyncio.to_thread(
            _fetch_billing_rows,
            db_host=settings.db_host,
            db_port=settings.db_port,
            db_name=settings.db_name,
            db_user=settings.db_user,
            db_password=settings.db_password,
            encounter_id=encounter_id,
            patient_id=patient_id,
            db_unix_socket=settings.db_unix_socket,
        )
    except Exception as exc:
        logger.warning("Failed to query billing table: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"detail": "Billing query failed"},
        )
    return {"data": rows}
