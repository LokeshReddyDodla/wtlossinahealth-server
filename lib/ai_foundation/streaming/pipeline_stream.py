"""
Pipeline Stream — orchestrates streaming an entire agent pipeline via SSE.

Emits status events for each stage, streams LLM tokens as they arrive,
and sends a final done event with metadata. Handles errors gracefully
with fallback text.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Awaitable

from .sse import (
    PipelineStage,
    SSEDonePayload,
    sse_done,
    sse_error,
    sse_intent,
    sse_status,
    sse_token,
)

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway, StreamChunk

logger = logging.getLogger(__name__)


class PipelineStream:
    """Manages streaming a full agent pipeline via SSE.

    This is a generic orchestrator. Agents provide callbacks for each stage;
    the pipeline stream handles SSE formatting, timing, and error recovery.

    Example::

        stream = PipelineStream()

        async def run():
            async for event in stream.run(
                intent_fn=my_extract_intent,
                retrieve_fn=my_retrieve_data,
                stream_fn=my_stream_response,
                done_fn=my_build_done_payload,
            ):
                yield event  # feed into StreamingResponse

    Each callback receives the result of the previous stage, enabling
    a clean pipeline: intent → retrieval → streaming response → done.
    """

    async def run(
        self,
        *,
        intent_fn: Callable[[], Awaitable[tuple[dict[str, Any], Any]]],
        retrieve_fn: Callable[[Any], Awaitable[Any]],
        stream_fn: Callable[[Any, Any], AsyncIterator[str]],
        done_fn: Callable[[Any, Any, str], Awaitable[SSEDonePayload]],
        fallback_fn: Callable[[Any, Any], Awaitable[str]] | None = None,
    ) -> AsyncIterator[str]:
        """Run the full pipeline and yield SSE events.

        Args:
            intent_fn: Async callable that returns (intent_dict, intent_object).
                The dict is sent as an SSE intent event; the object is passed downstream.
            retrieve_fn: Async callable that takes the intent_object and returns
                retrieved data (any shape the agent needs).
            stream_fn: Async generator that takes (intent_object, retrieved_data) and
                yields raw text deltas (NOT SSE-formatted).
            done_fn: Async callable that takes (intent_object, retrieved_data, full_text)
                and returns the SSEDonePayload.
            fallback_fn: Optional async callable for deterministic fallback text
                if streaming fails. Takes (intent_object, retrieved_data).

        Yields:
            Formatted SSE event strings.
        """
        pipeline_start = time.perf_counter()
        intent_obj: Any = None
        retrieved_data: Any = None
        full_text_parts: list[str] = []

        try:
            # Stage 1: Intent extraction
            yield sse_status(PipelineStage.EXTRACTING_INTENT, "Analyzing your question...")

            intent_dict, intent_obj = await intent_fn()
            yield sse_intent(intent_dict)

            # Stage 2: Data retrieval
            yield sse_status(PipelineStage.FETCHING_DATA, "Pulling your health data...")

            retrieved_data = await retrieve_fn(intent_obj)

            # Stage 3: Response generation (streaming)
            yield sse_status(
                PipelineStage.GENERATING_RESPONSE, "Generating response..."
            )

            try:
                async for delta in stream_fn(intent_obj, retrieved_data):
                    if delta:
                        full_text_parts.append(delta)
                        yield sse_token(delta)
            except Exception as stream_exc:
                logger.warning("Stream generation failed, trying fallback: %s", stream_exc)
                if fallback_fn:
                    fallback = await fallback_fn(intent_obj, retrieved_data)
                    full_text_parts = [fallback]
                    yield sse_token(fallback)
                else:
                    raise

            # Stage 4: Done
            full_text = "".join(full_text_parts)
            elapsed_ms = int((time.perf_counter() - pipeline_start) * 1000)

            done_payload = await done_fn(intent_obj, retrieved_data, full_text)
            done_payload.latency_ms = elapsed_ms
            yield sse_done(done_payload)

        except Exception as exc:
            logger.exception("Pipeline stream error: %s", exc)
            elapsed_ms = int((time.perf_counter() - pipeline_start) * 1000)
            yield sse_error(
                message="An error occurred while processing your request.",
                code="pipeline_error",
                fallback_text="I'm having trouble right now. Please try again.",
            )
