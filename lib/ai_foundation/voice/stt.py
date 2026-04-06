"""
Speech-to-Text — OpenAI Whisper integration.

Uses the OpenAI SDK directly (not LiteLLM) because LiteLLM does not
support audio APIs. The OPENAI_API_KEY env var is read automatically.

Audio input: raw PCM 16-bit 16kHz mono from Flutter client (startStream).
Wrapped in a WAV header before sending to Whisper.
"""

from __future__ import annotations

import io
import logging
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
        """Transcribe raw PCM audio bytes using Whisper.

        Args:
            audio_bytes: Raw PCM 16-bit 16kHz mono from the Flutter client.
            language: ISO 639-1 language code override, or None for auto-detect.

        Returns:
            TranscriptionResult with text, detected language, and duration.
        """
        wav_bytes = _pcm_to_wav(
            audio_bytes,
            sample_rate=self._settings.INPUT_SAMPLE_RATE,
            channels=self._settings.INPUT_CHANNELS,
        )
        audio_file = io.BytesIO(wav_bytes)
        audio_file.name = "audio.wav"

        kwargs: dict = {
            "model": self._settings.STT_MODEL,
            "file": audio_file,
            "response_format": "verbose_json",
        }
        lang = language or self._settings.STT_LANGUAGE
        if lang:
            kwargs["language"] = lang

        logger.debug("STT: transcribing %d bytes PCM → %d bytes WAV (lang=%s)", len(audio_bytes), len(wav_bytes), lang)

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
