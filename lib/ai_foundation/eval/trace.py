"""
Trace Collector — span-based pipeline tracing for AI agent runs.

Every agent pipeline run produces a Trace containing Spans for each step
(intent extraction, retrieval, analysis, LLM response). Traces are persisted
to MongoDB for observability, cost analysis, and debugging.

Uses ``contextvars`` for implicit trace propagation within async tasks.
"""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator
from uuid import uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

TRACES_COLLECTION = "ai_traces"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Span(BaseModel):
    """A single timed operation within a pipeline trace."""

    model_config = {"protected_namespaces": ()}

    span_id: str = Field(default_factory=lambda: str(uuid4())[:12])
    trace_id: str = ""
    parent_span_id: str | None = None
    name: str = Field(..., description="Step name, e.g. 'intent_extraction'.")
    agent_id: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    duration_ms: int | None = None
    model_id: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    cache_hit: bool = False
    error: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class Trace(BaseModel):
    """A complete pipeline trace with all its spans."""

    model_config = {"protected_namespaces": ()}

    trace_id: str = Field(default_factory=lambda: f"trc_{uuid4().hex[:16]}")
    agent_id: str = ""
    patient_id_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of patient ID — never the raw value.",
    )
    thread_id: str | None = None
    user_role: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    total_latency_ms: int = 0
    total_cost_usd: float = 0.0
    first_token_ms: int | None = Field(
        default=None, description="Time to first streamed token."
    )
    spans: list[Span] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class TraceCollector:
    """Collects spans during an agent run and persists the trace to MongoDB.

    Example::

        collector = TraceCollector(mongo_store)
        trace = collector.start_trace("health_query_v2", patient_id="p123")

        async with collector.span("intent_extraction") as s:
            result = await extract_intent(...)
            s.model_id = "gpt-4.1-mini"
            s.tokens_in = result.usage.input_tokens
            s.tokens_out = result.usage.output_tokens
            s.cost_usd = result.usage.cost.total_cost

        async with collector.span("qdrant_search") as s:
            results = await search(...)
            s.tags["result_count"] = str(len(results))

        completed = await collector.finish_trace()
        # trace is now persisted in MongoDB 'ai_traces' collection
    """

    def __init__(self, mongo_store: MongoStore | None = None) -> None:
        self._mongo = mongo_store
        self._active_trace: Trace | None = None
        self._pipeline_start: float | None = None

    # -- Trace lifecycle ----------------------------------------------------

    def start_trace(
        self,
        agent_id: str,
        *,
        patient_id: str | None = None,
        thread_id: str | None = None,
        user_role: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Trace:
        """Begin a new trace. Must be called before any ``span()`` calls."""
        self._pipeline_start = time.perf_counter()
        patient_hash = (
            hashlib.sha256(patient_id.encode()).hexdigest()[:16]
            if patient_id
            else None
        )
        self._active_trace = Trace(
            agent_id=agent_id,
            patient_id_hash=patient_hash,
            thread_id=thread_id,
            user_role=user_role,
            metadata=metadata or {},
        )
        return self._active_trace

    @asynccontextmanager
    async def span(self, name: str, **tags: str) -> AsyncIterator[Span]:
        """Context manager that records timing for a pipeline step.

        The yielded ``Span`` object can be mutated to add model_id,
        tokens, cost, etc. Duration is calculated automatically.
        """
        if self._active_trace is None:
            raise RuntimeError("No active trace. Call start_trace() first.")

        s = Span(
            name=name,
            trace_id=self._active_trace.trace_id,
            agent_id=self._active_trace.agent_id,
            tags=dict(tags),
        )
        start = time.perf_counter()

        try:
            yield s
        except Exception as exc:
            s.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed = time.perf_counter() - start
            s.ended_at = datetime.now(timezone.utc)
            s.duration_ms = int(elapsed * 1000)
            self._active_trace.spans.append(s)

    def record_first_token(self) -> None:
        """Call when the first streamed token is yielded."""
        if self._active_trace and self._pipeline_start:
            self._active_trace.first_token_ms = int(
                (time.perf_counter() - self._pipeline_start) * 1000
            )

    async def finish_trace(self) -> Trace:
        """Finalise and persist the trace. Returns the completed Trace."""
        if self._active_trace is None:
            raise RuntimeError("No active trace to finish.")

        trace = self._active_trace
        trace.ended_at = datetime.now(timezone.utc)

        if self._pipeline_start:
            trace.total_latency_ms = int(
                (time.perf_counter() - self._pipeline_start) * 1000
            )

        # Aggregate cost from spans
        trace.total_cost_usd = sum(
            s.cost_usd for s in trace.spans if s.cost_usd
        )

        # Persist
        if self._mongo:
            try:
                collection = self._mongo.get_collection(TRACES_COLLECTION)
                await collection.insert_one(
                    trace.model_dump(mode="json", exclude_none=True)
                )
                logger.debug(
                    "Trace %s persisted (%d spans, %dms, $%.4f)",
                    trace.trace_id,
                    len(trace.spans),
                    trace.total_latency_ms,
                    trace.total_cost_usd,
                )
            except Exception as exc:
                logger.warning("Failed to persist trace %s: %s", trace.trace_id, exc)

        # Reset
        self._active_trace = None
        self._pipeline_start = None
        return trace

    # -- Queries (for dashboards) -------------------------------------------

    async def get_trace(self, trace_id: str) -> dict | None:
        """Retrieve a single trace by ID."""
        if not self._mongo:
            return None
        collection = self._mongo.get_collection(TRACES_COLLECTION)
        return await collection.find_one({"trace_id": trace_id}, {"_id": 0})

    async def get_recent_traces(
        self,
        agent_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieve recent traces, optionally filtered by agent."""
        if not self._mongo:
            return []
        collection = self._mongo.get_collection(TRACES_COLLECTION)
        query: dict = {}
        if agent_id:
            query["agent_id"] = agent_id
        cursor = collection.find(query, {"_id": 0}).sort("started_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    @property
    def active_trace(self) -> Trace | None:
        return self._active_trace
