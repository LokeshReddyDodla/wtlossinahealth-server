"""
Speech-to-Text — OpenAI Whisper integration.

Uses the OpenAI SDK directly (not LiteLLM) because LiteLLM does not
support audio APIs. The OPENAI_API_KEY env var is read automatically.
"""

from __future__ import annotations

import io
import logging
import struct
import wave

from openai import AsyncOpenAI
from pydantic import BaseModel

from lib.ai_foundation.voice.config import VoiceSettings

logger = logging.getLogger(__name__)


class TranscriptionResult(BaseModel):
    """Result from a speech-to-text transcription."""

    text: str
    language: str | None = None
    duration_seconds: float | None = None


class SpeechToText:
    """Async OpenAI Whisper STT client."""

    def __init__(self, settings: VoiceSettings) -> None:
        self._client = AsyncOpenAI()
        self._settings = settings

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Whisper.

        Args:
            audio_bytes: Raw audio data (any format Whisper accepts).
            language: ISO 639-1 language code override, or None for auto-detect.

        Returns:
            TranscriptionResult with text, detected language, and duration.
        """
        filename = _detect_filename(audio_bytes)
        # Raw PCM has no header — wrap in WAV so Whisper can decode it
        if filename == "audio.wav" and not audio_bytes[:4] == b"RIFF":
            audio_bytes = _pcm_to_wav(
                audio_bytes,
                sample_rate=self._settings.INPUT_SAMPLE_RATE,
                channels=self._settings.INPUT_CHANNELS,
            )
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        kwargs: dict = {
            "model": self._settings.STT_MODEL,
            "file": audio_file,
            "response_format": "verbose_json",
        }
        lang = language or self._settings.STT_LANGUAGE
        if lang:
            kwargs["language"] = lang

        logger.debug("STT: transcribing %d bytes (lang=%s)", len(audio_bytes), lang)

        response = await self._client.audio.transcriptions.create(**kwargs)

        result = TranscriptionResult(
            text=response.text,
            language=getattr(response, "language", lang),
            duration_seconds=getattr(response, "duration", None),
        )

        logger.info(
            "STT: transcribed %d bytes → %d chars (lang=%s, dur=%.1fs)",
            len(audio_bytes),
            len(result.text),
            result.language,
            result.duration_seconds or 0,
        )
        return result


def _detect_filename(data: bytes) -> str:
    """Detect audio format from magic bytes and return a filename hint for Whisper."""
    if data[:4] == b"RIFF":
        return "audio.wav"
    if data[:4] == b"fLaC":
        return "audio.flac"
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3":
        return "audio.mp3"
    if data[:4] == b"OggS":
        return "audio.ogg"
    if data[:4] == b"\x1aE\xdf\xa3":  # EBML header (WebM/Matroska)
        return "audio.webm"
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "audio.m4a"
    # Default to wav — raw PCM will be wrapped with a WAV header
    return "audio.wav"


def _pcm_to_wav(
    pcm_data: bytes,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM bytes in a valid WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()
