"""
Speech-to-Text — OpenAI Whisper integration.

Uses the OpenAI SDK directly (not LiteLLM) because LiteLLM does not
support audio APIs. The OPENAI_API_KEY env var is read automatically.

Supports two input shapes:
  - Raw PCM 16-bit 16kHz mono (the WS voice agent's streaming format).
    Wrapped in a WAV container before upload.
  - Encoded container formats (m4a, mp3, mp4, mpeg, mpga, webm, ogg,
    flac, wav). Passed through to Whisper as-is — used by the meal
    voice preview endpoint where Flutter uploads a recorded file.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel

from lib.ai_foundation.voice.config import VoiceSettings

logger = logging.getLogger(__name__)


AudioFormat = Literal["pcm", "wav", "mp3", "mp4", "mpeg", "mpga", "m4a", "webm", "ogg", "flac"]


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

    async def transcribe_file(
        self,
        audio_bytes: bytes,
        *,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an already-encoded audio file (webm/m4a/mp3/wav/ogg).

        Use this for browser-recorded uploads (MediaRecorder produces webm
        on Chrome, m4a on Safari). Whisper auto-detects the container, so
        we forward the bytes as-is — no WAV wrapping like the PCM path.
        """
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename  # Whisper sniffs format from extension

        kwargs: dict = {
            "model": self._settings.STT_MODEL,
            "file": audio_file,
            "response_format": "verbose_json",
        }
        lang = language or self._settings.STT_LANGUAGE
        if lang:
            kwargs["language"] = lang

        logger.debug(
            "STT (file): transcribing %d bytes from %s (lang=%s)",
            len(audio_bytes),
            filename,
            lang,
        )

        response = await self._client.audio.transcriptions.create(**kwargs)

        result = TranscriptionResult(
            text=response.text,
            language=getattr(response, "language", lang),
            duration_seconds=getattr(response, "duration", None),
        )

        logger.info(
            "STT (file): transcribed %s (%d bytes) → %d chars (lang=%s, dur=%.1fs)",
            filename,
            len(audio_bytes),
            len(result.text),
            result.language,
            result.duration_seconds or 0,
        )
        return result

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        audio_format: AudioFormat = "pcm",
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Whisper.

        Args:
            audio_bytes: Audio payload. For ``audio_format="pcm"`` this must be
                raw 16-bit mono PCM at the configured ``INPUT_SAMPLE_RATE``;
                it will be wrapped in a WAV container before upload. For any
                other format the bytes are sent to Whisper unchanged.
            audio_format: Container/codec of ``audio_bytes``.
            language: ISO 639-1 language code override, or None for auto-detect.

        Returns:
            TranscriptionResult with text, detected language, and duration.
        """
        if audio_format == "pcm":
            upload_bytes = _pcm_to_wav(
                audio_bytes,
                sample_rate=self._settings.INPUT_SAMPLE_RATE,
                channels=self._settings.INPUT_CHANNELS,
            )
            filename = "audio.wav"
        else:
            upload_bytes = audio_bytes
            filename = f"audio.{audio_format}"

        audio_file = io.BytesIO(upload_bytes)
        audio_file.name = filename

        kwargs: dict = {
            "model": self._settings.STT_MODEL,
            "file": audio_file,
            "response_format": "verbose_json",
        }
        lang = language or self._settings.STT_LANGUAGE
        if lang:
            kwargs["language"] = lang

        logger.debug(
            "STT: transcribing %d bytes (in=%s → upload=%s, %d bytes, lang=%s)",
            len(audio_bytes),
            audio_format,
            filename,
            len(upload_bytes),
            lang or "auto",
        )

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


def _pcm_to_wav(
    pcm_data: bytes,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM 16-bit bytes in a valid WAV container for Whisper."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()
