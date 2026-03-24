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
    # Agentic reasoning events
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    # Multi-agent pipeline events
    PLAN = "plan"
    REFLECTION = "reflection"
    SPECIALIST_START = "specialist_start"
    SPECIALIST_DONE = "specialist_done"


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
# Agentic reasoning events
# ---------------------------------------------------------------------------


def sse_reasoning(step: int, thought: str) -> str:
    """Emit a REASONING event — the doctor's internal thought process."""
    return sse_event(SSEEventType.REASONING, {"step": step, "thought": thought})


def sse_tool_call(tool: str, args: dict[str, Any], reason: str | None = None) -> str:
    """Emit a TOOL_CALL event — the doctor deciding to look at specific data."""
    data: dict[str, Any] = {"tool": tool, "args": args}
    if reason:
        data["reason"] = reason
    return sse_event(SSEEventType.TOOL_CALL, data)


def sse_tool_result(tool: str, summary: str) -> str:
    """Emit a TOOL_RESULT event — brief summary of what the doctor found."""
    return sse_event(SSEEventType.TOOL_RESULT, {"tool": tool, "summary": summary})


# ---------------------------------------------------------------------------
# Multi-agent pipeline events
# ---------------------------------------------------------------------------


def sse_plan(strategy: str, steps: int, domains: list[str]) -> str:
    """Emit a PLAN event — the investigation strategy before execution."""
    return sse_event(SSEEventType.PLAN, {
        "strategy": strategy, "steps": steps, "domains": domains,
    })


def sse_reflection(confidence: float, gaps: list[str], is_complete: bool) -> str:
    """Emit a REFLECTION event — the critic's assessment of the investigation."""
    return sse_event(SSEEventType.REFLECTION, {
        "confidence": confidence, "gaps": gaps, "is_complete": is_complete,
    })


def sse_specialist_start(domain: str, step_count: int) -> str:
    """Emit a SPECIALIST_START event — a domain expert begins investigating."""
    return sse_event(SSEEventType.SPECIALIST_START, {
        "domain": domain, "steps": step_count,
    })


def sse_specialist_done(domain: str, summary: str) -> str:
    """Emit a SPECIALIST_DONE event — a domain expert completed its investigation."""
    return sse_event(SSEEventType.SPECIALIST_DONE, {
        "domain": domain, "summary": summary,
    })


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
