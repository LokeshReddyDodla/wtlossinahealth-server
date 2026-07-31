"""
WebSocket handler — auth, connection lifecycle, and message routing.

Handles JWT authentication from query params, creates a VoiceSession,
and routes binary/JSON frames to the VoiceOrchestrator.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect, status

from lib.ai_foundation.agents.thread_utils import resolve_thread_id
from lib.core.constants import AIFeatureEnum
from lib.services.ai_feature_toggle_service import ai_feature_toggle_service
from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.orchestrator import VoiceOrchestrator
from lib.ai_foundation.voice.protocol import (
    SessionEndedMsg,
    SessionReadyMsg,
    VoiceErrorMsg,
)
from lib.ai_foundation.voice.session import VoiceSession
from lib.utils.jwt import decode_jwt_token

logger = logging.getLogger(__name__)


async def authenticate_websocket(websocket: WebSocket) -> tuple[str, str] | None:
    """Validate JWT from query parameter.

    Returns (user_id, role) or None if auth fails.
    WebSocket auth uses query params because headers aren't reliably
    supported by all WebSocket clients.
    """
    token = websocket.query_params.get("token")
    if not token:
        return None

    payload = decode_jwt_token(token)
    if payload is None:
        return None

    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or not role:
        return None

    return user_id, role


class VoiceConnectionHandler:
    """Manages a single WebSocket voice connection."""

    def __init__(
        self,
        *,
        orchestrator: VoiceOrchestrator,
        settings: VoiceSettings,
    ) -> None:
        self._orchestrator = orchestrator
        self._settings = settings

    async def handle(self, websocket: WebSocket) -> None:
        """Full WebSocket connection lifecycle."""

        # ── Auth ─────────────────────────────────────────────────────────
        auth = await authenticate_websocket(websocket)
        if auth is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication failed")
            return

        user_id, role = auth

        # Only patients can use voice for now
        if role != "patient":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Voice is only available for patients")
            return

        if not await ai_feature_toggle_service.is_enabled_for_patient(
            AIFeatureEnum.VOICE, user_id
        ):
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Voice assistant is temporarily unavailable",
            )
            return

        await websocket.accept()

        try:
            await self._connection_loop(websocket, user_id, role)
        except WebSocketDisconnect:
            logger.info("Voice WS disconnected: user=%s", user_id)
        except Exception:
            logger.exception("Voice WS error: user=%s", user_id)
            try:
                await self._send_json(websocket, VoiceErrorMsg(
                    code="internal_error", message="Connection error.",
                ).model_dump())
            except Exception:
                pass

    async def _connection_loop(
        self,
        websocket: WebSocket,
        user_id: str,
        role: str,
    ) -> None:
        """Main message loop after auth."""
        session: VoiceSession | None = None

        try:
            while True:
                message = await websocket.receive()

                # Binary frame = audio data
                if "bytes" in message and message["bytes"]:
                    if session is None:
                        continue  # Drop audio before session_start
                    if not session.append_audio(message["bytes"]):
                        await self._send_json(websocket, VoiceErrorMsg(
                            code="buffer_overflow",
                            message="Audio too long. Please keep it shorter.",
                        ).model_dump())
                        session.get_audio_and_reset()
                    continue

                # Text frame = JSON control message
                if "text" in message and message["text"]:
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type")

                    if msg_type == "session_start":
                        session = self._create_session(user_id, role, data)
                        await self._send_json(websocket, SessionReadyMsg(
                            session_id=session.session_id,
                        ).model_dump())
                        logger.info(
                            "Voice session started: %s (user=%s, thread=%s)",
                            session.session_id, user_id, session.thread_id,
                        )
                        # Spoken greeting
                        await self._orchestrator.greet(
                            session,
                            send_json=lambda d: self._send_json(websocket, d),
                            send_bytes=lambda b: self._send_bytes(websocket, b),
                        )

                    elif msg_type == "end_of_speech" and session is not None:
                        if session.has_audio:
                            audio = session.get_audio_and_reset()
                            await self._orchestrator.handle_utterance(
                                session,
                                audio,
                                send_json=lambda d: self._send_json(websocket, d),
                                send_bytes=lambda b: self._send_bytes(websocket, b),
                            )
                        else:
                            await self._send_json(websocket, VoiceErrorMsg(
                                code="no_audio",
                                message="No audio received. Please speak and try again.",
                            ).model_dump())

                    elif msg_type == "interrupt" and session is not None:
                        session.interrupt()

                    elif msg_type == "session_end":
                        if session:
                            await self._send_json(websocket, SessionEndedMsg().model_dump())
                        try:
                            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                        except RuntimeError:
                            pass  # Already closed by client
                        return

                # Disconnect
                if message.get("type") == "websocket.disconnect":
                    return
        finally:
            # Cancel in-flight TTS/agent work when connection closes for any reason
            if session is not None:
                session.interrupt()
                logger.debug("Session %s interrupted on connection close", session.session_id)

    def _create_session(
        self,
        user_id: str,
        role: str,
        data: dict[str, Any],
    ) -> VoiceSession:
        """Create a new voice session from session_start message."""
        thread_id = data.get("thread_id") or resolve_thread_id(
            role=role,
            actor_id=user_id,
            patient_ids=[user_id],
        )

        metadata: dict = {}
        if data.get("metadata"):
            metadata.update(data["metadata"])

        return VoiceSession(
            user_id=user_id,
            patient_id=user_id,  # For patients, user_id == patient_id
            thread_id=thread_id,
            settings=self._settings,
            metadata=metadata,
        )

    @staticmethod
    async def _send_json(websocket: WebSocket, data: dict) -> None:
        """Send a JSON message, suppressing errors on closed connections."""
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    @staticmethod
    async def _send_bytes(websocket: WebSocket, data: bytes) -> None:
        """Send binary data, suppressing errors on closed connections."""
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass
