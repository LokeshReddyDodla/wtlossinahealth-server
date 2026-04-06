"""Tests for VoiceSession state machine."""

from __future__ import annotations

from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.session import VoiceSession, VoiceSessionState


def _make_session(**overrides) -> VoiceSession:
    defaults = {
        "SESSION_TIMEOUT_SECONDS": 60,
        "AUDIO_BUFFER_MAX_BYTES": 1000,
    }
    defaults.update(overrides)
    settings = VoiceSettings(**defaults)
    return VoiceSession(
        user_id="user_1",
        patient_id="patient_1",
        thread_id="bot:patient:patient_1",
        settings=settings,
    )


class TestVoiceSession:
    def test_initial_state_is_idle(self):
        session = _make_session()
        assert session.state == VoiceSessionState.IDLE

    def test_session_id_format(self):
        session = _make_session()
        assert session.session_id.startswith("vs_")
        assert len(session.session_id) == 19  # vs_ + 16 hex chars

    def test_append_audio_transitions_to_listening(self):
        session = _make_session()
        assert session.append_audio(b"\x00" * 100)
        assert session.state == VoiceSessionState.LISTENING

    def test_append_audio_accumulates(self):
        session = _make_session()
        session.append_audio(b"\x00" * 50)
        session.append_audio(b"\x01" * 50)
        assert session.audio_buffer_size == 100

    def test_append_audio_rejects_overflow(self):
        session = _make_session(AUDIO_BUFFER_MAX_BYTES=100)
        assert session.append_audio(b"\x00" * 80)
        assert not session.append_audio(b"\x00" * 30)  # Would exceed 100

    def test_get_audio_and_reset(self):
        session = _make_session()
        session.append_audio(b"\x00" * 50)
        audio = session.get_audio_and_reset()
        assert len(audio) == 50
        assert session.audio_buffer_size == 0

    def test_has_audio(self):
        session = _make_session()
        assert not session.has_audio
        session.append_audio(b"\x00")
        assert session.has_audio

    def test_interrupt_sets_cancelled(self):
        session = _make_session()
        session.state = VoiceSessionState.SPEAKING
        session.interrupt()
        assert session.is_cancelled
        assert session.state == VoiceSessionState.INTERRUPTED
        assert session.audio_buffer_size == 0

    def test_clear_interrupt_resets(self):
        session = _make_session()
        session.interrupt()
        session.clear_interrupt()
        assert not session.is_cancelled
        assert session.state == VoiceSessionState.IDLE

    def test_is_expired(self):
        session = _make_session(SESSION_TIMEOUT_SECONDS=0)
        assert session.is_expired  # 0 second timeout = always expired

    def test_not_expired(self):
        session = _make_session(SESSION_TIMEOUT_SECONDS=9999)
        assert not session.is_expired

    def test_touch_updates_last_activity(self):
        session = _make_session()
        old_time = session.last_activity
        session.touch()
        assert session.last_activity >= old_time
