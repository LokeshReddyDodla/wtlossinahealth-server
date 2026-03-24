"""
Metrics Collector — aggregates per-agent, per-model performance metrics.

Processes completed Traces into queryable metric summaries for dashboards,
alerting, and capacity planning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore
    from lib.ai_foundation.eval.trace import Trace

logger = logging.getLogger(__name__)

METRICS_COLLECTION = "ai_agent_metrics"


class ModelMetrics(BaseModel):
    """Per-model metrics within an agent summary."""

    model_config = {"protected_namespaces": ()}

    model_id: str
    call_count: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    error_count: int = 0


class AgentMetrics(BaseModel):
    """Aggregated metrics for an agent over a time window."""

    agent_id: str
    window_start: datetime
    window_end: datetime
    request_count: int = 0
    total_cost_usd: float = 0.0
    avg_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_first_token_ms: float | None = None
    cache_hit_rate: float = 0.0
    error_rate: float = 0.0
    by_model: dict[str, ModelMetrics] = Field(default_factory=dict)


class MetricsCollector:
    """Records per-request metrics and produces aggregate summaries.

    Stores raw metric events in MongoDB for historical analysis.
    In-memory counters provide fast access for recent metrics.

    Example::

        metrics = MetricsCollector(mongo_store)
        await metrics.record_request(trace)

        summary = await metrics.get_summary("health_query_v2", window_hours=24)
        print(f"Avg latency: {summary.avg_latency_ms}ms, Cost: ${summary.total_cost_usd}")
    """

    def __init__(self, mongo_store: MongoStore | None = None) -> None:
        self._mongo = mongo_store
        # In-memory ring buffer for fast recent metrics
        self._recent: list[dict[str, Any]] = []
        self._max_recent = 1000

    async def record_request(self, trace: Trace) -> None:
        """Record metrics from a completed trace."""
        event = {
            "agent_id": trace.agent_id,
            "trace_id": trace.trace_id,
            "latency_ms": trace.total_latency_ms,
            "cost_usd": trace.total_cost_usd,
            "first_token_ms": trace.first_token_ms,
            "span_count": len(trace.spans),
            "has_error": any(s.error for s in trace.spans),
            "cache_hits": sum(1 for s in trace.spans if s.cache_hit),
            "total_spans": len(trace.spans),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "models_used": list({s.model_id for s in trace.spans if s.model_id}),
        }

        # In-memory buffer
        self._recent.append(event)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]

        # Persist
        if self._mongo:
            try:
                collection = self._mongo.get_collection(METRICS_COLLECTION)
                await collection.insert_one(event)
            except Exception as exc:
                logger.warning("Failed to persist metrics: %s", exc)

    def get_recent_summary(self, agent_id: str | None = None) -> dict[str, Any]:
        """Fast in-memory summary from recent requests."""
        events = self._recent
        if agent_id:
            events = [e for e in events if e.get("agent_id") == agent_id]

        if not events:
            return {"request_count": 0}

        latencies = [e["latency_ms"] for e in events]
        costs = [e["cost_usd"] for e in events]
        errors = sum(1 for e in events if e["has_error"])
        cache_hits = sum(e.get("cache_hits", 0) for e in events)
        total_spans = sum(e.get("total_spans", 0) for e in events)

        return {
            "request_count": len(events),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
            "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1),
            "total_cost_usd": round(sum(costs), 4),
            "avg_cost_usd": round(sum(costs) / len(costs), 6),
            "error_rate": round(errors / len(events), 4),
            "cache_hit_rate": round(cache_hits / total_spans, 4) if total_spans else 0.0,
        }
