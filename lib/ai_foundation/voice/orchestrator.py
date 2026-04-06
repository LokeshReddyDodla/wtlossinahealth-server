"""
Voice Orchestrator — main pipeline: STT → HealthQueryAgent → TTS.

Bridges the gap between raw audio and the existing text-based agent.
Handles thinking-aloud filler phrases, sentence-level TTS chunking,
and interruption support.

The orchestrator does NOT own the HealthQueryAgent — it wraps it.
All reasoning, tools, memory, and persistence stay in the agent.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any

from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.state import AgentContext, AgentInput, RequestPriority
from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.protocol import (
    AgentDoneMsg,
    ResponseTextMsg,
    ThinkingAloudMsg,
    TranscriptMsg,
    VoiceErrorMsg,
    VoiceStatusMsg,
)
from lib.ai_foundation.voice.session import VoiceSession, VoiceSessionState
from lib.ai_foundation.voice.stt import SpeechToText
from lib.ai_foundation.voice.thinking_aloud import ThinkingAloudMapper, parse_sse_event
from lib.ai_foundation.voice.tts import TextToSpeech

logger = logging.getLogger(__name__)

# Regex to split text at sentence boundaries for chunked TTS
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


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
        thinking_mapper: ThinkingAloudMapper,
        settings: VoiceSettings,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._agent = agent
        self._thinking = thinking_mapper
        self._settings = settings

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
        self._thinking.reset_turn()

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
                metadata=session.metadata,
            ),
            stream=True,
        )

        # ── 3. Consume agent stream ─────────────────────────────────────
        token_buffer: list[str] = []
        tts_tasks: list[asyncio.Task] = []

        try:
            async for sse_raw in self._agent.run_stream(agent_input):
                if session.is_cancelled:
                    break

                event_name, event_data = parse_sse_event(sse_raw)
                if event_name is None:
                    continue

                # Forward status events as JSON
                if event_name == "status":
                    await send_json(VoiceStatusMsg(
                        stage=event_data.get("stage", ""),
                        message=event_data.get("message"),
                    ).model_dump())

                # Thinking-aloud filler
                filler = self._thinking.map_event(sse_raw)
                if filler and not session.is_cancelled:
                    await send_json(ThinkingAloudMsg(phrase=filler).model_dump())
                    task = asyncio.create_task(
                        self._send_filler_audio(filler, send_bytes, session)
                    )
                    tts_tasks.append(task)

                # Accumulate response tokens
                if event_name == "token":
                    delta = event_data.get("delta", "")
                    token_buffer.append(delta)

                    # Sentence-level TTS: start speaking completed sentences
                    text_so_far = "".join(token_buffer)
                    sentences = _SENTENCE_END.split(text_so_far)
                    if len(sentences) > 1:
                        # Speak all complete sentences, keep the incomplete tail
                        complete = " ".join(sentences[:-1])
                        token_buffer.clear()
                        token_buffer.append(sentences[-1])

                        if not session.is_cancelled:
                            session.state = VoiceSessionState.SPEAKING
                            task = asyncio.create_task(
                                self._stream_tts(complete, send_bytes, session)
                            )
                            tts_tasks.append(task)

                # Done event — stream remaining text and send metadata
                if event_name == "done":
                    if session.is_cancelled:
                        break

                    full_response = event_data.get("data", {}).get("full_response", "")
                    if not full_response:
                        full_response = "".join(token_buffer)

                    # Send text response for display
                    await send_json(ResponseTextMsg(text=full_response).model_dump())

                    # Wait for any in-flight TTS to finish
                    if tts_tasks:
                        await asyncio.gather(*tts_tasks, return_exceptions=True)
                        tts_tasks.clear()

                    # Stream remaining buffered text
                    remaining = "".join(token_buffer).strip()
                    if remaining and not session.is_cancelled:
                        session.state = VoiceSessionState.SPEAKING
                        await self._stream_tts(remaining, send_bytes, session)

                    # Send done metadata
                    await send_json(AgentDoneMsg(
                        suggestions=event_data.get("suggestions", []),
                        trace_id=event_data.get("trace_id"),
                        cost_usd=event_data.get("cost_usd"),
                        latency_ms=event_data.get("latency_ms"),
                    ).model_dump())

                    session.state = VoiceSessionState.IDLE
                    return

                # Error event
                if event_name == "error":
                    error_msg = event_data.get("message", "Something went wrong.")
                    fallback = event_data.get("fallback_text", error_msg)
                    await send_json(VoiceErrorMsg(
                        code="agent_error", message=error_msg,
                    ).model_dump())

                    # Speak the error
                    if not session.is_cancelled:
                        await self._stream_tts(fallback, send_bytes, session)

                    session.state = VoiceSessionState.IDLE
                    return

        except Exception:
            logger.exception("Voice pipeline error for session %s", session.session_id)
            await send_json(VoiceErrorMsg(
                code="pipeline_error",
                message="Sorry, something went wrong. Please try again.",
            ).model_dump())
        finally:
            # Cancel any lingering TTS tasks
            for task in tts_tasks:
                if not task.done():
                    task.cancel()
            session.state = VoiceSessionState.IDLE

    # ── TTS helpers ──────────────────────────────────────────────────────

    async def _stream_tts(
        self,
        text: str,
        send_bytes: SendBytes,
        session: VoiceSession,
    ) -> None:
        """Stream TTS audio to client, respecting interruption."""
        try:
            async for chunk in self._tts.synthesize_stream(text):
                if session.is_cancelled:
                    break
                await send_bytes(chunk)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("TTS streaming failed for session %s", session.session_id, exc_info=True)

    async def _send_filler_audio(
        self,
        phrase: str,
        send_bytes: SendBytes,
        session: VoiceSession,
    ) -> None:
        """Synthesize and send a short filler phrase."""
        try:
            audio = await self._tts.synthesize(phrase)
            if audio and not session.is_cancelled:
                await send_bytes(audio)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Filler TTS failed: %s", phrase, exc_info=True)


