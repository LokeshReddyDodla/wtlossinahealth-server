"""Tests for Retrieval — composite retriever with timeouts and degradation."""

import asyncio

import pytest

from lib.ai_foundation.retrieval.base import (
    CompositeResult,
    RetrievalRequest,
    RetrievalResult,
)
from lib.ai_foundation.retrieval.composite import CompositeRetriever


class _MockRetriever:
    """Simple mock retriever for testing."""

    def __init__(self, name: str, results: list[RetrievalResult] | None = None, delay: float = 0, error: Exception | None = None):
        self.name = name
        self._results = results or []
        self._delay = delay
        self._error = error
        self.call_count = 0

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        self.call_count += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._results


class TestCompositeRetriever:
    def test_register(self, composite_retriever):
        r = _MockRetriever("test")
        composite_retriever.register("test", r, timeout_seconds=5.0)
        assert "test" in composite_retriever
        assert len(composite_retriever.list_sources()) == 1

    @pytest.mark.asyncio
    async def test_retrieve_single_source(self, composite_retriever):
        results = [
            RetrievalResult(payload={"glucose": 145}, source="mock", score=0.9, data_type="cgm"),
        ]
        composite_retriever.register("mock", _MockRetriever("mock", results))

        result = await composite_retriever.retrieve(
            RetrievalRequest(query="test", patient_ids=["p1"]),
        )
        assert len(result.items) == 1
        assert result.items[0].score == 0.9
        assert result.executed_sources == ["mock"]
        assert result.best_score == 0.9

    @pytest.mark.asyncio
    async def test_retrieve_multiple_sources(self, composite_retriever):
        r1 = _MockRetriever("mongo", [
            RetrievalResult(payload={"cal": 500}, source="mongo", data_type="meal"),
        ])
        r2 = _MockRetriever("qdrant", [
            RetrievalResult(payload={"glucose": 180}, source="qdrant", score=0.85, data_type="cgm"),
        ])
        composite_retriever.register("mongo", r1, required=True)
        composite_retriever.register("qdrant", r2, required=False)

        result = await composite_retriever.retrieve(
            RetrievalRequest(query="test"),
        )
        assert len(result.items) == 2
        assert set(result.executed_sources) == {"mongo", "qdrant"}
        assert result.best_score == 0.85

    @pytest.mark.asyncio
    async def test_optional_timeout_degrades(self, composite_retriever):
        fast = _MockRetriever("fast", [
            RetrievalResult(payload={"ok": True}, source="fast"),
        ])
        slow = _MockRetriever("slow", delay=5.0)  # will timeout
        composite_retriever.register("fast", fast, timeout_seconds=5.0, required=False)
        composite_retriever.register("slow", slow, timeout_seconds=0.05, required=False)

        result = await composite_retriever.retrieve(
            RetrievalRequest(query="test"),
        )
        assert "fast" in result.executed_sources
        assert "slow" in result.degraded_sources
        assert len(result.warnings) == 1

    @pytest.mark.asyncio
    async def test_required_failure_raises(self, composite_retriever):
        failing = _MockRetriever("required", error=ConnectionError("db down"))
        composite_retriever.register("required", failing, required=True)

        with pytest.raises(RuntimeError, match="Required retriever"):
            await composite_retriever.retrieve(RetrievalRequest(query="test"))

    @pytest.mark.asyncio
    async def test_filter_sources(self, composite_retriever):
        r1 = _MockRetriever("mongo", [RetrievalResult(payload={}, source="mongo")])
        r2 = _MockRetriever("qdrant", [RetrievalResult(payload={}, source="qdrant")])
        composite_retriever.register("mongo", r1)
        composite_retriever.register("qdrant", r2)

        result = await composite_retriever.retrieve(
            RetrievalRequest(query="test"),
            sources=["mongo"],
        )
        assert result.executed_sources == ["mongo"]
        assert r1.call_count == 1
        assert r2.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_retriever(self, composite_retriever):
        result = await composite_retriever.retrieve(RetrievalRequest(query="test"))
        assert len(result.items) == 0
        assert result.best_score is None

    def test_repr(self, composite_retriever):
        composite_retriever.register("a", _MockRetriever("a"))
        assert "CompositeRetriever" in repr(composite_retriever)
        assert "a" in repr(composite_retriever)
