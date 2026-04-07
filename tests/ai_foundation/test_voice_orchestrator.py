"""Tests for VoiceOrchestrator — integration test with mocked STT/TTS/Agent."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.orchestrator import VoiceOrchestrator
from lib.ai_foundation.voice.session import VoiceSession, VoiceSessionState
from lib.ai_foundation.voice.stt import TranscriptionResult


def _settings(**overrides) -> VoiceSettings:
    return VoiceSettings(**overrides)


def _session(settings: VoiceSettings | None = None) -> VoiceSession:
    s = settings or _settings()
    return VoiceSession(
        user_id="user_1",
        patient_id="patient_1",
        thread_id="bot:patient:patient_1",
        settings=s,
    )


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _make_tts():
    mock_tts = AsyncMock()

    async def fake_stream(text):
        yield b"\x00" * 100

    mock_tts.synthesize_stream = MagicMock(side_effect=lambda t: fake_stream(t))
    return mock_tts


class TestVoiceOrchestrator:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_thoughts(self):
        """STT → reasoning (spoken) → tool_call (spoken) → response (spoken) → done."""
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="How is my glucose today?", language="en", duration_seconds=2.0,
        )

        mock_tts = _make_tts()
        mock_agent = AsyncMock()

        async def fake_run_stream(agent_input):
            yield _sse_event("status", {"stage": "extracting_intent"})
            yield _sse_event("reasoning", {"step": 1, "thought": "Let me check glucose data"})
            yield _sse_event("tool_call", {"tool": "look_up", "args": {"data_types": ["cgm_range_stats"]}, "reason": "Checking glucose"})
            yield _sse_event("tool_result", {"tool": "look_up", "summary": "Found 7 days of data"})
            yield _sse_event("token", {"delta": "Your glucose is fine."})
            yield _sse_event("done", {
                "suggestions": [{"label": "More"}],
                "trace_id": "trc_1",
                "latency_ms": 1500,
                "data": {"full_response": "Your glucose is fine."},
            })

        mock_agent.run_stream = MagicMock(side_effect=lambda i: fake_run_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), memory=AsyncMock(), settings=settings,
        )

        session = _session(settings)
        json_messages = []
        binary_messages = []

        await orchestrator.handle_utterance(
            session, b"\x00" * 1000,
            send_json=lambda d: _async_append(json_messages, d),
            send_bytes=lambda b: _async_append(binary_messages, b),
        )

        types = [m["type"] for m in json_messages]

        # All events forwarded
        assert "transcript" in types
        assert "status" in types
        assert "reasoning" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "response_text" in types
        assert "done" in types

        # TTS was called for thoughts + response
        assert mock_tts.synthesize_stream.call_count >= 2  # at least reasoning + response

        # Binary audio was sent
        assert len(binary_messages) > 0

        assert session.state == VoiceSessionState.IDLE

    @pytest.mark.asyncio
    async def test_thoughts_spoken_sequentially(self):
        """Each thought waits for the previous to finish before speaking."""
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="Tell me about today", language="en", duration_seconds=1.5,
        )

        speak_order = []
        mock_tts = AsyncMock()

        async def fake_stream(text):
            speak_order.append(text[:30])
            yield b"\x00" * 50

        mock_tts.synthesize_stream = MagicMock(side_effect=lambda t: fake_stream(t))

        mock_agent = AsyncMock()

        async def fake_run_stream(agent_input):
            yield _sse_event("reasoning", {"step": 1, "thought": "First thought"})
            yield _sse_event("reasoning", {"step": 2, "thought": "Second thought"})
            yield _sse_event("done", {"data": {"full_response": "Final answer."}})

        mock_agent.run_stream = MagicMock(side_effect=lambda i: fake_run_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), memory=AsyncMock(), settings=settings,
        )

        session = _session(settings)

        await orchestrator.handle_utterance(
            session, b"\x00" * 500,
            send_json=lambda d: _async_append([], d),
            send_bytes=AsyncMock(),
        )

        # All three were spoken: two thoughts + final response
        assert len(speak_order) == 3
        assert "First thought" in speak_order[0]
        assert "Second thought" in speak_order[1]
        assert "Final answer" in speak_order[2]

    @pytest.mark.asyncio
    async def test_empty_transcript_sends_error(self):
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="   ", language="en", duration_seconds=0.5,
        )

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=AsyncMock(), agent=AsyncMock(), patient_resolver=AsyncMock(), memory=AsyncMock(), settings=settings,
        )

        session = _session(settings)
        json_messages = []

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=lambda d: _async_append(json_messages, d),
            send_bytes=AsyncMock(),
        )

        types = [m["type"] for m in json_messages]
        assert "error" in types
        error_msg = next(m for m in json_messages if m["type"] == "error")
        assert error_msg["code"] == "empty_transcript"

    @pytest.mark.asyncio
    async def test_stt_failure_sends_error(self):
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.side_effect = RuntimeError("API error")

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=AsyncMock(), agent=AsyncMock(), patient_resolver=AsyncMock(), memory=AsyncMock(), settings=settings,
        )

        session = _session(settings)
        json_messages = []

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=lambda d: _async_append(json_messages, d),
            send_bytes=AsyncMock(),
        )

        types = [m["type"] for m in json_messages]
        assert "error" in types
        error_msg = next(m for m in json_messages if m["type"] == "error")
        assert error_msg["code"] == "stt_failed"

    @pytest.mark.asyncio
    async def test_interrupt_stops_pipeline(self):
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="Tell me about my glucose", language="en", duration_seconds=2.0,
        )

        mock_tts = _make_tts()
        mock_agent = AsyncMock()

        async def slow_stream(agent_input):
            yield _sse_event("status", {"stage": "analyzing"})
            yield _sse_event("token", {"delta": "Your glucose..."})
            yield _sse_event("done", {"data": {"full_response": "Your glucose..."}})

        mock_agent.run_stream = MagicMock(side_effect=lambda i: slow_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), memory=AsyncMock(), settings=settings,
        )

        session = _session(settings)
        json_messages = []

        async def send_json_and_interrupt(data):
            json_messages.append(data)
            if data.get("type") == "status":
                session.interrupt()

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=send_json_and_interrupt,
            send_bytes=AsyncMock(),
        )

        types = [m["type"] for m in json_messages]
        assert "done" not in types

    @pytest.mark.asyncio
    async def test_voice_metadata_set(self):
        """Verify output_mode='voice' is passed in agent input metadata."""
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="Hello", language="en", duration_seconds=1.0,
        )

        mock_tts = _make_tts()
        mock_agent = AsyncMock()
        captured_input = []

        async def capture_stream(agent_input):
            captured_input.append(agent_input)
            yield _sse_event("done", {"data": {"full_response": "Hi there."}})

        mock_agent.run_stream = MagicMock(side_effect=lambda i: capture_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), memory=AsyncMock(), settings=settings,
        )

        session = _session(settings)

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=lambda d: _async_append([], d),
            send_bytes=AsyncMock(),
        )

        assert len(captured_input) == 1
        assert captured_input[0].context.metadata["output_mode"] == "voice"


async def _async_append(lst: list, item):
    lst.append(item)
