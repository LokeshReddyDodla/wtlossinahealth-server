"""Tests for SSE parsing utility."""

from __future__ import annotations

from lib.ai_foundation.voice.sse_utils import parse_sse_event


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
