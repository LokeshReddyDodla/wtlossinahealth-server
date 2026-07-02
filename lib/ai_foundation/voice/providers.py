"""
Voice provider identifiers.

Switching providers is a config change — no code changes required:
    AI_VOICE_STT_PROVIDER=sarvam
    AI_VOICE_TTS_PROVIDER=sarvam

Provider selection happens in stt.build_stt / tts.build_tts.
"""

from __future__ import annotations

from enum import Enum


class AudioProvider(str, Enum):
    """Supported audio providers for STT and TTS."""

    OPENAI = "openai"
    SARVAM = "sarvam"


# Sarvam language support differs by direction: saaras (STT) understands 14
# languages, bulbul (TTS) speaks 11 — ur/ne/as are STT-only. Keep both maps
# here so the difference is visible in one place.
SARVAM_STT_LANGUAGE_MAP: dict[str, str] = {
    "hi": "hi-IN", "bn": "bn-IN", "kn": "kn-IN", "ml": "ml-IN",
    "mr": "mr-IN", "od": "od-IN", "pa": "pa-IN", "ta": "ta-IN",
    "te": "te-IN", "en": "en-IN", "gu": "gu-IN", "as": "as-IN",
    "ur": "ur-IN", "ne": "ne-IN",
}

SARVAM_TTS_LANGUAGE_MAP: dict[str, str] = {
    k: v for k, v in SARVAM_STT_LANGUAGE_MAP.items()
    if k not in ("as", "ur", "ne")
}

# Input codecs accepted by Sarvam STT (keyed by our AudioFormat).
SARVAM_INPUT_CODECS: dict[str, str] = {
    "pcm": "pcm_s16le", "wav": "wav", "mp3": "mp3", "mp4": "mp4",
    "m4a": "mp4", "webm": "webm", "ogg": "ogg", "flac": "flac",
    "mpeg": "mpeg", "mpga": "mpeg",
}

# Output codecs produced by Sarvam TTS (keyed by our TTS_RESPONSE_FORMAT).
SARVAM_OUTPUT_CODECS: dict[str, str] = {
    "opus": "opus", "mp3": "mp3", "aac": "aac", "flac": "flac",
    "wav": "wav", "pcm": "linear16",
}
