"""
Model Gateway — unified async interface for all LLM calls.

Every LLM interaction in the platform goes through this gateway, which provides:
- Three calling modes: complete (full), extract (structured), stream (token-by-token)
- Automatic model routing via ModelRegistry
- Fallback chain execution via CircuitBreaker
- Cost tracking via LiteLLM (automatic)
- Observability via Langfuse (generation-level via LiteLLM callbacks, trace-level via Langfuse client)

All provider-specific routing is handled by LiteLLM — no direct OpenAI/Gemini SDK calls.
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
import litellm
from pydantic import BaseModel, Field

from .circuit_breaker import CircuitBreaker
from .pricing import CostBreakdown, TokenUsage
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


class ToolCall(BaseModel):
    """A single tool call requested by the LLM."""

    model_config = {"protected_namespaces": ()}

    id: str = Field(description="Unique tool call ID from the API.")
    function_name: str = Field(description="Name of the function to call.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Parsed arguments.")


class LLMToolResponse(BaseModel):
    """Response from complete_with_tools — either text OR tool calls."""

    model_config = {"protected_namespaces": ()}

    content: str | None = Field(default=None, description="Text response (None if tool calls).")
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Tool calls (empty if text).")
    usage: LLMUsage = Field(default_factory=LLMUsage)
    model_id: str = ""
    provider: str = ""
    latency_ms: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class AllProvidersUnavailableError(ModelGatewayError):
    """Raised when all models in the fallback chain have failed."""


# ---------------------------------------------------------------------------
# LiteLLM model-id helper
# ---------------------------------------------------------------------------


def _litellm_model_id(spec: ModelSpec) -> str:
    """Convert a ModelSpec into the model string LiteLLM expects.

    - OpenAI models: use model_id as-is (e.g. "gpt-4.1-mini")
    - Google Gemini: prefix with "gemini/" (e.g. "gemini/gemini-2.5-flash")
    """
    if spec.provider == ModelProvider.GOOGLE:
        return f"gemini/{spec.model_id}"
    return spec.model_id


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class ModelGateway:
    """Unified async interface for all LLM calls.

    Example::

        gateway = ModelGateway(registry=build_default_registry())

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
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._registry = registry
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._langfuse_client = self._init_langfuse_client()
        self._setup_litellm()

    @staticmethod
    def _init_langfuse_client() -> Any | None:
        """Initialize Langfuse client for trace-level operations only.

        Generation-level logging is handled by LiteLLM callbacks.
        """
        from lib.ai_foundation.config import settings
        if not settings.LANGFUSE_ENABLED:
            logger.info("Langfuse disabled (AI_LANGFUSE_ENABLED=false)")
            return None
        if not settings.LANGFUSE_PUBLIC_KEY:
            logger.warning("Langfuse enabled but AI_LANGFUSE_PUBLIC_KEY is empty")
            return None
        try:
            from langfuse import Langfuse
            client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
            logger.info("Langfuse client initialized → %s", settings.LANGFUSE_HOST)
            return client
        except ImportError:
            logger.warning("langfuse package not installed — run: pip install langfuse")
            return None
        except Exception as exc:
            logger.warning("Langfuse client init failed: %s", exc)
            return None

    @staticmethod
    def _setup_litellm() -> None:
        """Configure LiteLLM callbacks for Langfuse generation-level logging."""
        from lib.ai_foundation.config import settings
        if settings.LANGFUSE_ENABLED:
            litellm.success_callback = ["langfuse"]
            litellm.failure_callback = ["langfuse"]
            logger.info("LiteLLM Langfuse callbacks enabled")
        # Drop unsupported params (e.g., gpt-5 doesn't support temperature=0.0)
        litellm.drop_params = True
        # Suppress LiteLLM's noisy logging
        litellm.set_verbose = False
        logging.getLogger("LiteLLM").setLevel(logging.WARNING)
        logging.getLogger("litellm").setLevel(logging.WARNING)

    # -- Langfuse context (set per-request by the agent) --------------------

    _langfuse_session_id: str | None = None
    _langfuse_user_id: str | None = None

    def set_langfuse_context(self, *, session_id: str | None = None, user_id: str | None = None) -> None:
        """Set session/user context for Langfuse traces. Called once per request."""
        self._langfuse_session_id = session_id
        self._langfuse_user_id = user_id

    def langfuse_trace_input(self, *, trace_id: str, input_text: str, metadata: dict | None = None) -> None:
        """Set the trace-level input (user message). Called at start of request."""
        if not self._langfuse_client:
            return
        try:
            self._langfuse_client.trace(
                id=trace_id,
                input=input_text,
                session_id=self._langfuse_session_id,
                user_id=self._langfuse_user_id,
                metadata=metadata,
            )
        except Exception:
            pass

    def langfuse_trace_output(self, *, trace_id: str, output_text: str) -> None:
        """Set the trace-level output (agent response). Called at end of request."""
        if not self._langfuse_client:
            return
        try:
            self._langfuse_client.trace(id=trace_id, output=output_text)
        except Exception:
            pass

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

    async def complete_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        task: ModelTask = ModelTask.CLASSIFICATION,
        model_id: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
    ) -> LLMToolResponse:
        """Send messages with tool definitions. LLM responds with text OR tool calls.

        This is the core of the agentic reasoning loop. The LLM sees the tools,
        decides whether to call one (or more) or respond directly.
        """
        trace_id = trace_id or str(uuid4())
        chain = self._resolve_chain(task, model_id)

        last_error: Exception | None = None
        for spec in chain:
            if not self._circuit_breaker.is_available(spec.provider.value):
                continue

            effective_spec = self._apply_overrides(spec, temperature, None, timeout)
            try:
                return await self._do_complete_with_tools(
                    effective_spec, messages, tools, trace_id,
                )
            except Exception as exc:
                last_error = exc
                self._circuit_breaker.record_failure(spec.provider.value)
                logger.warning("ModelGateway.complete_with_tools failed for %s: %s", spec.model_id, exc)

        raise AllProvidersUnavailableError(
            f"All models failed for task {task.value!r}. Last error: {last_error}"
        )

    async def _do_complete_with_tools(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        trace_id: str,
    ) -> LLMToolResponse:
        """Internal: execute function calling via LiteLLM."""
        model = _litellm_model_id(spec)
        start = time.perf_counter()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": spec.temperature,
            "tools": tools,
            "metadata": {"trace_id": trace_id},
        }
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens

        raw = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
            timeout=spec.timeout_seconds,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        usage = self._extract_usage(raw, spec)
        self._circuit_breaker.record_success(spec.provider.value)

        choice = raw.choices[0] if raw.choices else None
        if not choice:
            return LLMToolResponse(usage=usage, model_id=spec.model_id, latency_ms=elapsed_ms)

        # Parse tool calls if present
        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            import json as _json
            for tc in choice.message.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                except (ValueError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    function_name=tc.function.name,
                    arguments=args,
                ))

        content = choice.message.content if not tool_calls else None

        return LLMToolResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model_id=spec.model_id,
            provider=spec.provider.value,
            latency_ms=elapsed_ms,
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

    # -- Internal: LiteLLM complete -----------------------------------------

    async def _do_complete(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        trace_id: str,
    ) -> LLMResponse:
        model = _litellm_model_id(spec)
        start = time.perf_counter()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": spec.temperature,
            "metadata": {"trace_id": trace_id},
        }
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens

        raw = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
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

    # -- Internal: LiteLLM extract (Instructor) ----------------------------

    async def _do_extract(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        response_model: type[T],
        trace_id: str,
    ) -> tuple[T, LLMResponse]:
        model = _litellm_model_id(spec)
        start = time.perf_counter()

        client = instructor.from_litellm(litellm.acompletion)

        parsed, raw = await asyncio.wait_for(
            client.chat.completions.create_with_completion(
                model=model,
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

    # -- Internal: LiteLLM stream ------------------------------------------

    async def _do_stream(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        trace_id: str,
    ) -> AsyncIterator[StreamChunk]:
        model = _litellm_model_id(spec)
        start = time.perf_counter()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": spec.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
            "metadata": {"trace_id": trace_id},
        }
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens

        stream = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
            timeout=spec.timeout_seconds,
        )

        full_content: list[str] = []
        final_usage: TokenUsage | None = None

        async for chunk in stream:
            # Usage comes in the final chunk (LiteLLM may not have .usage on every chunk)
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage and getattr(chunk_usage, "prompt_tokens", None) is not None:
                cached = 0
                details = getattr(chunk_usage, "prompt_tokens_details", None)
                if details is not None:
                    cached = getattr(details, "cached_tokens", 0) or 0
                final_usage = TokenUsage(
                    input_tokens=chunk_usage.prompt_tokens or 0,
                    output_tokens=chunk_usage.completion_tokens or 0,
                    cached_tokens=cached,
                )

            if getattr(chunk, "choices", None):
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
            llm_usage = LLMUsage(
                input_tokens=final_usage.input_tokens,
                output_tokens=final_usage.output_tokens,
                cached_tokens=final_usage.cached_tokens,
                cost=CostBreakdown(total_cost=0),
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
        """Extract token usage and cost from a raw LiteLLM response."""
        if not hasattr(raw, "usage") or raw.usage is None:
            return LLMUsage()

        cached = 0
        if hasattr(raw.usage, "prompt_tokens_details"):
            details = raw.usage.prompt_tokens_details
            if details and hasattr(details, "cached_tokens"):
                cached = details.cached_tokens or 0

        # LiteLLM provides cost automatically
        response_cost = 0.0
        if hasattr(raw, "_hidden_params"):
            response_cost = raw._hidden_params.get("response_cost", 0) or 0

        return LLMUsage(
            input_tokens=raw.usage.prompt_tokens or 0,
            output_tokens=raw.usage.completion_tokens or 0,
            cached_tokens=cached,
            cost=CostBreakdown(total_cost=response_cost),
        )

    # -- Langfuse trace-level methods (kept, not generation-level) ----------

    def log_score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """Log a score (user feedback) to Langfuse."""
        if not self._langfuse_client:
            return
        try:
            self._langfuse_client.score(
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment,
            )
        except Exception as exc:
            logger.debug("Langfuse score failed: %s", exc)
