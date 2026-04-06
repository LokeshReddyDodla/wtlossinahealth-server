"""
Voice Agent router — WebSocket endpoint for real-time voice interaction.

Usage:
    ws://<host>/v1/voice/ws?token=<JWT>

Protocol:
    1. Connect with JWT in query param
    2. Send JSON: {"type": "session_start"}
    3. Receive JSON: {"type": "session_ready", "session_id": "vs_..."}
    4. Send binary audio frames (PCM 16kHz mono or WebM/Opus)
    5. Send JSON: {"type": "end_of_speech"} when user stops talking
    6. Receive: transcript → status → thinking_aloud + audio → response_text + audio → agent_done
    7. Repeat 4-6 for multi-turn conversation
    8. Send JSON: {"type": "session_end"} to close
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from lib.ai_foundation.voice.ws_dependencies import get_voice_connection_handler

router = APIRouter(prefix="/voice", tags=["voice-agent"])


@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time voice interaction with the health agent."""
    handler = get_voice_connection_handler()
    await handler.handle(websocket)
