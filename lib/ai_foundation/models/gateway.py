"""
Model Gateway — unified async interface for all LLM calls.

Every LLM interaction in the platform goes through this gateway, which provides:
- Three calling modes: complete (full), extract (structured), stream (token-by-token)
- Automatic model routing via ModelRegistry
- Fallback chain execution via CircuitBreaker
- Cost tracking via PricingCalculator
- Automatic data capture for training (via optional TraceCollector / FinetuneDataCollector)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    TypeVar,
)
from uuid import uuid4

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .circuit_breaker import CircuitBreaker
from .pricing import CostBreakdown, PricingCalculator, TokenUsage
from .registry import (
    ModelGatewayError,
    ModelProvider,
    ModelRegistry,
    ModelSpec,
    ModelTask,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LLMUsage(BaseModel):
    """Token usage and cost for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost: CostBreakdown = Field(default_factory=lambda: CostBreakdown())


class LLMResponse(BaseModel):
    """Standardised response from any LLM call."""

    model_config = {"protected_namespaces": ()}

    content: str = ""
    model_id: str = ""
    provider: str = ""
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: int = 0
    trace_id: str | None = None


class StreamChunk(BaseModel):
    """A single chunk yielded during streaming."""

    delta: str = ""
    finished: bool = False
    full_content: str | None = None
    usage: LLMUsage | None = None


class AllProvidersUnavailableError(ModelGatewayError):
    """Raised when all models in the fallback chain have failed."""


# ---------------------------------------------------------------------------
# Provider client factory
# ---------------------------------------------------------------------------


class _ProviderClients:
    """Lazily creates and caches async provider clients."""

    def __init__(self, api_keys: dict[str, str] | None = None) -> None:
        self._api_keys = api_keys or {}
        self._clients: dict[str, Any] = {}

    def get_openai(self, api_key: str | None = None) -> AsyncOpenAI:
        key = api_key or self._api_keys.get("openai", "")
        cache_key = f"openai:{key[:8]}"
        if cache_key not in self._clients:
            self._clients[cache_key] = AsyncOpenAI(api_key=key)
        return self._clients[cache_key]

    def get_instructor(self, api_key: str | None = None) -> instructor.AsyncInstructor:
        key = api_key or self._api_keys.get("openai", "")
        cache_key = f"instructor:{key[:8]}"
        if cache_key not in self._clients:
            self._clients[cache_key] = instructor.from_openai(
                AsyncOpenAI(api_key=key)
            )
        return self._clients[cache_key]


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class ModelGateway:
    """Unified async interface for all LLM calls.

    Example::

        gateway = ModelGateway(registry=build_default_registry(), api_keys={"openai": "sk-..."})

        # Full response
        response = await gateway.complete(
            messages=[{"role": "user", "content": "Hello"}],
            task=ModelTask.RESPONSE_GENERATION,
        )

        # Structured extraction
        intent, meta = await gateway.extract(
            messages=[{"role": "user", "content": "Show me my glucose"}],
            response_model=QueryIntent,
            task=ModelTask.INTENT_EXTRACTION,
        )

        # Streaming
        async for chunk in gateway.stream(
            messages=[{"role": "user", "content": "Summarize my week"}],
            task=ModelTask.RESPONSE_GENERATION,
        ):
            print(chunk.delta, end="")
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        api_keys: dict[str, str] | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._registry = registry
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._clients = _ProviderClients(api_keys)

    # -- Public API ---------------------------------------------------------

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        task: ModelTask = ModelTask.RESPONSE_GENERATION,
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
    ) -> LLMResponse:
        """Send messages and receive a complete text response.

        Tries the primary model first, then walks the fallback chain on failure.
        """
        trace_id = trace_id or str(uuid4())
        chain = self._resolve_chain(task, model_id)

        last_error: Exception | None = None
        for spec in chain:
            if not self._circuit_breaker.is_available(spec.provider.value):
                logger.debug("Skipping %s — circuit open for %s", spec.model_id, spec.provider.value)
                continue

            effective_spec = self._apply_overrides(spec, temperature, max_tokens, timeout)
            try:
                return await self._do_complete(effective_spec, messages, trace_id)
            except Exception as exc:
                last_error = exc
                self._circuit_breaker.record_failure(spec.provider.value)
                logger.warning(
                    "ModelGateway.complete failed for %s: %s", spec.model_id, exc
                )

        raise AllProvidersUnavailableError(
            f"All models failed for task {task.value!r}. Last error: {last_error}"
        )

    async def extract(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[T],
        task: ModelTask = ModelTask.INTENT_EXTRACTION,
        model_id: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
    ) -> tuple[T, LLMResponse]:
        """Send messages and receive a structured Pydantic model via Instructor.

        Returns a tuple of (parsed_model, llm_response_metadata).
        """
        trace_id = trace_id or str(uuid4())
        chain = self._resolve_chain(task, model_id)

        last_error: Exception | None = None
        for spec in chain:
            if not self._circuit_breaker.is_available(spec.provider.value):
                continue

            effective_spec = self._apply_overrides(spec, temperature, None, timeout)
            try:
                return await self._do_extract(
                    effective_spec, messages, response_model, trace_id
                )
            except Exception as exc:
                last_error = exc
                self._circuit_breaker.record_failure(spec.provider.value)
                logger.warning(
                    "ModelGateway.extract failed for %s: %s", spec.model_id, exc
                )

        raise AllProvidersUnavailableError(
            f"All models failed for task {task.value!r}. Last error: {last_error}"
        )

    async def stream(
        self,
        *,
        messages: list[dict[str, str]],
        task: ModelTask = ModelTask.RESPONSE_GENERATION,
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Send messages and yield response tokens as they arrive.

        Tries the primary model first. On failure, falls back and restarts
        streaming from the fallback model (does NOT resume mid-stream).
        """
        trace_id = trace_id or str(uuid4())
        chain = self._resolve_chain(task, model_id)

        last_error: Exception | None = None
        for spec in chain:
            if not self._circuit_breaker.is_available(spec.provider.value):
                continue

            effective_spec = self._apply_overrides(spec, temperature, max_tokens, timeout)
            try:
                async for chunk in self._do_stream(effective_spec, messages, trace_id):
                    yield chunk
                return  # stream completed successfully
            except Exception as exc:
                last_error = exc
                self._circuit_breaker.record_failure(spec.provider.value)
                logger.warning(
                    "ModelGateway.stream failed for %s: %s", spec.model_id, exc
                )

        raise AllProvidersUnavailableError(
            f"All models failed for task {task.value!r}. Last error: {last_error}"
        )

    # -- Accessors ----------------------------------------------------------

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._circuit_breaker

    # -- Internal: resolution -----------------------------------------------

    def _resolve_chain(
        self, task: ModelTask, model_id: str | None
    ) -> list[ModelSpec]:
        """Get the ordered list of models to try."""
        if model_id:
            return [self._registry.get(model_id)]
        return self._registry.get_fallback_chain(task)

    def _apply_overrides(
        self,
        spec: ModelSpec,
        temperature: float | None,
        max_tokens: int | None,
        timeout: float | None,
    ) -> ModelSpec:
        overrides: dict[str, Any] = {}
        if temperature is not None:
            overrides["temperature"] = temperature
        if max_tokens is not None:
            overrides["max_tokens"] = max_tokens
        if timeout is not None:
            overrides["timeout_seconds"] = timeout
        return spec.with_overrides(**overrides) if overrides else spec

    # -- Internal: OpenAI complete ------------------------------------------

    async def _do_complete(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        trace_id: str,
    ) -> LLMResponse:
        client = self._get_async_client(spec)
        start = time.perf_counter()

        kwargs: dict[str, Any] = {
            "model": spec.model_id,
            "messages": messages,
            "temperature": spec.temperature,
        }
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens

        raw = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=spec.timeout_seconds,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        content = raw.choices[0].message.content or "" if raw.choices else ""

        usage = self._extract_usage(raw, spec)
        self._circuit_breaker.record_success(spec.provider.value)

        return LLMResponse(
            content=content,
            model_id=spec.model_id,
            provider=spec.provider.value,
            usage=usage,
            latency_ms=elapsed_ms,
            trace_id=trace_id,
        )

    # -- Internal: OpenAI extract (Instructor) ------------------------------

    async def _do_extract(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        response_model: type[T],
        trace_id: str,
    ) -> tuple[T, LLMResponse]:
        client = self._get_instructor_client(spec)
        start = time.perf_counter()

        raw_response_holder: dict[str, Any] = {}

        parsed, raw = await asyncio.wait_for(
            client.chat.completions.create_with_completion(
                model=spec.model_id,
                response_model=response_model,
                messages=messages,
                temperature=spec.temperature,
            ),
            timeout=spec.timeout_seconds,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        content = raw.choices[0].message.content or "" if raw.choices else ""

        usage = self._extract_usage(raw, spec)
        self._circuit_breaker.record_success(spec.provider.value)

        meta = LLMResponse(
            content=content,
            model_id=spec.model_id,
            provider=spec.provider.value,
            usage=usage,
            latency_ms=elapsed_ms,
            trace_id=trace_id,
        )
        return parsed, meta

    # -- Internal: OpenAI stream -------------------------------------------

    async def _do_stream(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        trace_id: str,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_async_client(spec)
        start = time.perf_counter()

        kwargs: dict[str, Any] = {
            "model": spec.model_id,
            "messages": messages,
            "temperature": spec.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens

        stream = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=spec.timeout_seconds,
        )

        full_content: list[str] = []
        final_usage: TokenUsage | None = None

        async for chunk in stream:
            # Usage comes in the final chunk
            if chunk.usage:
                final_usage = TokenUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                    cached_tokens=getattr(
                        getattr(chunk.usage, "prompt_tokens_details", None),
                        "cached_tokens",
                        0,
                    ) or 0,
                )

            if chunk.choices:
                delta = chunk.choices[0].delta
                text = delta.content if delta and delta.content else ""
                if text:
                    full_content.append(text)
                    yield StreamChunk(delta=text, finished=False)

        # Final chunk with metadata
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        combined = "".join(full_content)

        llm_usage = LLMUsage()
        if final_usage:
            cost = PricingCalculator.calculate(spec, final_usage)
            llm_usage = LLMUsage(
                input_tokens=final_usage.input_tokens,
                output_tokens=final_usage.output_tokens,
                cached_tokens=final_usage.cached_tokens,
                cost=cost,
            )

        self._circuit_breaker.record_success(spec.provider.value)

        yield StreamChunk(
            delta="",
            finished=True,
            full_content=combined,
            usage=llm_usage,
        )

    # -- Internal: usage extraction -----------------------------------------

    def _extract_usage(self, raw: Any, spec: ModelSpec) -> LLMUsage:
        """Extract token usage and calculate cost from a raw API response."""
        if not hasattr(raw, "usage") or raw.usage is None:
            return LLMUsage()

        cached = 0
        if hasattr(raw.usage, "prompt_tokens_details"):
            details = raw.usage.prompt_tokens_details
            if details and hasattr(details, "cached_tokens"):
                cached = details.cached_tokens or 0

        token_usage = TokenUsage(
            input_tokens=raw.usage.prompt_tokens or 0,
            output_tokens=raw.usage.completion_tokens or 0,
            cached_tokens=cached,
        )
        cost = PricingCalculator.calculate(spec, token_usage)

        return LLMUsage(
            input_tokens=token_usage.input_tokens,
            output_tokens=token_usage.output_tokens,
            cached_tokens=token_usage.cached_tokens,
            cost=cost,
        )

    # -- Internal: client factories -----------------------------------------

    def _get_async_client(self, spec: ModelSpec) -> AsyncOpenAI:
        """Get the appropriate async client for a model spec."""
        if spec.provider == ModelProvider.OPENAI:
            return self._clients.get_openai()
        # Future: add Anthropic, Google, Local providers
        raise ModelGatewayError(
            f"Provider {spec.provider.value!r} is not yet supported for async completion."
        )

    def _get_instructor_client(self, spec: ModelSpec) -> instructor.AsyncInstructor:
        """Get an Instructor-wrapped client for structured extraction."""
        if spec.provider == ModelProvider.OPENAI:
            return self._clients.get_instructor()
        raise ModelGatewayError(
            f"Provider {spec.provider.value!r} is not yet supported for structured extraction."
        )
