"""
Text-to-Speech — OpenAI TTS integration with streaming support.

Uses the OpenAI SDK directly (not LiteLLM) because LiteLLM does not
support audio APIs. The OPENAI_API_KEY env var is read automatically.

Two modes:
    synthesize_stream() — yields audio chunks as they arrive (for responses)
    synthesize()        — returns full audio bytes (for short filler phrases)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from lib.ai_foundation.voice.config import VoiceSettings

logger = logging.getLogger(__name__)

# Chunk size for streaming TTS audio (4KB)
_STREAM_CHUNK_SIZE = 4096


class TextToSpeech:
    """Async OpenAI TTS client with streaming support."""

    def __init__(self, settings: VoiceSettings) -> None:
        self._client = AsyncOpenAI()
        self._settings = settings
        self._filler_cache: dict[str, bytes] = {}

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream TTS audio chunks as they arrive from OpenAI.

        Yields audio bytes in chunks suitable for real-time playback.
        Uses with_streaming_response for minimum time-to-first-byte.
        """
        if not text.strip():
            return

        logger.debug("TTS stream: synthesizing %d chars", len(text))

        async with self._client.audio.speech.with_streaming_response.create(
            model=self._settings.TTS_MODEL,
            voice=self._settings.TTS_VOICE,
            input=text,
            speed=self._settings.TTS_SPEED,
            response_format=self._settings.TTS_RESPONSE_FORMAT,
        ) as response:
            async for chunk in response.iter_bytes(chunk_size=_STREAM_CHUNK_SIZE):
                yield chunk

    async def synthesize(self, text: str) -> bytes:
        """Synthesize full audio for short phrases (filler/thinking aloud).

        Results are cached in memory for common filler phrases.
        """
        if not text.strip():
            return b""

        cached = self._filler_cache.get(text)
        if cached is not None:
            return cached

        logger.debug("TTS: synthesizing %d chars", len(text))

        response = await self._client.audio.speech.create(
            model=self._settings.TTS_MODEL,
            voice=self._settings.TTS_VOICE,
            input=text,
            speed=self._settings.TTS_SPEED,
            response_format=self._settings.TTS_RESPONSE_FORMAT,
        )
        audio = response.content

        # Cache short phrases (filler) to avoid re-synthesizing
        if len(text) <= 80:
            self._filler_cache[text] = audio

        return audio

    async def precache_phrases(self, phrases: list[str]) -> None:
        """Pre-synthesize common filler phrases at startup for instant playback."""
        for phrase in phrases:
            if phrase not in self._filler_cache:
                try:
                    await self.synthesize(phrase)
                except Exception:
                    logger.warning("TTS precache failed for: %s", phrase, exc_info=True)
