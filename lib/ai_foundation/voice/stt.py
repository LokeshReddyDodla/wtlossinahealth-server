"""
Speech-to-Text — provider-agnostic interface with OpenAI and Sarvam backends.

Provider selection is driven by config (AI_VOICE_STT_PROVIDER). Both providers
share the same TranscriptionResult contract so callers never know which ran.

    stt = build_stt(settings)  # returns the configured provider
    result = await stt.transcribe(audio_bytes)
"""

from __future__ import annotations

import io
import logging
import wave
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.providers import (
    AudioProvider,
    SARVAM_INPUT_CODECS,
    SARVAM_STT_LANGUAGE_MAP,
)

logger = logging.getLogger(__name__)


AudioFormat = Literal["pcm", "wav", "mp3", "mp4", "mpeg", "mpga", "m4a", "webm", "ogg", "flac"]


class TranscriptionResult(BaseModel):
    """Result from a speech-to-text transcription."""

    text: str
    language: str | None = None
    duration_seconds: float | None = None


class BaseSpeechToText(ABC):
    """Provider-agnostic STT interface."""

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        audio_format: AudioFormat = "pcm",
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult: ...


# ── OpenAI Whisper ──────────────────────────────────────────────────────────


class OpenAISpeechToText(BaseSpeechToText):
    """Async OpenAI Whisper STT client."""

    def __init__(self, settings: VoiceSettings) -> None:
        from openai import AsyncOpenAI
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
        prompt: str | None = None,
    ) -> TranscriptionResult:
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
        if prompt:
            kwargs["prompt"] = prompt

        logger.debug(
            "STT [openai]: transcribing %d bytes (in=%s → upload=%s, %d bytes, lang=%s)",
            len(audio_bytes), audio_format, filename, len(upload_bytes), lang or "auto",
        )

        response = await self._client.audio.transcriptions.create(**kwargs)

        result = TranscriptionResult(
            text=response.text,
            language=getattr(response, "language", lang),
            duration_seconds=getattr(response, "duration", None),
        )

        logger.info(
            "STT [openai]: %d bytes → %d chars (lang=%s, dur=%.1fs)",
            len(audio_bytes), len(result.text), result.language, result.duration_seconds or 0,
        )
        return result


# ── Sarvam AI ───────────────────────────────────────────────────────────────


class SarvamSpeechToText(BaseSpeechToText):
    """Async Sarvam AI STT client."""

    def __init__(self, settings: VoiceSettings) -> None:
        from sarvamai import AsyncSarvamAI
        self._client = AsyncSarvamAI(api_subscription_key=settings.SARVAM_API_KEY)
        self._settings = settings

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        audio_format: AudioFormat = "pcm",
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        if audio_format == "pcm":
            upload_bytes = _pcm_to_wav(
                audio_bytes,
                sample_rate=self._settings.INPUT_SAMPLE_RATE,
                channels=self._settings.INPUT_CHANNELS,
            )
        else:
            upload_bytes = audio_bytes

        lang = language or self._settings.STT_LANGUAGE
        sarvam_lang = SARVAM_STT_LANGUAGE_MAP.get(lang, "unknown") if lang else "unknown"
        sarvam_codec = SARVAM_INPUT_CODECS.get(audio_format, "wav")

        logger.debug(
            "STT [sarvam]: transcribing %d bytes (format=%s, lang=%s)",
            len(audio_bytes), audio_format, sarvam_lang,
        )

        response = await self._client.speech_to_text.transcribe(
            file=io.BytesIO(upload_bytes),
            model=self._settings.SARVAM_STT_MODEL,
            language_code=sarvam_lang,
            input_audio_codec=sarvam_codec,
        )

        detected_lang = getattr(response, "language_code", sarvam_lang)
        if detected_lang and "-" in detected_lang:
            detected_lang = detected_lang.split("-")[0]

        result = TranscriptionResult(
            text=response.transcript,
            language=detected_lang,
            duration_seconds=None,
        )

        logger.info(
            "STT [sarvam]: %d bytes → %d chars (lang=%s)",
            len(audio_bytes), len(result.text), result.language,
        )
        return result


# ── Factory ─────────────────────────────────────────────────────────────────


def build_stt(settings: VoiceSettings) -> BaseSpeechToText:
    """Build the STT client based on the configured provider."""
    provider = AudioProvider(settings.STT_PROVIDER)
    if provider == AudioProvider.SARVAM:
        try:
            return SarvamSpeechToText(settings)
        except ImportError:
            logger.warning("STT provider set to sarvam but sarvamai not installed, falling back to openai")
    return OpenAISpeechToText(settings)


# ── Utilities ───────────────────────────────────────────────────────────────


def _pcm_to_wav(
    pcm_data: bytes,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM 16-bit bytes in a valid WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()
