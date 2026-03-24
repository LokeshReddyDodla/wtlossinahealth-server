"""
SSE (Server-Sent Events) utilities for streaming AI responses to clients.

Formats events according to the SSE spec (https://html.spec.whatwg.org/multipage/server-sent-events.html).
Works with both browser EventSource API and mobile HTTP streaming clients.

Event types:
    status  — pipeline stage updates (instant UX feedback)
    intent  — extracted intent payload
    token   — individual response token (delta streaming)
    done    — final metadata (suggestions, trace_id, cost, latency)
    error   — error with optional fallback message
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SSEEventType(str, Enum):
    """Standard event types emitted during an agent pipeline."""

    STATUS = "status"
    INTENT = "intent"
    TOKEN = "token"
    DONE = "done"
    ERROR = "error"


class PipelineStage(str, Enum):
    """Named stages in the agent pipeline, sent as STATUS events."""

    UNDERSTANDING_QUERY = "understanding_query"
    EXTRACTING_INTENT = "extracting_intent"
    FETCHING_DATA = "fetching_data"
    ANALYZING = "analyzing"
    GENERATING_RESPONSE = "generating_response"


class SSEDonePayload(BaseModel):
    """Payload for the final DONE event."""

    model_config = {"protected_namespaces": ()}

    suggestions: list[dict[str, str]] = Field(default_factory=list)
    trace_id: str | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    model_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SSEErrorPayload(BaseModel):
    """Payload for ERROR events."""

    message: str
    code: str = "internal_error"
    fallback_text: str | None = None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def sse_event(event_type: str | SSEEventType, data: dict[str, Any] | str) -> str:
    """Format a single Server-Sent Event.

    Args:
        event_type: The event name (maps to EventSource ``event`` field).
        data: JSON-serializable dict or raw string for the ``data`` field.

    Returns:
        Fully formatted SSE event string with trailing double newline.
    """
    event_name = event_type.value if isinstance(event_type, SSEEventType) else event_type
    payload = json.dumps(data, default=str) if isinstance(data, dict) else data
    return f"event: {event_name}\ndata: {payload}\n\n"


def sse_status(stage: str | PipelineStage, message: str | None = None) -> str:
    """Convenience: emit a STATUS event for a pipeline stage."""
    stage_value = stage.value if isinstance(stage, PipelineStage) else stage
    data: dict[str, Any] = {"stage": stage_value}
    if message:
        data["message"] = message
    return sse_event(SSEEventType.STATUS, data)


def sse_token(delta: str) -> str:
    """Convenience: emit a TOKEN event with a text delta."""
    return sse_event(SSEEventType.TOKEN, {"delta": delta})


def sse_intent(intent_data: dict[str, Any]) -> str:
    """Convenience: emit an INTENT event with the extracted intent payload."""
    return sse_event(SSEEventType.INTENT, intent_data)


def sse_done(payload: SSEDonePayload | dict[str, Any]) -> str:
    """Convenience: emit a DONE event with final metadata."""
    data = payload.model_dump(exclude_none=True) if isinstance(payload, SSEDonePayload) else payload
    return sse_event(SSEEventType.DONE, data)


def sse_error(
    message: str,
    code: str = "internal_error",
    fallback_text: str | None = None,
) -> str:
    """Convenience: emit an ERROR event."""
    payload = SSEErrorPayload(message=message, code=code, fallback_text=fallback_text)
    return sse_event(SSEEventType.ERROR, payload.model_dump(exclude_none=True))


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------

SSE_RESPONSE_HEADERS: dict[str, str] = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
"""Standard response headers for SSE endpoints. Use with StreamingResponse."""
