"""
Voice Session — state machine for a single WebSocket voice connection.

Each WebSocket connection creates one VoiceSession. Sessions share the same
thread_id as text chat, so patients can switch freely between voice and text.

States: IDLE → LISTENING → PROCESSING → SPEAKING → (INTERRUPTED → IDLE)
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from enum import Enum

from lib.ai_foundation.voice.config import VoiceSettings

logger = logging.getLogger(__name__)


class VoiceSessionState(str, Enum):
    """Voice session states."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"


class VoiceSession:
    """Manages state for a single voice WebSocket connection."""

    def __init__(
        self,
        *,
        user_id: str,
        patient_id: str | None,
        thread_id: str,
        settings: VoiceSettings,
        role: str = "patient",
        metadata: dict | None = None,
    ) -> None:
        self.session_id: str = f"vs_{secrets.token_hex(8)}"
        self.user_id = user_id
        self.patient_id = patient_id
        # Actor role — patient (self) or care_provider/admin asking about a patient.
        self.role = role
        self.thread_id = thread_id
        self.metadata: dict = metadata or {}
        # Reply language for this session: seeded from the patient's stored
        # preference, then MIRRORS whatever language each utterance is spoken
        # in (voice has no "view in English" toggle — the spoken language IS
        # the user's choice). Always a TTS-speakable code.
        self.language: str = "en"
        self.state = VoiceSessionState.IDLE
        self.created_at: float = time.monotonic()
        self.last_activity: float = time.monotonic()

        self._settings = settings
        self._audio_buffer = bytearray()
        self._cancel_event = asyncio.Event()
        self._speaking_task: asyncio.Task | None = None

    # ── Audio buffer ─────────────────────────────────────────────────────

    def append_audio(self, chunk: bytes) -> bool:
        """Append audio data to the buffer.

        Returns False if buffer would exceed max size (frame rejected).
        """
        if len(self._audio_buffer) + len(chunk) > self._settings.AUDIO_BUFFER_MAX_BYTES:
            logger.warning(
                "Session %s: audio buffer overflow (%d + %d > %d)",
                self.session_id,
                len(self._audio_buffer),
                len(chunk),
                self._settings.AUDIO_BUFFER_MAX_BYTES,
            )
            return False

        self._audio_buffer.extend(chunk)
        self.last_activity = time.monotonic()

        if self.state == VoiceSessionState.IDLE:
            self.state = VoiceSessionState.LISTENING

        return True

    def get_audio_and_reset(self) -> bytes:
        """Return accumulated audio and clear the buffer."""
        audio = bytes(self._audio_buffer)
        self._audio_buffer.clear()
        return audio

    @property
    def audio_buffer_size(self) -> int:
        return len(self._audio_buffer)

    @property
    def has_audio(self) -> bool:
        return len(self._audio_buffer) > 0

    # ── Interruption ─────────────────────────────────────────────────────

    def interrupt(self) -> None:
        """Signal the orchestrator to stop speaking and cancel current work."""
        self._cancel_event.set()
        if self._speaking_task and not self._speaking_task.done():
            self._speaking_task.cancel()
        self.state = VoiceSessionState.INTERRUPTED
        self._audio_buffer.clear()
        logger.info("Session %s: interrupted", self.session_id)

    def clear_interrupt(self) -> None:
        """Reset the cancel signal for the next utterance."""
        self._cancel_event.clear()
        self.state = VoiceSessionState.IDLE

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ── Lifecycle ────────────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        """Check if the session has timed out due to inactivity."""
        return (time.monotonic() - self.last_activity) > self._settings.SESSION_TIMEOUT_SECONDS

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.monotonic()
