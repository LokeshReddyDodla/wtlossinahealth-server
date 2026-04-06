"""
Voice Agent Configuration — all tunables for the voice pipeline.

Usage:
    from lib.ai_foundation.voice.config import voice_settings
    voice_settings.STT_MODEL        # → "whisper-1"
    voice_settings.TTS_VOICE        # → "nova"

To override: set environment variables with AI_VOICE_ prefix:
    AI_VOICE_TTS_MODEL=tts-1-hd
    AI_VOICE_TTS_VOICE=alloy
    AI_VOICE_SESSION_TIMEOUT_SECONDS=600
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class VoiceSettings(BaseSettings):
    """All voice agent configuration in one place."""

    model_config = {"env_prefix": "AI_VOICE_", "case_sensitive": False}

    # ── Speech-to-Text ───────────────────────────────────────────────────

    STT_MODEL: str = Field(default="whisper-1", description="OpenAI Whisper model")
    STT_LANGUAGE: str = Field(default="en", description="Default STT language (ISO 639-1)")
    STT_MAX_AUDIO_SECONDS: int = Field(default=30, description="Max audio duration per utterance")

    # ── Text-to-Speech ───────────────────────────────────────────────────

    TTS_MODEL: str = Field(default="tts-1", description="OpenAI TTS model (tts-1 for speed, tts-1-hd for quality)")
    TTS_VOICE: str = Field(default="nova", description="TTS voice: alloy, echo, fable, onyx, nova, shimmer")
    TTS_SPEED: float = Field(default=1.0, description="TTS playback speed (0.25-4.0)")
    TTS_RESPONSE_FORMAT: str = Field(default="opus", description="TTS audio format: opus, mp3, aac, flac, wav, pcm")

    # ── Session ──────────────────────────────────────────────────────────

    SESSION_TIMEOUT_SECONDS: int = Field(default=300, description="Idle timeout before session auto-closes")
    MAX_CONCURRENT_SESSIONS: int = Field(default=100, description="Max simultaneous voice sessions")
    AUDIO_BUFFER_MAX_BYTES: int = Field(default=5_000_000, description="Max audio buffer per utterance (~5MB)")

    # ── Thinking Aloud ───────────────────────────────────────────────────

    THINKING_ALOUD_ENABLED: bool = Field(default=True, description="Speak filler phrases while agent reasons")
    THINKING_COOLDOWN_SECONDS: float = Field(default=2.5, description="Min seconds between filler phrases")
    THINKING_MAX_FILLERS_PER_TURN: int = Field(default=3, description="Max filler phrases per agent turn")

    # ── Audio Format ─────────────────────────────────────────────────────

    INPUT_SAMPLE_RATE: int = Field(default=16_000, description="Expected input audio sample rate (Hz)")
    INPUT_CHANNELS: int = Field(default=1, description="Expected input audio channels (mono)")
    OUTPUT_SAMPLE_RATE: int = Field(default=24_000, description="Output audio sample rate (Hz)")

    # ── Silence Detection (server-side fallback) ─────────────────────────

    SILENCE_THRESHOLD_MS: int = Field(default=1500, description="Silence duration to auto-trigger STT (ms)")


# Singleton — import this everywhere
voice_settings = VoiceSettings()
