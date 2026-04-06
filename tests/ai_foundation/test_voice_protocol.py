"""Tests for voice WebSocket protocol message schemas."""

from __future__ import annotations

from lib.ai_foundation.voice.protocol import (
    AgentDoneMsg,
    EndOfSpeechMsg,
    InterruptMsg,
    ResponseTextMsg,
    SessionEndMsg,
    SessionEndedMsg,
    SessionReadyMsg,
    SessionStartMsg,
    ThinkingAloudMsg,
    TranscriptMsg,
    VoiceErrorMsg,
    VoiceStatusMsg,
)


class TestClientMessages:
    def test_session_start_defaults(self):
        msg = SessionStartMsg()
        assert msg.type == "session_start"
        assert msg.thread_id is None
        assert msg.metadata == {}

    def test_session_start_with_data(self):
        msg = SessionStartMsg(thread_id="t_123", metadata={"local_time": "2026-04-06T10:00:00"})
        d = msg.model_dump()
        assert d["type"] == "session_start"
        assert d["thread_id"] == "t_123"
        assert d["metadata"]["local_time"] == "2026-04-06T10:00:00"

    def test_end_of_speech(self):
        msg = EndOfSpeechMsg()
        assert msg.type == "end_of_speech"

    def test_interrupt(self):
        msg = InterruptMsg()
        assert msg.type == "interrupt"

    def test_session_end(self):
        msg = SessionEndMsg()
        assert msg.type == "session_end"


class TestServerMessages:
    def test_session_ready(self):
        msg = SessionReadyMsg(session_id="vs_abc123")
        d = msg.model_dump()
        assert d["type"] == "session_ready"
        assert d["session_id"] == "vs_abc123"

    def test_transcript(self):
        msg = TranscriptMsg(text="What was my glucose?", language="en", duration_seconds=2.5)
        d = msg.model_dump()
        assert d["type"] == "transcript"
        assert d["text"] == "What was my glucose?"
        assert d["is_final"] is True

    def test_voice_status(self):
        msg = VoiceStatusMsg(stage="analyzing", message="Looking at your data...")
        d = msg.model_dump()
        assert d["type"] == "status"
        assert d["stage"] == "analyzing"

    def test_thinking_aloud(self):
        msg = ThinkingAloudMsg(phrase="Let me check your records...")
        d = msg.model_dump()
        assert d["type"] == "thinking_aloud"
        assert d["phrase"] == "Let me check your records..."

    def test_response_text(self):
        msg = ResponseTextMsg(text="Your glucose was 128 mg/dL.")
        d = msg.model_dump()
        assert d["type"] == "response_text"

    def test_agent_done(self):
        msg = AgentDoneMsg(
            suggestions=[{"label": "More", "description": "Tell me more"}],
            trace_id="trc_123",
            latency_ms=2340,
        )
        d = msg.model_dump()
        assert d["type"] == "agent_done"
        assert len(d["suggestions"]) == 1
        assert d["trace_id"] == "trc_123"

    def test_agent_done_defaults(self):
        msg = AgentDoneMsg()
        d = msg.model_dump()
        assert d["suggestions"] == []
        assert d["trace_id"] is None

    def test_voice_error(self):
        msg = VoiceErrorMsg(code="stt_failed", message="Could not understand audio.")
        d = msg.model_dump()
        assert d["type"] == "error"
        assert d["code"] == "stt_failed"

    def test_session_ended(self):
        msg = SessionEndedMsg()
        assert msg.type == "session_ended"
