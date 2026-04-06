"""
WebSocket protocol — message schemas for voice agent communication.

Binary frames carry raw audio. Text frames carry JSON control messages.
All JSON messages have a ``type`` field for discrimination.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Client → Server (JSON)
# ---------------------------------------------------------------------------


class SessionStartMsg(BaseModel):
    """Client requests a new voice session."""

    type: Literal["session_start"] = "session_start"
    thread_id: str | None = Field(default=None, description="Existing thread to continue, or None for new")
    metadata: dict[str, Any] = Field(default_factory=dict, description="local_time, tier, etc.")


class EndOfSpeechMsg(BaseModel):
    """Client signals the user stopped speaking (client-side VAD)."""

    type: Literal["end_of_speech"] = "end_of_speech"


class InterruptMsg(BaseModel):
    """Client wants to interrupt the agent mid-response."""

    type: Literal["interrupt"] = "interrupt"


class SessionEndMsg(BaseModel):
    """Client ends the voice session."""

    type: Literal["session_end"] = "session_end"


# ---------------------------------------------------------------------------
# Server → Client (JSON)
# ---------------------------------------------------------------------------


class SessionReadyMsg(BaseModel):
    """Server confirms the voice session is active."""

    type: Literal["session_ready"] = "session_ready"
    session_id: str


class TranscriptMsg(BaseModel):
    """Transcription of the user's speech."""

    type: Literal["transcript"] = "transcript"
    text: str
    is_final: bool = True
    language: str | None = None
    duration_seconds: float | None = None


class VoiceStatusMsg(BaseModel):
    """Agent pipeline status update."""

    type: Literal["status"] = "status"
    stage: str
    message: str | None = None


class ThinkingAloudMsg(BaseModel):
    """Agent is speaking a filler phrase while thinking."""

    type: Literal["thinking_aloud"] = "thinking_aloud"
    phrase: str


class ResponseTextMsg(BaseModel):
    """Final agent response as text (for display alongside audio)."""

    type: Literal["response_text"] = "response_text"
    text: str


class AgentDoneMsg(BaseModel):
    """Agent finished processing — mirrors SSE done event."""

    type: Literal["agent_done"] = "agent_done"
    suggestions: list[dict[str, str]] = Field(default_factory=list)
    trace_id: str | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None


class VoiceErrorMsg(BaseModel):
    """Error during voice pipeline."""

    type: Literal["error"] = "error"
    code: str
    message: str


class SessionEndedMsg(BaseModel):
    """Server confirms the session has ended."""

    type: Literal["session_ended"] = "session_ended"
