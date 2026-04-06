"""
Voice WebSocket dependencies — resolves services from the container.

Keeps the voice module self-contained. The router imports from here
instead of lib/dependencies/service_dependencies.py.
"""

from __future__ import annotations

from typing import cast

from lib.core.container import container
from lib.ai_foundation.voice.orchestrator import VoiceOrchestrator


def get_voice_orchestrator() -> VoiceOrchestrator:
    return cast(VoiceOrchestrator, container.resolve(VoiceOrchestrator))
