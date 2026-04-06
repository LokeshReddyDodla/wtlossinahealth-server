"""
Thinking Aloud — maps SSE pipeline events to spoken filler phrases.

While the Health Query Agent investigates (tool calls, reasoning, fetching data),
the patient hears natural filler speech instead of silence. This mapper converts
raw SSE event strings into short phrases suitable for TTS.

Rate-limited: max 1 filler per cooldown period, max N per turn. Avoids repeating
the same phrase within a session.
"""

from __future__ import annotations

import json
import random
import time

from lib.ai_foundation.voice.config import VoiceSettings

# SSE event key → list of natural filler phrases
_FILLER_MAP: dict[str, list[str]] = {
    # Pipeline status events
    "status:understanding_query": [
        "Let me understand your question.",
        "Alright, let me think about that.",
    ],
    "status:extracting_intent": [
        "One moment while I process that.",
        "Let me figure out what you need.",
    ],
    "status:fetching_data": [
        "Let me check your records.",
        "Looking at your data now.",
        "One moment while I pull that up.",
        "Checking your health records.",
    ],
    "status:analyzing": [
        "Analyzing what I've found.",
        "Let me look at these numbers.",
        "Going through the details now.",
    ],
    "status:generating_response": [],  # No filler — response is imminent
    # Agentic reasoning events
    "reasoning": [
        "Hmm, interesting.",
        "I see something here.",
        "Let me think about this.",
    ],
    "tool_call": [
        "Let me check one more thing.",
        "Looking into that.",
    ],
    "plan": [
        "I have a plan for this.",
        "Let me investigate step by step.",
    ],
    "reflection": [
        "Let me double-check that.",
        "Making sure I haven't missed anything.",
    ],
    # Multi-agent events
    "specialist_start": [
        "Looking at your {domain} data.",
        "Consulting the {domain} records.",
    ],
}

# All unique phrases for precaching
ALL_FILLER_PHRASES: list[str] = []
for _phrases in _FILLER_MAP.values():
    for _p in _phrases:
        if "{" not in _p and _p not in ALL_FILLER_PHRASES:
            ALL_FILLER_PHRASES.append(_p)


class ThinkingAloudMapper:
    """Converts SSE events into spoken filler phrases with rate limiting."""

    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._last_filler_time: float = 0.0
        self._filler_count: int = 0
        self._used_phrases: set[str] = set()

    def reset_turn(self) -> None:
        """Reset per-turn state. Call at the start of each agent invocation."""
        self._filler_count = 0
        self._used_phrases.clear()
        self._last_filler_time = 0.0

    def map_event(self, sse_raw: str) -> str | None:
        """Given a raw SSE event string, return a filler phrase or None.

        Returns None if:
        - The event type has no filler phrases
        - Cooldown period hasn't elapsed
        - Max fillers per turn reached
        - Thinking aloud is disabled
        """
        if not self._settings.THINKING_ALOUD_ENABLED:
            return None

        if self._filler_count >= self._settings.THINKING_MAX_FILLERS_PER_TURN:
            return None

        now = time.monotonic()
        if now - self._last_filler_time < self._settings.THINKING_COOLDOWN_SECONDS:
            return None

        event_name, event_data = parse_sse_event(sse_raw)
        if event_name is None:
            return None

        # Build lookup key: "status:analyzing" or just "reasoning"
        key = event_name
        if event_name == "status":
            stage = event_data.get("stage", "")
            key = f"status:{stage}"

        phrases = _FILLER_MAP.get(key)
        if not phrases:
            return None

        # Pick a phrase not yet used this turn
        available = [p for p in phrases if p not in self._used_phrases]
        if not available:
            available = phrases  # All used — allow repeats

        phrase = random.choice(available)

        # Template substitution for specialist events
        if "{domain}" in phrase:
            domain = event_data.get("domain", "health")
            phrase = phrase.replace("{domain}", domain)

        self._used_phrases.add(phrase)
        self._filler_count += 1
        self._last_filler_time = now

        return phrase


def parse_sse_event(raw: str) -> tuple[str | None, dict]:
    """Extract event name and parsed data from a raw SSE string.

    Returns (event_name, event_data) where event_data defaults to {}
    if missing or unparseable.
    """
    event_name = None
    data_str = None

    for line in raw.strip().split("\n"):
        if line.startswith("event: "):
            event_name = line[7:].strip()
        elif line.startswith("data: "):
            data_str = line[6:].strip()

    if event_name is None:
        return None, {}

    event_data: dict = {}
    if data_str:
        try:
            event_data = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            pass

    return event_name, event_data
