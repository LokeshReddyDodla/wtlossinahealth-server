"""
Speech-to-Text — OpenAI Whisper integration.

Uses the OpenAI SDK directly (not LiteLLM) because LiteLLM does not
support audio APIs. The OPENAI_API_KEY env var is read automatically.
"""

from __future__ import annotations

import io
import logging

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
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.webm"

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
