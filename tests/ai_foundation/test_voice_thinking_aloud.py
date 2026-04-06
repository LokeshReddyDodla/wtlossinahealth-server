"""Tests for thinking-aloud mapper — SSE event to filler phrase conversion."""

from __future__ import annotations

from lib.ai_foundation.voice.config import VoiceSettings
from lib.ai_foundation.voice.thinking_aloud import ThinkingAloudMapper, parse_sse_event


class TestParseSSE:
    def test_parses_status_event(self):
        raw = 'event: status\ndata: {"stage": "analyzing", "message": "Looking..."}\n\n'
        name, data = parse_sse_event(raw)
        assert name == "status"
        assert data["stage"] == "analyzing"

    def test_parses_token_event(self):
        raw = 'event: token\ndata: {"delta": "Hello"}\n\n'
        name, data = parse_sse_event(raw)
        assert name == "token"
        assert data["delta"] == "Hello"

    def test_returns_none_for_empty(self):
        name, data = parse_sse_event("")
        assert name is None
        assert data == {}

    def test_handles_malformed_json(self):
        raw = "event: status\ndata: not-json\n\n"
        name, data = parse_sse_event(raw)
        assert name == "status"
        assert data == {}


class TestThinkingAloudMapper:
    def _make_mapper(self, **overrides) -> ThinkingAloudMapper:
        defaults = {
            "THINKING_ALOUD_ENABLED": True,
            "THINKING_COOLDOWN_SECONDS": 0,  # No cooldown for tests
            "THINKING_MAX_FILLERS_PER_TURN": 3,
        }
        defaults.update(overrides)
        settings = VoiceSettings(**defaults)
        return ThinkingAloudMapper(settings=settings)

    def test_returns_filler_for_status_analyzing(self):
        mapper = self._make_mapper()
        raw = 'event: status\ndata: {"stage": "analyzing"}\n\n'
        result = mapper.map_event(raw)
        assert result is not None
        assert len(result) > 0

    def test_returns_filler_for_fetching_data(self):
        mapper = self._make_mapper()
        raw = 'event: status\ndata: {"stage": "fetching_data"}\n\n'
        result = mapper.map_event(raw)
        assert result is not None

    def test_returns_none_for_token_events(self):
        mapper = self._make_mapper()
        raw = 'event: token\ndata: {"delta": "Hi"}\n\n'
        result = mapper.map_event(raw)
        assert result is None

    def test_returns_none_for_generating_response(self):
        mapper = self._make_mapper()
        raw = 'event: status\ndata: {"stage": "generating_response"}\n\n'
        result = mapper.map_event(raw)
        assert result is None

    def test_respects_max_fillers_per_turn(self):
        mapper = self._make_mapper(THINKING_MAX_FILLERS_PER_TURN=2)
        events = [
            'event: status\ndata: {"stage": "extracting_intent"}\n\n',
            'event: status\ndata: {"stage": "fetching_data"}\n\n',
            'event: status\ndata: {"stage": "analyzing"}\n\n',
        ]
        results = [mapper.map_event(e) for e in events]
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 2

    def test_respects_cooldown(self):
        mapper = self._make_mapper(THINKING_COOLDOWN_SECONDS=10.0)
        raw = 'event: status\ndata: {"stage": "fetching_data"}\n\n'
        first = mapper.map_event(raw)
        second = mapper.map_event(raw)
        assert first is not None
        assert second is None  # Cooldown not elapsed

    def test_reset_turn_clears_state(self):
        mapper = self._make_mapper(THINKING_MAX_FILLERS_PER_TURN=1)
        raw = 'event: status\ndata: {"stage": "fetching_data"}\n\n'
        mapper.map_event(raw)  # Use up the one filler

        mapper.reset_turn()
        result = mapper.map_event(raw)
        assert result is not None  # Fresh turn

    def test_disabled_returns_none(self):
        mapper = self._make_mapper(THINKING_ALOUD_ENABLED=False)
        raw = 'event: status\ndata: {"stage": "fetching_data"}\n\n'
        result = mapper.map_event(raw)
        assert result is None

    def test_specialist_domain_substitution(self):
        mapper = self._make_mapper()
        raw = 'event: specialist_start\ndata: {"domain": "glucose", "steps": 3}\n\n'
        result = mapper.map_event(raw)
        assert result is not None
        assert "glucose" in result
