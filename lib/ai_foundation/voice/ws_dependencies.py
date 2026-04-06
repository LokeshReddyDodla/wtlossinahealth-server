"""
Voice WebSocket dependencies — resolves services from the container.

Keeps the voice module self-contained. The router imports from here
instead of lib/dependencies/service_dependencies.py.
"""

from __future__ import annotations

from typing import cast

from lib.core.container import container
from lib.ai_foundation.voice.orchestrator import VoiceOrchestrator
from lib.ai_foundation.voice.ws_handler import VoiceConnectionHandler
from lib.ai_foundation.voice.config import voice_settings


def get_voice_orchestrator() -> VoiceOrchestrator:
    return cast(VoiceOrchestrator, container.resolve(VoiceOrchestrator))


def get_voice_connection_handler() -> VoiceConnectionHandler:
    """Build a connection handler with the orchestrator from the container."""
    return VoiceConnectionHandler(
        orchestrator=get_voice_orchestrator(),
        settings=voice_settings,
    )
