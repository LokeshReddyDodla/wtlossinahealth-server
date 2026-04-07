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
import contextvars
import json
import logging
import time
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    TypeVar,
)
from uuid import uuid4

import instructor
import litellm
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

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def safe_cost(obj: Any) -> float:
    """Safely extract total_cost from an LLM response or metadata object."""
    try:
        return obj.usage.cost.total_cost if obj and obj.usage and obj.usage.cost else 0.0
    except AttributeError:
        return 0.0


def _circuit_key(spec: ModelSpec) -> str:
    """Scope breaker state to a concrete model so same-provider fallbacks still work."""
    return f"{spec.provider.value}:{spec.model_id}"


def _is_retryable(exc: Exception) -> bool:
    """Check if an error is transient (rate-limit or timeout) and worth a brief delay."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    # LiteLLM wraps provider errors — check status code and message
    status = getattr(exc, "status_code", None)
    if status in (429, 408, 503):
        return True
    msg = str(exc).lower()
    return "rate" in msg and "limit" in msg


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
        # Reuse the Instructor wrapper — constructing it per-call adds avoidable overhead.
        self._instructor_client = instructor.from_litellm(litellm.acompletion)
        self._setup_litellm()

    @staticmethod
    def _init_langfuse_client() -> Any | None:
        """Initialize Langfuse client for trace-level operations only.

        Generation-level logging is handled by LiteLLM callbacks.
        """
        from lib.ai_foundation.config import settings
        if not settings.LANGFUSE_ENABLED:
            logger.info("Langfuse disabled (LANGFUSE_ENABLED=false)")
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

    # -- Langfuse context (set per-request via contextvars for concurrency safety) --

    _langfuse_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("_lf_session", default=None)
    _langfuse_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("_lf_user", default=None)
    _langfuse_trace_name: contextvars.ContextVar[str | None] = contextvars.ContextVar("_lf_trace_name", default=None)
    _langfuse_request_meta: contextvars.ContextVar[dict | None] = contextvars.ContextVar("_lf_req_meta", default=None)

    def set_langfuse_context(self, *, session_id: str | None = None, user_id: str | None = None) -> None:
        """Set session/user context for Langfuse traces. Called once per request."""
        self._langfuse_session_id.set(session_id)
        self._langfuse_user_id.set(user_id)

    def langfuse_trace_input(self, *, trace_id: str, name: str, input_text: str, metadata: dict | None = None) -> None:
        """Set the trace-level input (user message). Called at start of request."""
        self._langfuse_trace_name.set(name)
        self._langfuse_request_meta.set(metadata)
        if not self._langfuse_client:
            return
        try:
            self._langfuse_client.trace(
                id=trace_id,
                name=name,
                input=input_text,
                session_id=self._langfuse_session_id.get(),
                user_id=self._langfuse_user_id.get(),
                metadata={"request": metadata} if metadata else None,
            )
        except Exception as exc:
            logger.debug("Langfuse trace_input failed: %s", exc)

    def langfuse_trace_output(
        self,
        *,
        trace_id: str,
        output_text: str,
        metadata: dict | None = None,
    ) -> None:
        """Set the trace-level output (agent response). Called at end of request.

        Merges request metadata (saved by langfuse_trace_input) with response
        metadata under namespaced keys so neither overwrites the other.
        Langfuse replaces the whole metadata field on upsert, so we must send
        both halves together.
        """
        if not self._langfuse_client:
            return
        try:
            combined: dict | None = None
            request_meta = self._langfuse_request_meta.get()
            if request_meta or metadata:
                combined = {}
                if request_meta:
                    combined["request"] = request_meta
                if metadata:
                    combined["response"] = metadata
            self._langfuse_client.trace(
                id=trace_id,
                output=output_text,
                metadata=combined,
            )
        except Exception as exc:
            logger.debug("Langfuse trace_output failed: %s", exc)

    # -- Token counting & context window ------------------------------------

    @staticmethod
    def _clean_messages(messages: list[dict]) -> list[dict]:
        """Strip internal metadata keys (e.g. _meta) before sending to LLM API."""
        return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]

    def count_tokens(self, messages: list[dict], model: str | None = None) -> int:
        """Count tokens in a message list. Falls back to char/4 estimate.

        Strips internal metadata (_meta) before counting so the result
        matches what the LLM API actually receives.
        """
        clean = self._clean_messages(messages)
        try:
            return litellm.token_counter(model=model or "gpt-4.1-mini", messages=clean)
        except Exception:
            return sum(len(m.get("content", "") or "") for m in clean) // 4

    def get_model_window(self, model: str) -> int:
        """Get context window size with fallback chain: litellm → config override → default."""
        from lib.ai_foundation.config import settings
        try:
            info = litellm.get_model_info(model)
            if info and info.get("max_input_tokens"):
                return info["max_input_tokens"]
        except Exception:
            pass
        return settings.CONTEXT_WINDOW_OVERRIDE.get(model, settings.CONTEXT_WINDOW_DEFAULT)

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
        return await self._with_fallback(
            task=task,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            trace_id=trace_id,
            method_name="ModelGateway.complete",
            call=lambda spec, tid: self._do_complete(spec, messages, tid),
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
        return await self._with_fallback(
            task=task,
            model_id=model_id,
            temperature=temperature,
            max_tokens=None,
            timeout=timeout,
            trace_id=trace_id,
            method_name="ModelGateway.extract",
            call=lambda spec, tid: self._do_extract(spec, messages, response_model, tid),
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
        return await self._with_fallback(
            task=task,
            model_id=model_id,
            temperature=temperature,
            max_tokens=None,
            timeout=timeout,
            trace_id=trace_id,
            method_name="ModelGateway.complete_with_tools",
            call=lambda spec, tid: self._do_complete_with_tools(spec, messages, tools, tid),
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
            "messages": self._clean_messages(messages),
            "temperature": spec.temperature,
            "tools": tools,
            "metadata": self._trace_metadata(trace_id),
        }
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens

        raw = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
            timeout=spec.timeout_seconds,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        usage = self._extract_usage(raw, spec)
        self._circuit_breaker.record_success(_circuit_key(spec))

        choice = raw.choices[0] if raw.choices else None
        if not choice:
            return LLMToolResponse(usage=usage, model_id=spec.model_id, latency_ms=elapsed_ms)

        # Parse tool calls if present
        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = (
                        json.loads(tc.function.arguments)
                        if isinstance(tc.function.arguments, str)
                        else tc.function.arguments
                    )
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

        Tries the primary model first. On failure, falls back to the next model
        ONLY if no tokens were yielded yet. If tokens were already sent to the
        client, re-raises immediately to avoid garbled concatenation.
        """
        trace_id = trace_id or str(uuid4())
        chain = self._resolve_chain(task, model_id)

        last_error: Exception | None = None
        failed_attempts: list[str] = []
        for spec in chain:
            circuit_key = _circuit_key(spec)
            if not self._circuit_breaker.is_available(circuit_key):
                continue

            effective_spec = self._apply_overrides(spec, temperature, max_tokens, timeout)
            tokens_yielded = 0
            try:
                async for chunk in self._do_stream(effective_spec, messages, trace_id):
                    if chunk.delta:
                        tokens_yielded += 1
                    yield chunk
                return  # stream completed successfully
            except Exception as exc:
                self._circuit_breaker.record_failure(circuit_key)
                if tokens_yielded > 0:
                    logger.error(
                        "ModelGateway.stream failed for %s after %d chunks yielded, "
                        "cannot fallback: %s", spec.model_id, tokens_yielded, exc,
                    )
                    raise
                failed_attempts.append(f"{spec.model_id}:{type(exc).__name__}")
                last_error = exc
                logger.warning(
                    "ModelGateway.stream failed for %s (pre-output), falling back: %s",
                    spec.model_id, exc,
                )

        raise AllProvidersUnavailableError(
            f"All stream models failed for task {task.value!r}. "
            f"Attempts: {', '.join(failed_attempts) or 'none (all circuits open)'}. "
            f"Last error: {last_error}"
        )

    # -- Accessors ----------------------------------------------------------

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._circuit_breaker

    # -- Internal: fallback orchestration ------------------------------------

    _R = TypeVar("_R")

    async def _with_fallback(
        self,
        *,
        task: ModelTask,
        model_id: str | None,
        temperature: float | None,
        max_tokens: int | None,
        timeout: float | None,
        trace_id: str | None,
        method_name: str,
        call: Callable[[ModelSpec, str], Awaitable[_R]],
    ) -> _R:
        """Run *call* against each model in the fallback chain until one succeeds.

        Handles: trace_id defaulting, chain resolution, circuit-breaker checks,
        spec overrides, try/except with failure recording, and the terminal
        AllProvidersUnavailableError.

        Parameters
        ----------
        call:
            ``async def(effective_spec, trace_id) -> _R`` — the actual LLM
            invocation (e.g. ``_do_complete``, ``_do_extract`` partial).
        method_name:
            Used only in the warning log so messages stay identical to the
            originals (e.g. ``"ModelGateway.complete"``).
        """
        trace_id = trace_id or str(uuid4())
        chain = self._resolve_chain(task, model_id)

        last_error: Exception | None = None
        failed_attempts: list[str] = []
        for spec in chain:
            circuit_key = _circuit_key(spec)
            if not self._circuit_breaker.is_available(circuit_key):
                logger.debug("Skipping %s — circuit open for %s", spec.model_id, circuit_key)
                continue

            effective_spec = self._apply_overrides(spec, temperature, max_tokens, timeout)
            try:
                return await call(effective_spec, trace_id)
            except Exception as exc:
                last_error = exc
                failed_attempts.append(f"{spec.model_id}:{type(exc).__name__}")
                self._circuit_breaker.record_failure(circuit_key)
                logger.warning(
                    "%s failed for %s: %s", method_name, spec.model_id, exc
                )
                # Brief delay on rate-limit / timeout before trying next provider
                if _is_retryable(exc):
                    await asyncio.sleep(0.5)

        raise AllProvidersUnavailableError(
            f"All models failed for task {task.value!r}. "
            f"Attempts: {', '.join(failed_attempts) or 'none (all circuits open)'}. "
            f"Last error: {last_error}"
        )

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

    def _trace_metadata(self, trace_id: str) -> dict[str, Any]:
        """Build LiteLLM metadata dict with trace_id and optional trace_name/user/session."""
        meta: dict[str, Any] = {"trace_id": trace_id}
        trace_name = self._langfuse_trace_name.get()
        if trace_name:
            meta["trace_name"] = trace_name
        user_id = self._langfuse_user_id.get()
        if user_id:
            meta["trace_user_id"] = user_id
        session_id = self._langfuse_session_id.get()
        if session_id:
            meta["session_id"] = session_id
        return meta

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
            "messages": self._clean_messages(messages),
            "temperature": spec.temperature,
            "metadata": self._trace_metadata(trace_id),
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
        self._circuit_breaker.record_success(_circuit_key(spec))

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

        parsed, raw = await asyncio.wait_for(
            self._instructor_client.chat.completions.create_with_completion(
                model=model,
                response_model=response_model,
                messages=self._clean_messages(messages),
                temperature=spec.temperature,
                metadata=self._trace_metadata(trace_id),
            ),
            timeout=spec.timeout_seconds,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        content = raw.choices[0].message.content or "" if raw.choices else ""

        usage = self._extract_usage(raw, spec)
        self._circuit_breaker.record_success(_circuit_key(spec))

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
            "messages": self._clean_messages(messages),
            "temperature": spec.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
            "metadata": self._trace_metadata(trace_id),
        }
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens

        stream = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
            timeout=spec.timeout_seconds,
        )

        full_content: list[str] = []
        final_usage: TokenUsage | None = None

        # Use remaining budget so total wall-clock never exceeds timeout_seconds
        elapsed = time.perf_counter() - start
        remaining = max(1.0, spec.timeout_seconds - elapsed)
        async with asyncio.timeout(remaining):
            async for chunk in stream:
                # Usage comes in the final chunk (LiteLLM may not have .usage on every chunk)
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    prompt_tokens = getattr(chunk_usage, "prompt_tokens", None)
                    if prompt_tokens is not None:
                        details = getattr(chunk_usage, "prompt_tokens_details", None)
                        cached = getattr(details, "cached_tokens", 0) if details is not None else 0
                        final_usage = TokenUsage(
                            input_tokens=prompt_tokens or 0,
                            output_tokens=getattr(chunk_usage, "completion_tokens", 0) or 0,
                            cached_tokens=cached or 0,
                        )

                choices = getattr(chunk, "choices", None)
                if choices:
                    delta = choices[0].delta
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
                cost=PricingCalculator.calculate(spec, final_usage),
            )

        self._circuit_breaker.record_success(_circuit_key(spec))

        yield StreamChunk(
            delta="",
            finished=True,
            full_content=combined,
            usage=llm_usage,
        )

    # -- Internal: usage extraction -----------------------------------------

    def _extract_usage(self, raw: Any, spec: ModelSpec) -> LLMUsage:
        """Extract token usage and cost from a raw LiteLLM response."""
        usage = getattr(raw, "usage", None)
        if usage is None:
            return LLMUsage()

        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details is not None else 0

        # LiteLLM provides cost automatically
        hidden_params = getattr(raw, "_hidden_params", None)
        response_cost = hidden_params.get("response_cost", 0) if isinstance(hidden_params, dict) else 0.0

        return LLMUsage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cached_tokens=cached or 0,
            cost=CostBreakdown(total_cost=response_cost or 0.0),
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
