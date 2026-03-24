"""Tests for SSE streaming — event formatting and helpers."""

import json

from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    SSEEventType,
    SSE_RESPONSE_HEADERS,
    sse_done,
    sse_error,
    sse_event,
    sse_intent,
    sse_status,
    sse_token,
)


class TestSSEFormatting:
    def test_sse_event_basic(self):
        result = sse_event("test", {"key": "value"})
        assert result.startswith("event: test\n")
        assert result.endswith("\n\n")
        data_line = result.split("\n")[1]
        assert data_line.startswith("data: ")
        parsed = json.loads(data_line[6:])
        assert parsed == {"key": "value"}

    def test_sse_event_with_enum(self):
        result = sse_event(SSEEventType.TOKEN, {"delta": "hi"})
        assert "event: token\n" in result

    def test_sse_event_string_data(self):
        result = sse_event("test", "raw string")
        assert "data: raw string\n" in result

    def test_sse_status(self):
        result = sse_status(PipelineStage.EXTRACTING_INTENT, "Analyzing...")
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["stage"] == "extracting_intent"
        assert parsed["message"] == "Analyzing..."

    def test_sse_status_no_message(self):
        result = sse_status("custom_stage")
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["stage"] == "custom_stage"
        assert "message" not in parsed

    def test_sse_token(self):
        result = sse_token("Hello")
        assert "event: token\n" in result
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["delta"] == "Hello"

    def test_sse_intent(self):
        intent_data = {"is_ready": True, "data_types": ["cgm_range_stats"]}
        result = sse_intent(intent_data)
        assert "event: intent\n" in result
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["is_ready"] is True

    def test_sse_done_with_model(self):
        payload = SSEDonePayload(
            trace_id="trc_123",
            cost_usd=0.005,
            latency_ms=3200,
            model_id="gpt-5.1",
            suggestions=[{"label": "Next", "description": "What next?"}],
        )
        result = sse_done(payload)
        assert "event: done\n" in result
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["trace_id"] == "trc_123"
        assert parsed["cost_usd"] == 0.005
        assert parsed["model_id"] == "gpt-5.1"

    def test_sse_done_with_dict(self):
        result = sse_done({"trace_id": "abc"})
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["trace_id"] == "abc"

    def test_sse_error(self):
        result = sse_error("Something went wrong", code="timeout", fallback_text="Try again")
        assert "event: error\n" in result
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["message"] == "Something went wrong"
        assert parsed["code"] == "timeout"
        assert parsed["fallback_text"] == "Try again"

    def test_sse_error_defaults(self):
        result = sse_error("Oops")
        parsed = json.loads(result.split("data: ")[1].split("\n")[0])
        assert parsed["code"] == "internal_error"
        assert "fallback_text" not in parsed


class TestSSEHeaders:
    def test_content_type(self):
        assert SSE_RESPONSE_HEADERS["Content-Type"] == "text/event-stream"

    def test_no_cache(self):
        assert SSE_RESPONSE_HEADERS["Cache-Control"] == "no-cache"

    def test_nginx_buffering_off(self):
        assert SSE_RESPONSE_HEADERS["X-Accel-Buffering"] == "no"
