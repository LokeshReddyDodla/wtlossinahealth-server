"""
Base Agent — foundation base class with all shared services injected.

All agents built on the foundation extend ``BaseAgent`` to get automatic
access to the model gateway, memory, prompts, retrieval, tracing, events,
and streaming. This eliminates boilerplate and ensures consistent behaviour.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from .state import AgentInput, AgentOutput

if TYPE_CHECKING:
    from lib.ai_foundation.events.bus import EventBus
    from lib.ai_foundation.eval.trace import TraceCollector
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway
    from lib.ai_foundation.prompts.registry import PromptRegistry
    from lib.ai_foundation.retrieval.composite import CompositeRetriever

logger = logging.getLogger(__name__)


class BaseAgent:
    """Foundation base class for all AI agents.

    Subclasses must:
    1. Set ``agent_id`` as a class attribute.
    2. Implement ``run()`` for non-streaming execution.
    3. Optionally implement ``run_stream()`` for SSE streaming.

    Example::

        class HealthQueryAgent(BaseAgent):
            agent_id = "health_query_v2"

            async def run(self, input: AgentInput) -> AgentOutput:
                # Use self.gateway, self.memory, self.prompts, etc.
                intent, meta = await self.gateway.extract(
                    messages=[...],
                    response_model=QueryIntent,
                    task=ModelTask.INTENT_EXTRACTION,
                )
                ...
                return AgentOutput(message="Your glucose was...", trace_id=meta.trace_id)

            async def run_stream(self, input: AgentInput) -> AsyncIterator[str]:
                # Yield SSE events
                yield sse_status("extracting_intent")
                ...
    """

    agent_id: str = "base"

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        memory: MemoryStore | None = None,
        prompts: PromptRegistry | None = None,
        retriever: CompositeRetriever | None = None,
        tracer: TraceCollector | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.gateway = gateway
        self.memory = memory
        self.prompts = prompts
        self.retriever = retriever
        self.tracer = tracer
        self.event_bus = event_bus

    async def run(self, input: AgentInput) -> AgentOutput:
        """Execute the agent pipeline and return a complete response.

        Subclasses must implement this method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run()"
        )

    async def run_stream(self, input: AgentInput) -> AsyncIterator[str]:
        """Execute the agent pipeline and yield SSE events.

        Default implementation calls ``run()`` and wraps the result
        as SSE events. Subclasses can override for true streaming.
        """
        from lib.ai_foundation.streaming.sse import (
            sse_done,
            sse_error,
            sse_status,
            sse_token,
            SSEDonePayload,
            PipelineStage,
        )

        try:
            yield sse_status(PipelineStage.GENERATING_RESPONSE)
            output = await self.run(input)
            yield sse_token(output.message)
            yield sse_done(SSEDonePayload(
                trace_id=output.trace_id,
                cost_usd=output.cost_usd,
                latency_ms=output.latency_ms,
                model_id=output.model_id,
                suggestions=output.suggestions,
            ))
        except Exception as exc:
            logger.exception("Agent %s stream error: %s", self.agent_id, exc)
            yield sse_error(
                message="An error occurred while processing your request.",
                code="agent_error",
            )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(agent_id={self.agent_id!r})"
