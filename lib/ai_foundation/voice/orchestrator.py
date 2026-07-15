"""
Voice Orchestrator — main pipeline: STT → HealthQueryAgent → TTS.

Audio boundary protocol:
    Every spoken segment is wrapped in audio_start / audio_end.
    Binary frames only appear between these two signals — never orphaned.
    Only one segment is open at a time. done always comes after the
    final audio_end. Any binary received outside an open segment is a
    protocol error and should be ignored by the client.

Segment types: greeting, reasoning, plan, response_text, error.
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
from collections.abc import Callable, Coroutine
from typing import Any

from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.state import AgentContext, AgentInput, RequestPriority
from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.protocol import (
    ResponseTextMsg,
    TranscriptMsg,
    VoiceErrorMsg,
)
from lib.ai_foundation.voice.session import VoiceSession, VoiceSessionState
from lib.ai_foundation.voice.stt import BaseSpeechToText
from lib.ai_foundation.voice.sse_utils import parse_sse_event
from lib.ai_foundation.voice.tts import BaseTextToSpeech

logger = logging.getLogger(__name__)

def _normalize_spoken_language(raw: str | None) -> str | None:
    """Detected STT language → base ISO code, or None when unusable.

    Providers disagree on the output format — Sarvam gives tags ("hi-IN"),
    Whisper can give full names ("hindi"). langcodes resolves both for any
    language; no hand-maintained name list.
    """
    if not raw:
        return None
    code = raw.strip().lower()
    if code in ("unknown", "und"):
        return None

    import langcodes

    try:
        lang = langcodes.Language.get(code)
        if lang.is_valid():
            return lang.language
    except Exception:
        pass
    try:
        return langcodes.find(code).language  # full names: "hindi" → "hi"
    except LookupError:
        return None

# SSE events forwarded as JSON to the client (same type names as text chat)
_FORWARDED_EVENTS = frozenset({
    "status", "intent", "reasoning", "tool_call", "tool_result",
    "plan", "reflection", "specialist_start", "specialist_done",
})

# Events spoken aloud — only LLM-generated text that sounds natural.
# The key is the SSE event name, value extracts speakable text.
# segment_type sent to Flutter matches the event name.
_SPEAKABLE_EVENTS: dict[str, Callable[[dict], str | None]] = {
    "reasoning": lambda d: d.get("thought"),
    "plan": lambda d: d.get("strategy"),
}

SendJson = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
SendBytes = Callable[[bytes], Coroutine[Any, Any, None]]

# (patient_id, audio_bytes) → audio_url or None
UploadAudio = Callable[[str, bytes], Coroutine[Any, Any, str | None]]


class VoiceOrchestrator:
    """Bridges audio I/O with the text-based HealthQueryAgent."""

    def __init__(
        self,
        *,
        stt: BaseSpeechToText,
        tts: BaseTextToSpeech,
        agent: HealthQueryAgent,
        patient_resolver: PatientNameResolver,
        settings: VoiceSettings,
        upload_audio: UploadAudio | None = None,
        translation: Any = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._agent = agent
        self._patient_resolver = patient_resolver
        self._settings = settings
        self._upload_audio = upload_audio
        self._translation = translation

    async def _localize(self, text: str, language: str) -> str:
        """Canned strings (greeting, errors) in the session language — same
        cached-translation path every other surface uses."""
        if language == "en" or not text or self._translation is None:
            return text
        try:
            return await self._translation.translate_cached(text, language)
        except Exception:
            return text  # spoken English beats silence

    def _speakable_language(self, language: str | None) -> str | None:
        """A language is usable only if the TTS provider can voice it —
        STT understands more languages than TTS speaks (e.g. Urdu on Sarvam)."""
        if language and self._tts.supports_language(language):
            return language
        return None

    async def greet(
        self,
        session: VoiceSession,
        *,
        send_json: SendJson,
        send_bytes: SendBytes,
    ) -> None:
        """Send a warm spoken greeting when the voice session starts."""
        try:
            pid = session.patient_id or session.user_id
            name = await self._patient_resolver.resolve_name(pid)
            first_name = name.split()[0] if name else ""

            # No speech heard yet — the stored preference is the best signal.
            # Each utterance re-decides by mirroring the spoken language.
            try:
                pref = await self._patient_resolver.resolve_language(pid)
            except Exception:
                pref = "en"
            session.language = self._speakable_language(pref) or "en"

            greeting = await self._localize(_pick_greeting(first_name), session.language)

            # Semantic event first (Flutter shows text from this)
            await send_json({"type": "greeting", "text": greeting})
            # Then audio with explicit boundaries
            await self._speak(greeting, send_json, send_bytes, session,
                              segment_type="greeting", language=session.language)
        except Exception:
            logger.warning("Greeting failed for session %s", session.session_id, exc_info=True)

    async def handle_utterance(
        self,
        session: VoiceSession,
        audio_bytes: bytes,
        *,
        send_json: SendJson,
        send_bytes: SendBytes,
    ) -> None:
        """Full pipeline: audio → STT → Agent → TTS → audio."""
        session.clear_interrupt()
        session.state = VoiceSessionState.PROCESSING

        # ── 1. Speech-to-Text + audio upload (concurrent) ─────────────────
        pid = session.patient_id or session.user_id
        upload_coro = self._upload_audio(pid, audio_bytes) if self._upload_audio else None

        tasks: list = [self._stt.transcribe(audio_bytes)]
        if upload_coro:
            tasks.append(upload_coro)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        result = results[0]
        audio_url = results[1] if len(results) > 1 else None

        if isinstance(result, Exception):
            logger.error("STT failed for session %s: %s", session.session_id, result, exc_info=result)
            await send_json(VoiceErrorMsg(
                code="stt_failed",
                message=await self._localize(
                    "I couldn't understand the audio. Could you try again?", session.language,
                ),
            ).model_dump())
            session.state = VoiceSessionState.IDLE
            return

        if isinstance(audio_url, Exception):
            logger.warning("Voice audio upload failed for %s: %s", pid, audio_url)
            audio_url = None

        await send_json(TranscriptMsg(
            text=result.text,
            is_final=True,
            language=result.language,
            duration_seconds=result.duration_seconds,
        ).model_dump())

        if not result.text.strip():
            await send_json(VoiceErrorMsg(
                code="empty_transcript",
                message=await self._localize(
                    "I didn't catch that. Could you say that again?", session.language,
                ),
            ).model_dump())
            session.state = VoiceSessionState.IDLE
            return

        # ── 2. Reply language MIRRORS the spoken language ────────────────
        # Speaking is itself a language choice — voice has no "view in
        # English" toggle, so the utterance wins over the stored preference.
        # Constrained to what TTS can voice; falls back to the session seed.
        spoken = self._speakable_language(_normalize_spoken_language(result.language))
        voice_language = spoken or session.language or "en"
        session.language = voice_language

        # ── 3. Build AgentInput ──────────────────────────────────────────
        agent_input = AgentInput(
            message=result.text,
            context=AgentContext(
                patient_id=session.patient_id,
                user_id=session.user_id,
                user_role="patient",
                thread_id=session.thread_id,
                patient_ids=[session.patient_id] if session.patient_id else [],
                priority=RequestPriority.NORMAL,
                metadata={
                    **session.metadata,
                    "output_mode": "voice",
                    "audio_url": audio_url,
                    "voice_language": voice_language,
                },
            ),
            stream=True,
        )

        # ── 3. Consume agent stream ─────────────────────────────────────
        token_buffer: list[str] = []

        try:
            async for sse_raw in self._agent.run_stream(agent_input):
                if session.is_cancelled:
                    break

                event_name, event_data = parse_sse_event(sse_raw)
                if event_name is None:
                    continue

                # Forward all agent events as JSON (semantic events — UI source of truth)
                if event_name in _FORWARDED_EVENTS:
                    await send_json({"type": event_name, **event_data})

                # Speak thoughts aloud — sequential, one at a time. Thoughts
                # are generated in English; voicing them in a non-English
                # session would mix languages mid-conversation, so they stay
                # text-only there (still forwarded as JSON above).
                extractor = _SPEAKABLE_EVENTS.get(event_name)
                if extractor and not session.is_cancelled and voice_language == "en":
                    phrase = extractor(event_data)
                    if phrase and phrase.strip():
                        await self._speak(
                            phrase, send_json, send_bytes, session,
                            segment_type=event_name, language="en",
                        )

                # Accumulate response tokens
                if event_name == "token":
                    token_buffer.append(event_data.get("delta", ""))

                # Done — speak the full response as one stream
                if event_name == "done":
                    if session.is_cancelled:
                        break

                    full_response = event_data.get("data", {}).get("full_response", "")
                    if not full_response:
                        full_response = "".join(token_buffer)

                    # Semantic event (Flutter shows text from this)
                    await send_json(ResponseTextMsg(text=full_response).model_dump())

                    # One TTS stream for the full response
                    if full_response.strip() and not session.is_cancelled:
                        session.state = VoiceSessionState.SPEAKING
                        await self._speak(
                            full_response, send_json, send_bytes, session,
                            segment_type="response_text", language=voice_language,
                        )

                    # done always after the final audio_end
                    await send_json({"type": "done", **event_data})
                    session.state = VoiceSessionState.IDLE
                    return

                # Error
                if event_name == "error":
                    error_msg = event_data.get("message", "Something went wrong.")
                    fallback = event_data.get("fallback_text", error_msg)

                    # Semantic event
                    await send_json(VoiceErrorMsg(
                        code="agent_error", message=error_msg,
                    ).model_dump())

                    if not session.is_cancelled:
                        await self._speak(
                            fallback, send_json, send_bytes, session,
                            segment_type="error", language=voice_language,
                        )

                    session.state = VoiceSessionState.IDLE
                    return

        except Exception:
            logger.exception("Voice pipeline error for session %s", session.session_id)
            await send_json(VoiceErrorMsg(
                code="pipeline_error",
                message=await self._localize(
                    "Sorry, something went wrong. Please try again.", session.language,
                ),
            ).model_dump())
        finally:
            session.state = VoiceSessionState.IDLE

    # ── TTS with explicit audio boundaries ───────────────────────────────

    async def _speak(
        self,
        text: str,
        send_json: SendJson,
        send_bytes: SendBytes,
        session: VoiceSession,
        *,
        segment_type: str,
        language: str | None = None,
    ) -> None:
        """Stream TTS audio wrapped in audio_start/audio_end.

        Guarantees:
        - audio_start always before any binary
        - audio_end always after, even on interrupt/error
        - No orphan binary outside start/end
        - completed=false + reason on interruption/error
        - No unrelated JSON between audio_start and audio_end
        - Only one segment open at a time (enforced by sequential awaits)
        - Any binary outside an open segment is a protocol error
        """
        if not text.strip():
            return

        segment_id = f"seg_{secrets.token_hex(6)}"

        await send_json({
            "type": "audio_start",
            "segment_id": segment_id,
            "segment_type": segment_type,
            "text": text,
        })

        total_bytes = 0
        completed = True
        reason: str | None = None

        try:
            async for chunk in self._tts.synthesize_stream(text, language=language):
                if session.is_cancelled:
                    completed = False
                    reason = "interrupted"
                    break
                total_bytes += len(chunk)
                await send_bytes(chunk)
        except asyncio.CancelledError:
            completed = False
            reason = "cancelled"
        except Exception:
            completed = False
            reason = "tts_error"
            logger.error("TTS failed [%s/%s]", segment_id, segment_type, exc_info=True)

        end_payload: dict[str, Any] = {
            "type": "audio_end",
            "segment_id": segment_id,
            "segment_type": segment_type,
            "bytes_sent": total_bytes,
            "completed": completed,
        }
        if reason:
            end_payload["reason"] = reason

        await send_json(end_payload)


# ── Greetings ────────────────────────────────────────────────────────────

_GREETINGS_WITH_NAME = [
    "Hey {name}! What's on your mind today?",
    "Hi {name}! How are you doing? What would you like to check?",
    "Hey {name}! Good to hear from you. What can I help with?",
    "Hi {name}! What would you like to know today?",
    "Hey {name}! Ready when you are. What's up?",
    "Hi {name}! How's it going? Ask me anything.",
    "Hey {name}! What can I look into for you today?",
]

_GREETINGS_NO_NAME = [
    "Hey! What's on your mind today?",
    "Hi there! What would you like to check?",
    "Hey! Good to hear from you. What can I help with?",
    "Hi! Ready when you are. What's up?",
]


def _pick_greeting(first_name: str) -> str:
    """Pick a random warm greeting, using the patient's name if available."""
    if first_name:
        return random.choice(_GREETINGS_WITH_NAME).format(name=first_name)
    return random.choice(_GREETINGS_NO_NAME)
