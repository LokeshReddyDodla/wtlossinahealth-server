"""
Text-to-Speech — provider-agnostic interface with OpenAI and Sarvam backends.

Provider selection is driven by config (AI_VOICE_TTS_PROVIDER). Both providers
share the same async iterator contract so callers never know which ran.

    tts = build_tts(settings)  # returns the configured provider
    async for chunk in tts.synthesize_stream(text):
        send(chunk)
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import AsyncIterator

from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.providers import (
    AudioProvider,
    SARVAM_OUTPUT_CODECS,
    SARVAM_TTS_LANGUAGE_MAP,
)

logger = logging.getLogger(__name__)

# Short phrases (fillers like "Let me check that...") are cached to skip the API.
_FILLER_MAX_CHARS = 80


class BaseTextToSpeech(ABC):
    """Provider-agnostic TTS interface with a shared filler-phrase cache."""

    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._filler_cache: OrderedDict[str, bytes] = OrderedDict()

    @abstractmethod
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]: ...

    @abstractmethod
    async def _synthesize_full(self, text: str) -> bytes:
        """One-shot synthesis of the full text — provider-specific."""

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            return b""

        cached = self._filler_cache.get(text)
        if cached is not None:
            return cached

        logger.debug("TTS [%s]: synthesizing %d chars", type(self).__name__, len(text))
        audio = await self._synthesize_full(text)

        if len(text) <= _FILLER_MAX_CHARS:
            self._filler_cache[text] = audio
            while len(self._filler_cache) > self._settings.TTS_FILLER_CACHE_MAX_SIZE:
                self._filler_cache.popitem(last=False)

        return audio

    async def precache_phrases(self, phrases: list[str]) -> None:
        for phrase in phrases:
            try:
                await self.synthesize(phrase)
            except Exception:
                logger.warning("TTS precache failed for: %s", phrase, exc_info=True)


# ── OpenAI TTS ──────────────────────────────────────────────────────────────


class OpenAITextToSpeech(BaseTextToSpeech):
    """Async OpenAI TTS client with streaming support."""

    def __init__(self, settings: VoiceSettings) -> None:
        from openai import AsyncOpenAI
        super().__init__(settings)
        self._client = AsyncOpenAI()

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        if not text.strip():
            return

        logger.debug("TTS [openai] stream: synthesizing %d chars", len(text))

        async with self._client.audio.speech.with_streaming_response.create(
            model=self._settings.TTS_MODEL,
            voice=self._settings.TTS_VOICE,
            input=text,
            speed=self._settings.TTS_SPEED,
            response_format=self._settings.TTS_RESPONSE_FORMAT,
        ) as response:
            async for chunk in response.iter_bytes(chunk_size=self._settings.TTS_STREAM_CHUNK_SIZE):
                yield chunk

    async def _synthesize_full(self, text: str) -> bytes:
        response = await self._client.audio.speech.create(
            model=self._settings.TTS_MODEL,
            voice=self._settings.TTS_VOICE,
            input=text,
            speed=self._settings.TTS_SPEED,
            response_format=self._settings.TTS_RESPONSE_FORMAT,
        )
        return response.content


# ── Sarvam AI TTS ───────────────────────────────────────────────────────────


class SarvamTextToSpeech(BaseTextToSpeech):
    """Async Sarvam AI TTS client with streaming support."""

    def __init__(self, settings: VoiceSettings) -> None:
        from sarvamai import AsyncSarvamAI
        super().__init__(settings)
        self._client = AsyncSarvamAI(api_subscription_key=settings.SARVAM_API_KEY)

    def _resolve_language(self) -> str:
        lang = self._settings.SARVAM_TTS_LANGUAGE
        if lang and lang in SARVAM_TTS_LANGUAGE_MAP.values():
            return lang
        return SARVAM_TTS_LANGUAGE_MAP.get(lang or "en", "en-IN")

    def _resolve_codec(self) -> str:
        return SARVAM_OUTPUT_CODECS.get(self._settings.TTS_RESPONSE_FORMAT, "mp3")

    async def _synthesize_full(self, text: str) -> bytes:
        """Call Sarvam TTS REST API and return decoded audio bytes."""
        response = await self._client.text_to_speech.convert(
            text=text,
            target_language_code=self._resolve_language(),
            model=self._settings.SARVAM_TTS_MODEL,
            speaker=self._settings.SARVAM_TTS_SPEAKER,
            pace=self._settings.TTS_SPEED,
            speech_sample_rate=self._settings.OUTPUT_SAMPLE_RATE,
            output_audio_codec=self._resolve_codec(),
        )
        return base64.b64decode(response.audios[0])

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        if not text.strip():
            return

        logger.debug("TTS [sarvam] stream: synthesizing %d chars", len(text))

        chunk_size = self._settings.TTS_STREAM_CHUNK_SIZE
        for segment in _split_text(text, max_chars=2400):
            audio = await self._synthesize_full(segment)
            for i in range(0, len(audio), chunk_size):
                yield audio[i:i + chunk_size]


# ── Factory ─────────────────────────────────────────────────────────────────


def build_tts(settings: VoiceSettings) -> BaseTextToSpeech:
    """Build the TTS client based on the configured provider."""
    provider = AudioProvider(settings.TTS_PROVIDER)
    if provider == AudioProvider.SARVAM:
        try:
            return SarvamTextToSpeech(settings)
        except ImportError:
            logger.warning("TTS provider set to sarvam but sarvamai not installed, falling back to openai")
    return OpenAITextToSpeech(settings)


# ── Utilities ───────────────────────────────────────────────────────────────


def _split_text(text: str, max_chars: int = 2400) -> list[str]:
    """Split text into segments at sentence boundaries, respecting max_chars."""
    if len(text) <= max_chars:
        return [text]

    segments: list[str] = []
    current = ""
    for sentence in text.replace(". ", ".|").replace("? ", "?|").replace("! ", "!|").split("|"):
        if len(current) + len(sentence) + 1 > max_chars and current:
            segments.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current.strip():
        segments.append(current.strip())
    return segments
