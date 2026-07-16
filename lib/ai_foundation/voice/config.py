"""
Voice Agent Configuration — all tunables for the voice pipeline.

Usage:
    from lib.ai_foundation.voice.config import voice_settings
    voice_settings.STT_PROVIDER     # → "openai"
    voice_settings.TTS_PROVIDER     # → "openai"

Switch providers via environment variables:
    AI_VOICE_STT_PROVIDER=sarvam
    AI_VOICE_TTS_PROVIDER=sarvam
    AI_VOICE_SARVAM_API_KEY=your-key
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class VoiceSettings(BaseSettings):
    """All voice agent configuration in one place."""

    model_config = {"env_prefix": "AI_VOICE_", "case_sensitive": False}

    # ── Provider Selection ───────────────────────────────────────────────

    STT_PROVIDER: str = Field(default="openai", description="STT provider: openai or sarvam")
    TTS_PROVIDER: str = Field(default="openai", description="TTS provider: openai or sarvam")
    PROVIDER_TIMEOUT_SECONDS: float = Field(default=30.0, description="Per-call STT/TTS provider timeout — a hung call must not stall a live voice turn for the library-default 10 minutes")

    # ── OpenAI Speech-to-Text ────────────────────────────────────────────

    STT_MODEL: str = Field(default="whisper-1", description="OpenAI Whisper model")
    STT_LANGUAGE: str = Field(default="", description="Default STT language (ISO 639-1). Empty = auto-detect.")
    STT_MAX_AUDIO_SECONDS: int = Field(default=30, description="Max audio duration per utterance")

    # ── OpenAI Text-to-Speech ────────────────────────────────────────────

    TTS_MODEL: str = Field(default="tts-1-hd", description="OpenAI TTS model (tts-1 for speed, tts-1-hd for quality)")
    TTS_VOICE: str = Field(default="nova", description="TTS voice: alloy, echo, fable, onyx, nova, shimmer")
    TTS_SPEED: float = Field(default=1.0, description="TTS playback speed (0.25-4.0)")
    TTS_RESPONSE_FORMAT: str = Field(default="opus", description="TTS audio format: opus, mp3, aac, flac, wav, pcm")
    TTS_STREAM_CHUNK_SIZE: int = Field(default=4096, description="Chunk size for streaming TTS audio (bytes)")
    TTS_FILLER_CACHE_MAX_SIZE: int = Field(default=256, description="Max cached filler phrases (LRU eviction)")

    # ── Sarvam AI ────────────────────────────────────────────────────────

    SARVAM_API_KEY: str = Field(default="", description="Sarvam AI API subscription key")
    SARVAM_STT_MODEL: str = Field(default="saaras:v3", description="Sarvam STT model: saarika:v2.5, saaras:v3")
    SARVAM_TTS_MODEL: str = Field(default="bulbul:v3", description="Sarvam TTS model: bulbul:v2, bulbul:v3")
    SARVAM_TTS_SPEAKER: str = Field(default="shubh", description="Sarvam TTS voice (43 available)")
    SARVAM_TTS_LANGUAGE: str = Field(default="en-IN", description="Sarvam TTS target language code (e.g. hi-IN, en-IN)")

    # ── Session ──────────────────────────────────────────────────────────

    SESSION_TIMEOUT_SECONDS: int = Field(default=300, description="Idle timeout before session auto-closes")
    MAX_CONCURRENT_SESSIONS: int = Field(default=100, description="Max simultaneous voice sessions")
    AUDIO_BUFFER_MAX_BYTES: int = Field(default=5_000_000, description="Max audio buffer per utterance (~5MB)")

    # ── Audio Format ─────────────────────────────────────────────────────

    INPUT_SAMPLE_RATE: int = Field(default=16_000, description="Expected input audio sample rate (Hz)")
    INPUT_CHANNELS: int = Field(default=1, description="Expected input audio channels (mono)")
    OUTPUT_SAMPLE_RATE: int = Field(default=24_000, description="Output audio sample rate (Hz)")

    # ── Silence Detection (server-side fallback) ─────────────────────────

    SILENCE_THRESHOLD_MS: int = Field(default=1500, description="Silence duration to auto-trigger STT (ms)")


# Singleton — import this everywhere
voice_settings = VoiceSettings()
