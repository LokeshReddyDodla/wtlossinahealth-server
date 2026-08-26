"""Tests for VoiceOrchestrator — integration test with mocked STT/TTS/Agent."""

from __future__ import annotations

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

    mock_tts.synthesize_stream = MagicMock(side_effect=lambda t, language=None: fake_stream(t))
    mock_tts.supports_language = MagicMock(return_value=True)
    return mock_tts


class TestVoiceOrchestrator:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_audio_boundaries(self):
        """Verify audio_start/audio_end wrap every spoken segment."""
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="How is my glucose today?", language="en", duration_seconds=2.0,
        )

        mock_tts = _make_tts()
        mock_agent = AsyncMock()
        save_response_audio = AsyncMock(return_value="https://assets.example/response.ogg")

        async def fake_run_stream(agent_input):
            yield _sse_event("status", {"stage": "extracting_intent"})
            yield _sse_event("reasoning", {"step": 1, "thought": "Let me check glucose data"})
            yield _sse_event("tool_call", {"tool": "look_up", "args": {"data_types": ["cgm_range_stats"]}})
            yield _sse_event("tool_result", {"tool": "look_up", "summary": "Found 7 days of data"})
            yield _sse_event("token", {"delta": "Your glucose is fine."})
            yield _sse_event("done", {
                "suggestions": [{"label": "More"}],
                "trace_id": "trc_1",
                "data": {"full_response": "Your glucose is fine."},
            })

        mock_agent.run_stream = MagicMock(side_effect=lambda i: fake_run_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), settings=settings,
            save_response_audio=save_response_audio,
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

        # Semantic events forwarded
        assert "transcript" in types
        assert "reasoning" in types
        assert "response_text" in types
        assert "response_audio" in types
        assert "done" in types

        # Audio boundaries present
        assert "audio_start" in types
        assert "audio_end" in types

        # Every audio_start has a matching audio_end
        starts = [m for m in json_messages if m["type"] == "audio_start"]
        ends = [m for m in json_messages if m["type"] == "audio_end"]
        assert len(starts) == len(ends)
        for s, e in zip(starts, ends):
            assert s["segment_id"] == e["segment_id"]
            assert s["segment_type"] == e["segment_type"]
            assert e["completed"] is True

        # done is the last event
        assert types[-1] == "done"

        # done comes after the last audio_end
        last_audio_end_idx = max(i for i, m in enumerate(json_messages) if m["type"] == "audio_end")
        done_idx = next(i for i, m in enumerate(json_messages) if m["type"] == "done")
        assert done_idx > last_audio_end_idx

        # Binary audio was sent
        assert len(binary_messages) > 0

        # Segment types are correct
        segment_types = [m["segment_type"] for m in starts]
        assert "reasoning" in segment_types
        assert "response_text" in segment_types
        save_response_audio.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_orphan_binary(self):
        """Binary only appears between audio_start and audio_end."""
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="Check my glucose", language="en", duration_seconds=1.5,
        )

        mock_tts = _make_tts()
        mock_agent = AsyncMock()

        async def fake_run_stream(agent_input):
            yield _sse_event("reasoning", {"step": 1, "thought": "Checking glucose"})
            yield _sse_event("done", {"data": {"full_response": "Looks good."}})

        mock_agent.run_stream = MagicMock(side_effect=lambda i: fake_run_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), settings=settings,
        )

        session = _session(settings)
        all_messages = []  # Track order of JSON and binary

        async def track_json(d):
            all_messages.append(("json", d))

        async def track_bytes(b):
            all_messages.append(("binary", len(b)))

        await orchestrator.handle_utterance(
            session, b"\x00" * 500,
            send_json=track_json,
            send_bytes=track_bytes,
        )

        # Verify binary only appears between audio_start and audio_end
        in_segment = False
        for kind, data in all_messages:
            if kind == "json" and isinstance(data, dict):
                if data.get("type") == "audio_start":
                    in_segment = True
                elif data.get("type") == "audio_end":
                    in_segment = False
            elif kind == "binary":
                assert in_segment, "Binary frame outside audio_start/audio_end!"

    @pytest.mark.asyncio
    async def test_thoughts_spoken_sequentially(self):
        """Each thought finishes before the next starts — one segment at a time."""
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

        mock_tts.synthesize_stream = MagicMock(side_effect=lambda t, language=None: fake_stream(t))
        mock_agent = AsyncMock()

        async def fake_run_stream(agent_input):
            yield _sse_event("reasoning", {"step": 1, "thought": "First thought"})
            yield _sse_event("reasoning", {"step": 2, "thought": "Second thought"})
            yield _sse_event("done", {"data": {"full_response": "Final answer."}})

        mock_agent.run_stream = MagicMock(side_effect=lambda i: fake_run_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), settings=settings,
        )

        session = _session(settings)
        json_messages = []

        await orchestrator.handle_utterance(
            session, b"\x00" * 500,
            send_json=lambda d: _async_append(json_messages, d),
            send_bytes=AsyncMock(),
        )

        # All three spoken in order
        assert len(speak_order) == 3
        assert "First thought" in speak_order[0]
        assert "Second thought" in speak_order[1]
        assert "Final answer" in speak_order[2]

        # Verify no overlapping segments
        starts = [m for m in json_messages if m["type"] == "audio_start"]
        ends = [m for m in json_messages if m["type"] == "audio_end"]
        assert len(starts) == 3
        assert len(ends) == 3

    @pytest.mark.asyncio
    async def test_interrupt_closes_segment(self):
        """Interrupted segment gets audio_end with completed=false."""
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="Tell me about my glucose", language="en", duration_seconds=2.0,
        )

        mock_tts = _make_tts()
        mock_agent = AsyncMock()

        async def fake_stream(agent_input):
            yield _sse_event("reasoning", {"step": 1, "thought": "Checking glucose data"})
            yield _sse_event("done", {"data": {"full_response": "Your glucose..."}})

        mock_agent.run_stream = MagicMock(side_effect=lambda i: fake_stream(i))

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), settings=settings,
        )

        session = _session(settings)
        json_messages = []

        async def send_json_and_interrupt(data):
            json_messages.append(data)
            # Interrupt when audio_start for reasoning arrives
            if isinstance(data, dict) and data.get("type") == "audio_start" and data.get("segment_type") == "reasoning":
                session.interrupt()

        await orchestrator.handle_utterance(
            session, b"\x00" * 100,
            send_json=send_json_and_interrupt,
            send_bytes=AsyncMock(),
        )

        # The reasoning segment should have audio_end with completed=false
        ends = [m for m in json_messages if m.get("type") == "audio_end"]
        assert len(ends) >= 1
        reasoning_end = next((e for e in ends if e["segment_type"] == "reasoning"), None)
        assert reasoning_end is not None
        assert reasoning_end["completed"] is False
        assert reasoning_end["reason"] == "interrupted"

        # done should NOT be present (interrupted before response)
        types = [m.get("type") for m in json_messages]
        assert "done" not in types

    @pytest.mark.asyncio
    async def test_empty_transcript_sends_error(self):
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="   ", language="en", duration_seconds=0.5,
        )

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=AsyncMock(), agent=AsyncMock(), patient_resolver=AsyncMock(), settings=settings,
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
        assert "audio_start" not in types  # No audio for errors without agent

    @pytest.mark.asyncio
    async def test_stt_failure_sends_error(self):
        settings = _settings()

        mock_stt = AsyncMock()
        mock_stt.transcribe.side_effect = RuntimeError("API error")

        orchestrator = VoiceOrchestrator(
            stt=mock_stt, tts=AsyncMock(), agent=AsyncMock(), patient_resolver=AsyncMock(), settings=settings,
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
            stt=mock_stt, tts=mock_tts, agent=mock_agent, patient_resolver=AsyncMock(), settings=settings,
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
