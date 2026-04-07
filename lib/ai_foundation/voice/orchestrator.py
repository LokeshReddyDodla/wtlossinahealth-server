"""
Voice Orchestrator — main pipeline: STT → HealthQueryAgent → TTS.

Bridges the gap between raw audio and the existing text-based agent.
Speaks the agent's actual thoughts (reasoning, tool calls, findings)
so there's no silence while the agent investigates. Final response
is spoken as one continuous stream.

The orchestrator does NOT own the HealthQueryAgent — it wraps it.
All reasoning, tools, memory, and persistence stay in the agent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.state import AgentContext, AgentInput, RequestPriority
from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.protocol import (
    ResponseTextMsg,
    TranscriptMsg,
    VoiceErrorMsg,
)
from lib.ai_foundation.voice.session import VoiceSession, VoiceSessionState
from lib.ai_foundation.voice.stt import SpeechToText
from lib.ai_foundation.voice.sse_utils import parse_sse_event
from lib.ai_foundation.voice.tts import TextToSpeech

logger = logging.getLogger(__name__)

# SSE events forwarded as JSON to the client (same type names as text chat)
_FORWARDED_EVENTS = frozenset({
    "status", "intent", "reasoning", "tool_call", "tool_result",
    "plan", "reflection", "specialist_start", "specialist_done",
})

# Events spoken aloud — only LLM-generated text that sounds natural.
# reasoning: single-domain path thoughts (from ReasoningEngine)
# plan: multi-domain path strategy (from Coordinator) — fills silence
#       when reasoning events aren't emitted
_SPEAKABLE_EVENTS: dict[str, Callable[[dict], str | None]] = {
    "reasoning": lambda d: d.get("thought"),
    "plan": lambda d: d.get("strategy"),
}

SendJson = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
SendBytes = Callable[[bytes], Coroutine[Any, Any, None]]


class VoiceOrchestrator:
    """Bridges audio I/O with the text-based HealthQueryAgent."""

    def __init__(
        self,
        *,
        stt: SpeechToText,
        tts: TextToSpeech,
        agent: HealthQueryAgent,
        patient_resolver: PatientNameResolver,
        memory: MongoMemoryStore,
        settings: VoiceSettings,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._agent = agent
        self._patient_resolver = patient_resolver
        self._memory = memory
        self._settings = settings

    async def greet(
        self,
        session: VoiceSession,
        *,
        send_json: SendJson,
        send_bytes: SendBytes,
    ) -> None:
        """Send a personalized spoken greeting when the voice session starts."""
        try:
            pid = session.patient_id or session.user_id

            # Fetch name + facts in parallel
            name_coro = self._patient_resolver.resolve_name(pid)
            facts_coro = self._memory.get_patient_facts(pid)
            name, facts = await asyncio.gather(name_coro, facts_coro)

            first_name = name.split()[0] if name else ""
            greeting = _build_greeting(first_name, facts)

            await send_json({"type": "greeting", "text": greeting})
            await self._speak(greeting, send_bytes, session)
        except Exception:
            logger.warning("Greeting failed for session %s", session.session_id, exc_info=True)
            # Fallback greeting
            try:
                await send_json({"type": "greeting", "text": "Hey, how can I help you today?"})
                await self._speak("Hey, how can I help you today?", send_bytes, session)
            except Exception:
                pass

    async def handle_utterance(
        self,
        session: VoiceSession,
        audio_bytes: bytes,
        *,
        send_json: SendJson,
        send_bytes: SendBytes,
    ) -> None:
        """Full pipeline: audio → STT → Agent → TTS → audio.

        Args:
            session: Current voice session.
            audio_bytes: Raw audio from the client.
            send_json: Callback to send a JSON message to the client.
            send_bytes: Callback to send binary audio to the client.
        """
        session.clear_interrupt()
        session.state = VoiceSessionState.PROCESSING

        # ── 1. Speech-to-Text ────────────────────────────────────────────
        try:
            result = await self._stt.transcribe(audio_bytes)
        except Exception:
            logger.exception("STT failed for session %s", session.session_id)
            await send_json(VoiceErrorMsg(
                code="stt_failed",
                message="I couldn't understand the audio. Could you try again?",
            ).model_dump())
            session.state = VoiceSessionState.IDLE
            return

        # Send transcript to client
        await send_json(TranscriptMsg(
            text=result.text,
            is_final=True,
            language=result.language,
            duration_seconds=result.duration_seconds,
        ).model_dump())

        if not result.text.strip():
            await send_json(VoiceErrorMsg(
                code="empty_transcript",
                message="I didn't catch that. Could you say that again?",
            ).model_dump())
            session.state = VoiceSessionState.IDLE
            return

        # ── 2. Build AgentInput ──────────────────────────────────────────
        agent_input = AgentInput(
            message=result.text,
            context=AgentContext(
                patient_id=session.patient_id,
                user_id=session.user_id,
                user_role="patient",
                thread_id=session.thread_id,
                patient_ids=[session.patient_id] if session.patient_id else [],
                priority=RequestPriority.NORMAL,
                metadata={**session.metadata, "output_mode": "voice"},
            ),
            stream=True,
        )

        # ── 3. Consume agent stream ─────────────────────────────────────
        token_buffer: list[str] = []
        speaking_task: asyncio.Task | None = None

        try:
            async for sse_raw in self._agent.run_stream(agent_input):
                if session.is_cancelled:
                    break

                event_name, event_data = parse_sse_event(sse_raw)
                if event_name is None:
                    continue

                # Forward all agent events as JSON (same types as text chat)
                if event_name in _FORWARDED_EVENTS:
                    await send_json({"type": event_name, **event_data})

                # Speak thoughts aloud — wait for each to finish before next
                extractor = _SPEAKABLE_EVENTS.get(event_name)
                if extractor and not session.is_cancelled:
                    phrase = extractor(event_data)
                    if phrase and phrase.strip():
                        # Wait for any previous speech to finish
                        if speaking_task and not speaking_task.done():
                            await speaking_task
                        speaking_task = asyncio.create_task(
                            self._speak(phrase, send_bytes, session)
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

                    # Send text for display
                    await send_json(ResponseTextMsg(text=full_response).model_dump())

                    # Wait for any in-flight thought speech to finish
                    if speaking_task and not speaking_task.done():
                        await speaking_task

                    # One TTS stream for the full response
                    if full_response.strip() and not session.is_cancelled:
                        session.state = VoiceSessionState.SPEAKING
                        await self._speak(full_response, send_bytes, session)

                    await send_json({"type": "done", **event_data})
                    session.state = VoiceSessionState.IDLE
                    return

                # Error
                if event_name == "error":
                    error_msg = event_data.get("message", "Something went wrong.")
                    fallback = event_data.get("fallback_text", error_msg)
                    await send_json(VoiceErrorMsg(
                        code="agent_error", message=error_msg,
                    ).model_dump())

                    if speaking_task and not speaking_task.done():
                        await speaking_task
                    if not session.is_cancelled:
                        await self._speak(fallback, send_bytes, session)

                    session.state = VoiceSessionState.IDLE
                    return

        except Exception:
            logger.exception("Voice pipeline error for session %s", session.session_id)
            await send_json(VoiceErrorMsg(
                code="pipeline_error",
                message="Sorry, something went wrong. Please try again.",
            ).model_dump())
        finally:
            if speaking_task and not speaking_task.done():
                speaking_task.cancel()
            session.state = VoiceSessionState.IDLE

    # ── TTS ──────────────────────────────────────────────────────────────

    async def _speak(
        self,
        text: str,
        send_bytes: SendBytes,
        session: VoiceSession,
    ) -> None:
        """Stream TTS audio to client, respecting interruption."""
        if not text.strip():
            return

        logger.info("TTS: speaking %d chars: %s", len(text), text[:80])
        total_bytes = 0
        try:
            async for chunk in self._tts.synthesize_stream(text):
                if session.is_cancelled:
                    break
                total_bytes += len(chunk)
                await send_bytes(chunk)
            logger.info("TTS: sent %d bytes", total_bytes)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.error("TTS failed for session %s", session.session_id, exc_info=True)


def _build_greeting(first_name: str, facts: list) -> str:
    """Build a personal greeting from the patient's name and stored facts."""
    name = first_name or "there"

    # Try to find something personal to reference
    goal = None
    condition = None
    for f in facts:
        key = getattr(f, "key", "") or ""
        value = getattr(f, "value", "") or ""
        category = getattr(f, "category", "") or ""
        if not goal and category == "goal" and value:
            goal = value
        if not condition and key in ("diagnosis", "condition", "medical_condition") and value:
            condition = value
        if goal:
            break  # Goal is the best hook

    if goal:
        return f"Hey {name}! How's the {goal} journey going? What can I help with?"
    if condition:
        return f"Hey {name}! How are you feeling today? What would you like to check?"
    return f"Hey {name}! What would you like to know about your health today?"
