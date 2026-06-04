"""
Product Bot Agent — public-facing chatbot for the AI Health marketing website.

Answers visitor questions about the product, grounded in real shipped
capabilities. Uses the full ai_foundation stack: ModelGateway (LiteLLM +
circuit breaker + fallback chains), PromptRegistry (Langfuse-first),
SSE streaming, and Langfuse tracing.

Conversation history is stored ephemerally in Redis (30-min TTL, max 10 turns).
Every exchange is also persisted to MongoDB for analytics (what visitors ask,
common questions, bot quality).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator
from uuid import uuid4

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    SSEDonePayload,
    sse_done,
    sse_error,
    sse_status,
    sse_token,
)

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

    from lib.core.cache_store import CacheStore

logger = logging.getLogger(__name__)

_SESSION_TTL = 1800
_MAX_TURNS = 10
_MAX_TOKENS = 800
_TEMPERATURE = 0.4
_STREAM_TIMEOUT = 30
_HISTORY_KEY_PREFIX = "session"

_DEFAULT_SUGGESTIONS = [
    {"label": "What makes this different?", "value": "What makes AI Health different from other health apps?"},
    {"label": "How does it help patients?", "value": "How does AI Health help someone managing diabetes day to day?"},
    {"label": "Show me the provider side", "value": "What does the provider dashboard look like?"},
]


async def _maybe_await(result: Any) -> Any:
    if asyncio.iscoroutine(result):
        return await result
    return result


class ProductBotAgent(BaseAgent):
    agent_id = "product_bot"

    def __init__(
        self,
        *,
        gateway,
        memory=None,
        prompts=None,
        event_bus=None,
        cache_store: CacheStore,
        analytics_collection: AsyncIOMotorCollection | None = None,
    ) -> None:
        super().__init__(
            gateway=gateway,
            memory=memory,
            prompts=prompts,
            event_bus=event_bus,
        )
        self._cache = cache_store
        self._analytics = analytics_collection

    # -- Tracing + history (single Redis read) --------------------------------

    async def _init_pipeline(
        self, input: AgentInput
    ) -> tuple[str, str, list[dict[str, str]]]:
        """Set up Langfuse tracing and load history in one pass."""
        session_id = input.context.thread_id or str(uuid4())
        trace_id = f"trc_{uuid4().hex[:16]}"
        history = self._load_history(session_id)

        await _maybe_await(self.gateway.set_langfuse_context(
            session_id=session_id,
            user_id=f"anon:{session_id[:8]}",
        ))
        await _maybe_await(self.gateway.langfuse_trace_input(
            trace_id=trace_id,
            name="product_bot",
            input_text=input.message,
            metadata={
                "session_id": session_id,
                "turn": len(history) // 2 + 1,
            },
        ))
        return session_id, trace_id, history

    # -- Public API -----------------------------------------------------------

    async def run(self, input: AgentInput) -> AgentOutput:
        start = time.perf_counter()
        session_id, trace_id, history = await self._init_pipeline(input)

        if len(history) // 2 >= _MAX_TURNS:
            return AgentOutput(
                message="This session has reached its limit. Please refresh the page to start a new conversation.",
                trace_id=trace_id,
            )

        messages = self._build_messages(input.message, history)

        response = await self.gateway.complete(
            messages=messages,
            task=ModelTask.PRODUCT_BOT,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
            trace_id=trace_id,
        )

        self._append_history(session_id, input.message, response.content)

        latency_ms = int((time.perf_counter() - start) * 1000)
        cost_usd = response.cost.total_cost if response.cost else None

        await _maybe_await(self.gateway.langfuse_trace_output(
            trace_id=trace_id,
            output_text=response.content,
            metadata={"model_id": response.model_id, "latency_ms": latency_ms, "cost_usd": cost_usd},
        ))

        asyncio.ensure_future(self._save_exchange(
            session_id=session_id,
            user_message=input.message,
            bot_response=response.content,
            trace_id=trace_id,
            model_id=response.model_id,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            turn=len(history) // 2 + 1,
            ip=input.context.metadata.get("ip") if input.context.metadata else None,
        ))

        return AgentOutput(
            message=response.content,
            trace_id=trace_id,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            model_id=response.model_id,
            suggestions=_DEFAULT_SUGGESTIONS,
            data={"source": "product_bot", "model_id": response.model_id},
        )

    async def run_stream(self, input: AgentInput) -> AsyncIterator[str]:
        start = time.perf_counter()

        try:
            session_id, trace_id, history = await self._init_pipeline(input)
        except Exception as exc:
            logger.exception("ProductBot init failed: %s", exc)
            yield sse_error(
                message="Something went wrong. Please try again.",
                code="init_error",
            )
            return

        if len(history) // 2 >= _MAX_TURNS:
            yield sse_token(
                "This session has reached its limit. "
                "Please refresh the page to start a new conversation."
            )
            yield sse_done(SSEDonePayload(trace_id=trace_id))
            return

        messages = self._build_messages(input.message, history)
        yield sse_status("generating_response")

        try:
            full_response: list[str] = []
            cost_usd: float | None = None

            async with asyncio.timeout(_STREAM_TIMEOUT):
                async for chunk in self.gateway.stream(
                    messages=messages,
                    task=ModelTask.PRODUCT_BOT,
                    temperature=_TEMPERATURE,
                    max_tokens=_MAX_TOKENS,
                    trace_id=trace_id,
                ):
                    if chunk.delta:
                        yield sse_token(chunk.delta)
                        full_response.append(chunk.delta)
                    if chunk.finished and chunk.usage and chunk.usage.cost:
                        cost_usd = chunk.usage.cost.total_cost

            response_text = "".join(full_response)
            self._append_history(session_id, input.message, response_text)

            latency_ms = int((time.perf_counter() - start) * 1000)
            primary_model = self.gateway.registry.route(ModelTask.PRODUCT_BOT).model_id

            await _maybe_await(self.gateway.langfuse_trace_output(
                trace_id=trace_id,
                output_text=response_text,
                metadata={"model_id": primary_model, "latency_ms": latency_ms, "cost_usd": cost_usd},
            ))

            asyncio.ensure_future(self._save_exchange(
                session_id=session_id,
                user_message=input.message,
                bot_response=response_text,
                trace_id=trace_id,
                model_id=primary_model,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                turn=len(history) // 2 + 1,
                ip=input.context.metadata.get("ip") if input.context.metadata else None,
            ))

            yield sse_done(SSEDonePayload(
                trace_id=trace_id,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                model_id=primary_model,
                suggestions=_DEFAULT_SUGGESTIONS,
            ))

        except asyncio.TimeoutError:
            elapsed = int((time.perf_counter() - start) * 1000)
            logger.error("ProductBot stream timed out after %dms", elapsed)
            yield sse_error(
                message="This is taking longer than expected. Please try again.",
                code="stream_timeout",
            )
        except Exception as exc:
            logger.exception("ProductBot stream error: %s", exc)
            yield sse_error(
                message="Something went wrong. Please try again.",
                code="product_bot_error",
            )

    # -- Internals ------------------------------------------------------------

    def _get_system_prompt(self) -> str:
        if self.prompts:
            try:
                template = self.prompts.get("product_bot_system")
                return template.body
            except Exception:
                logger.warning("Failed to load product_bot_system prompt from registry")
        return _FALLBACK_SYSTEM_PROMPT

    def _build_messages(
        self, user_message: str, history: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self._get_system_prompt()},
            *history,
            {"role": "user", "content": user_message},
        ]

    def _load_history(self, session_id: str) -> list[dict[str, str]]:
        key = f"{_HISTORY_KEY_PREFIX}:{session_id}"
        try:
            raw = self._cache.get_key(key)
            if raw:
                return json.loads(raw)
        except Exception:
            logger.debug("Failed to load history for session %s", session_id)
        return []

    async def _save_exchange(
        self,
        *,
        session_id: str,
        user_message: str,
        bot_response: str,
        trace_id: str,
        model_id: str | None = None,
        latency_ms: int | None = None,
        cost_usd: float | None = None,
        turn: int = 1,
        ip: str | None = None,
    ) -> None:
        if not self._analytics:
            return
        try:
            doc: dict[str, Any] = {
                "session_id": session_id,
                "turn": turn,
                "user_message": user_message,
                "bot_response": bot_response,
                "trace_id": trace_id,
                "model_id": model_id,
                "latency_ms": latency_ms,
                "cost_usd": cost_usd,
                "created_at": datetime.now(timezone.utc),
            }
            if ip:
                doc["ip_hash"] = hashlib.sha256(ip.encode()).hexdigest()[:16]
            await self._analytics.insert_one(doc)
        except Exception:
            logger.debug("Failed to save product bot exchange for session %s", session_id)

    def _append_history(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        key = f"{_HISTORY_KEY_PREFIX}:{session_id}"
        history = self._load_history(session_id)
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})

        if len(history) > _MAX_TURNS * 2:
            history = history[-_MAX_TURNS * 2 :]

        try:
            self._cache.set_key(key, json.dumps(history), expire=_SESSION_TTL)
        except Exception:
            logger.warning("Failed to save history for session %s", session_id)


_FALLBACK_SYSTEM_PROMPT = (
    "You are the AI Health product assistant. Answer questions about the "
    "AI Health platform — a precision health platform for diabetes and "
    "metabolic health management. Be confident, direct, and concise. "
    "Never fabricate stats or user counts. Never give medical advice."
)
