"""Tests for ModelGateway — LLM calls, fallback chains, circuit breaker, streaming."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai_foundation.models.circuit_breaker import CircuitBreaker
from lib.ai_foundation.models.gateway import (
    AllProvidersUnavailableError,
    LLMResponse,
    LLMToolResponse,
    LLMUsage,
    ModelGateway,
    StreamChunk,
    ToolCall,
    safe_cost,
)
from lib.ai_foundation.models.pricing import CostBreakdown
from lib.ai_foundation.models.registry import (
    ModelProvider,
    ModelRegistry,
    ModelSpec,
    ModelTask,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_spec(model_id: str = "test-model", provider: ModelProvider = ModelProvider.OPENAI) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        provider=provider,
        temperature=0.7,
        timeout_seconds=10.0,
    )


def _make_registry(*specs: ModelSpec, task: ModelTask = ModelTask.RESPONSE_GENERATION) -> ModelRegistry:
    """Build a registry with a single task → chain mapping."""
    spec_list = list(specs) if specs else [_make_spec()]
    reg = ModelRegistry()
    reg.register_many(spec_list)
    primary = spec_list[0]
    fallbacks = [s.model_id for s in spec_list[1:]]
    reg.set_task_route(task, primary=primary.model_id, fallbacks=fallbacks or None)
    return reg


def _make_gateway(registry: ModelRegistry | None = None, cb: CircuitBreaker | None = None) -> ModelGateway:
    """Create a gateway with mocked Langfuse/LiteLLM setup."""
    with patch.object(ModelGateway, "_init_langfuse_client", return_value=None), \
         patch.object(ModelGateway, "_setup_litellm"):
        return ModelGateway(
            registry=registry or _make_registry(),
            circuit_breaker=cb or CircuitBreaker(),
        )


def _mock_litellm_response(content: str = "Hello", input_tokens: int = 10, output_tokens: int = 5):
    """Build a mock LiteLLM response object."""
    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens
    usage.prompt_tokens_details = None

    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = None

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _mock_litellm_tool_response(tool_name: str = "look_up", args: str = '{"query": "glucose"}'):
    """Build a mock LiteLLM response with tool calls."""
    tc = MagicMock()
    tc.id = "call_123"
    tc.function.name = tool_name
    tc.function.arguments = args

    choice = MagicMock()
    choice.message.content = None
    choice.message.tool_calls = [tc]

    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.prompt_tokens_details = None

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


async def _mock_stream_chunks(*deltas: str):
    """Async generator that yields mock stream chunks."""
    for d in deltas:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = d
        chunk.usage = None
        yield chunk
    # Final chunk with usage
    final = MagicMock()
    final.choices = []
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = len(deltas)
    usage.prompt_tokens_details = None
    final.usage = usage
    yield final


# ---------------------------------------------------------------------------
# safe_cost
# ---------------------------------------------------------------------------

class TestSafeCost:
    def test_extracts_cost(self):
        obj = MagicMock()
        obj.usage.cost.total_cost = 0.05
        assert safe_cost(obj) == 0.05

    def test_returns_zero_on_none(self):
        assert safe_cost(None) == 0.0

    def test_returns_zero_on_missing_attrs(self):
        obj = MagicMock(spec=[])
        assert safe_cost(obj) == 0.0


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------

class TestComplete:
    @pytest.mark.asyncio
    async def test_successful_complete(self):
        gw = _make_gateway()
        mock_resp = _mock_litellm_response("Hello world")

        with patch("litellm.acompletion", return_value=mock_resp):
            result = await gw.complete(
                messages=[{"role": "user", "content": "Hi"}],
                task=ModelTask.RESPONSE_GENERATION,
            )

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello world"

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        primary = _make_spec("primary-model")
        fallback = _make_spec("fallback-model")
        gw = _make_gateway(_make_registry(primary, fallback))

        call_count = 0
        async def mock_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Primary failed")
            return _mock_litellm_response("Fallback response")

        with patch("litellm.acompletion", side_effect=mock_completion):
            result = await gw.complete(
                messages=[{"role": "user", "content": "Hi"}],
                task=ModelTask.RESPONSE_GENERATION,
            )

        assert result.content == "Fallback response"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        gw = _make_gateway()

        with patch("litellm.acompletion", side_effect=Exception("fail")):
            with pytest.raises(AllProvidersUnavailableError):
                await gw.complete(
                    messages=[{"role": "user", "content": "Hi"}],
                    task=ModelTask.RESPONSE_GENERATION,
                )

    @pytest.mark.asyncio
    async def test_circuit_breaker_skips_open(self):
        cb = CircuitBreaker(failure_threshold=1, window_seconds=60, cooldown_seconds=30)
        primary = _make_spec("broken-model")
        fallback = _make_spec("healthy-model")
        gw = _make_gateway(_make_registry(primary, fallback), cb=cb)

        # Trip the circuit for primary
        cb.record_failure(f"{primary.provider.value}:{primary.model_id}")

        with patch("litellm.acompletion", return_value=_mock_litellm_response("OK")):
            result = await gw.complete(
                messages=[{"role": "user", "content": "Hi"}],
                task=ModelTask.RESPONSE_GENERATION,
            )

        assert result.content == "OK"
        # Primary should have been skipped
        stats = cb.get_stats(f"{primary.provider.value}:{primary.model_id}")[0]
        assert stats.state.value != "closed"


# ---------------------------------------------------------------------------
# complete_with_tools()
# ---------------------------------------------------------------------------

class TestCompleteWithTools:
    @pytest.mark.asyncio
    async def test_returns_tool_calls(self):
        gw = _make_gateway(_make_registry(task=ModelTask.CLASSIFICATION))
        mock_resp = _mock_litellm_tool_response("look_up", '{"query": "glucose"}')

        with patch("litellm.acompletion", return_value=mock_resp):
            result = await gw.complete_with_tools(
                messages=[{"role": "user", "content": "Show glucose"}],
                tools=[{"type": "function", "function": {"name": "look_up"}}],
                task=ModelTask.CLASSIFICATION,
            )

        assert isinstance(result, LLMToolResponse)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].function_name == "look_up"
        assert result.tool_calls[0].arguments == {"query": "glucose"}
        assert result.content is None

    @pytest.mark.asyncio
    async def test_handles_malformed_tool_args(self):
        gw = _make_gateway(_make_registry(task=ModelTask.CLASSIFICATION))
        mock_resp = _mock_litellm_tool_response("look_up", "not valid json")

        with patch("litellm.acompletion", return_value=mock_resp):
            result = await gw.complete_with_tools(
                messages=[{"role": "user", "content": "Show glucose"}],
                tools=[{"type": "function", "function": {"name": "look_up"}}],
                task=ModelTask.CLASSIFICATION,
            )

        assert result.tool_calls[0].arguments == {}


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------

class TestStream:
    @pytest.mark.asyncio
    async def test_successful_stream(self):
        gw = _make_gateway()

        with patch("litellm.acompletion", return_value=_mock_stream_chunks("Hello", " world")):
            chunks = []
            async for chunk in gw.stream(
                messages=[{"role": "user", "content": "Hi"}],
                task=ModelTask.RESPONSE_GENERATION,
            ):
                chunks.append(chunk)

        deltas = [c.delta for c in chunks if c.delta]
        assert deltas == ["Hello", " world"]
        assert chunks[-1].finished is True

    @pytest.mark.asyncio
    async def test_fallback_when_no_tokens_yielded(self):
        """If stream fails before any tokens, should fallback to next model."""
        primary = _make_spec("primary-model")
        fallback = _make_spec("fallback-model")
        gw = _make_gateway(_make_registry(primary, fallback))

        call_count = 0
        async def mock_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection failed")
            return _mock_stream_chunks("OK")

        with patch("litellm.acompletion", side_effect=mock_completion):
            chunks = []
            async for chunk in gw.stream(
                messages=[{"role": "user", "content": "Hi"}],
                task=ModelTask.RESPONSE_GENERATION,
            ):
                chunks.append(chunk)

        deltas = [c.delta for c in chunks if c.delta]
        assert "OK" in deltas
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_fallback_after_partial_output(self):
        """If stream fails after yielding tokens, should NOT fallback (raises instead)."""
        primary = _make_spec("primary-model")
        fallback = _make_spec("fallback-model")
        gw = _make_gateway(_make_registry(primary, fallback))

        async def _failing_stream(*args, **kwargs):
            """Yields one chunk then raises."""
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = "Partial"
            chunk.usage = None
            yield chunk
            raise Exception("Stream died mid-response")

        with patch("litellm.acompletion", return_value=_failing_stream()):
            chunks = []
            with pytest.raises(Exception, match="Stream died mid-response"):
                async for chunk in gw.stream(
                    messages=[{"role": "user", "content": "Hi"}],
                    task=ModelTask.RESPONSE_GENERATION,
                ):
                    chunks.append(chunk)

        # Should have received the partial chunk before the error
        assert any(c.delta == "Partial" for c in chunks)

    @pytest.mark.asyncio
    async def test_all_streams_fail(self):
        gw = _make_gateway()

        async def _fail_immediately(**kwargs):
            raise Exception("Connection refused")

        with patch("litellm.acompletion", side_effect=_fail_immediately):
            with pytest.raises(AllProvidersUnavailableError):
                async for _ in gw.stream(
                    messages=[{"role": "user", "content": "Hi"}],
                    task=ModelTask.RESPONSE_GENERATION,
                ):
                    pass


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

class TestCostTracking:
    @pytest.mark.asyncio
    async def test_complete_tracks_usage(self):
        gw = _make_gateway()
        mock_resp = _mock_litellm_response("Hi", input_tokens=100, output_tokens=50)

        with patch("litellm.acompletion", return_value=mock_resp):
            result = await gw.complete(
                messages=[{"role": "user", "content": "Hi"}],
                task=ModelTask.RESPONSE_GENERATION,
            )

        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50


# ---------------------------------------------------------------------------
# Circuit breaker integration
# ---------------------------------------------------------------------------

class TestCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_failure_records_to_circuit_breaker(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=60, cooldown_seconds=1)
        spec = _make_spec("test-model")
        gw = _make_gateway(_make_registry(spec), cb=cb)
        circuit_key = f"{spec.provider.value}:{spec.model_id}"

        with patch("litellm.acompletion", side_effect=Exception("fail")):
            with pytest.raises(AllProvidersUnavailableError):
                await gw.complete(
                    messages=[{"role": "user", "content": "Hi"}],
                    task=ModelTask.RESPONSE_GENERATION,
                )

        stats = cb.get_stats(circuit_key)[0]
        assert stats.failure_count >= 1

    @pytest.mark.asyncio
    async def test_success_records_to_circuit_breaker(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=60, cooldown_seconds=1)
        spec = _make_spec("test-model")
        gw = _make_gateway(_make_registry(spec), cb=cb)
        circuit_key = f"{spec.provider.value}:{spec.model_id}"

        with patch("litellm.acompletion", return_value=_mock_litellm_response("OK")):
            await gw.complete(
                messages=[{"role": "user", "content": "Hi"}],
                task=ModelTask.RESPONSE_GENERATION,
            )

        stats = cb.get_stats(circuit_key)[0]
        assert stats.success_count >= 1
