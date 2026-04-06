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
from lib.ai_foundation.voice.thinking_aloud import ThinkingAloudMapper


def _settings(**overrides) -> VoiceSettings:
    return VoiceSettings(
        THINKING_ALOUD_ENABLED=True,
        THINKING_COOLDOWN_SECONDS=0,
        THINKING_MAX_FILLERS_PER_TURN=3,
        **overrides,
    )


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


class TestVoiceOrchestrator:
    @pytest.mark.asyncio
    async def test_full_pipeline_happy_path(self):
        """STT → Agent stream → TTS → client receives transcript, status, response, done."""
        settings = _settings()

        # Mock STT
        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="How is my glucose today?",
            language="en",
            duration_seconds=2.0,
        )

        # Mock TTS
        mock_tts = AsyncMock()

        async def fake_stream(text):
            yield b"\x00" * 100  # Fake audio chunk

        mock_tts.synthesize_stream = MagicMock(side_effect=lambda t: fake_stream(t))
        mock_tts.synthesize.return_value = b"\x00" * 50

        # Mock Agent — yields status + tokens + done
        mock_agent = AsyncMock()

        async def fake_run_stream(agent_input):
            yield _sse_event("status", {"stage": "analyzing", "message": "Looking..."})
            yield _sse_event("token", {"delta": "Your "})
            yield _sse_event("token", {"delta": "glucose "})
            yield _sse_event("token", {"delta": "is fine."})
            yield _sse_event("done", {
                "suggestions": [{"label": "More"}],
                "trace_id": "trc_1",
                "latency_ms": 1500,
                "data": {"full_response": "Your glucose is fine."},
            })

        mock_agent.run_stream = MagicMock(side_effect=lambda i: fake_run_stream(i))

        mapper = ThinkingAloudMapper(settings=settings)
        orchestrator = VoiceOrchestrator(
            stt=mock_stt,
            tts=mock_tts,
            agent=mock_agent,
            thinking_mapper=mapper,
            settings=settings,
        )

        session = _session(settings)
        json_messages = []
        binary_messages = []

        async def send_json(data):
            json_messages.append(data)

        async def send_bytes(data):
            binary_messages.append(data)

        await orchestrator.handle_utterance(
            session,
            b"\x00" * 1000,
            send_json=send_json,
            send_bytes=send_bytes,
        )

        # Verify STT was called
        mock_stt.transcribe.assert_called_once_with(b"\x00" * 1000)

        # Verify messages sent to client
        types = [m["type"] for m in json_messages]
        assert "transcript" in types
        assert "response_text" in types
        assert "agent_done" in types

        # Verify transcript content
        transcript_msg = next(m for m in json_messages if m["type"] == "transcript")
        assert transcript_msg["text"] == "How is my glucose today?"

        # Verify done metadata
        done_msg = next(m for m in json_messages if m["type"] == "agent_done")
        assert done_msg["trace_id"] == "trc_1"

        # Session should be back to idle
        assert session.state == VoiceSessionState.IDLE

    @pytest.mark.asyncio
    async def test_empty_transcript_sends_error(self):
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="   ", language="en", duration_seconds=0.5,
        )

        mock_tts = AsyncMock()
        mock_agent = AsyncMock()
        mapper = ThinkingAloudMapper(settings=settings)

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent,
            thinking_mapper=mapper, settings=settings,
        )

        session = _session(settings)
        json_messages = []

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=lambda d: _append(json_messages, d),
            send_bytes=AsyncMock(),
        )

        # Should get transcript then error
        types = [m["type"] for m in json_messages]
        assert "transcript" in types
        assert "error" in types
        error_msg = next(m for m in json_messages if m["type"] == "error")
        assert error_msg["code"] == "empty_transcript"
        assert session.state == VoiceSessionState.IDLE

    @pytest.mark.asyncio
    async def test_stt_failure_sends_error(self):
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.side_effect = RuntimeError("API error")

        mock_tts = AsyncMock()
        mock_agent = AsyncMock()
        mapper = ThinkingAloudMapper(settings=settings)

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent,
            thinking_mapper=mapper, settings=settings,
        )

        session = _session(settings)
        json_messages = []

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=lambda d: _append(json_messages, d),
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

        mock_tts = AsyncMock()
        mock_tts.synthesize.return_value = b"\x00" * 50

        mock_agent = AsyncMock()

        async def slow_stream(agent_input):
            yield _sse_event("status", {"stage": "analyzing"})
            yield _sse_event("token", {"delta": "Your "})
            # Simulate interrupt during stream
            yield _sse_event("token", {"delta": "glucose "})
            yield _sse_event("token", {"delta": "is "})
            yield _sse_event("done", {"suggestions": [], "data": {"full_response": "Your glucose is..."}})

        mock_agent.run_stream = MagicMock(side_effect=lambda i: slow_stream(i))
        mapper = ThinkingAloudMapper(settings=settings)

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent,
            thinking_mapper=mapper, settings=settings,
        )

        session = _session(settings)
        json_messages = []

        # Interrupt after first message
        original_send = AsyncMock()

        async def send_json_and_interrupt(data):
            json_messages.append(data)
            if data.get("type") == "status":
                session.interrupt()

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=send_json_and_interrupt,
            send_bytes=AsyncMock(),
        )

        # Should NOT have agent_done (interrupted before completion)
        types = [m["type"] for m in json_messages]
        assert "agent_done" not in types


async def _append(lst: list, item):
    lst.append(item)
