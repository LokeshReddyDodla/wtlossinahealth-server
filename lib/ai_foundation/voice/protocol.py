"""
WebSocket protocol — message schemas for voice agent communication.

Binary frames carry raw audio. Text frames carry JSON control messages.
All JSON messages have a ``type`` field for discrimination.

Shared event types (same as text chat SSE):
    status, intent, reasoning, tool_call, tool_result, plan,
    reflection, specialist_start, specialist_done, token, done, error

Voice-only event types:
    session_ready, greeting, transcript, response_text, session_ended
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
# Server → Client (JSON) — voice-only messages
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
    audio_url: str | None = None


class ResponseTextMsg(BaseModel):
    """Final agent response as text (for display alongside audio)."""

    type: Literal["response_text"] = "response_text"
    text: str


class SessionEndedMsg(BaseModel):
    """Server confirms the session has ended."""

    type: Literal["session_ended"] = "session_ended"


class VoiceErrorMsg(BaseModel):
    """Voice-specific error (STT failure, buffer overflow, etc)."""

    type: Literal["error"] = "error"
    code: str
    message: str
