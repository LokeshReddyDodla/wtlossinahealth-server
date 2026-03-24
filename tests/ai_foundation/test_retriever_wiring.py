"""Tests for actual retriever implementations — QdrantRetriever + MongoReportRetriever."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from lib.ai_foundation.retrieval.base import RetrievalRequest, RetrievalResult
from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
from lib.ai_foundation.retrieval.mongo import MongoReportRetriever
from lib.ai_foundation.retrieval.composite import CompositeRetriever


# ---------------------------------------------------------------------------
# QdrantRetriever
# ---------------------------------------------------------------------------


class _FakeQdrantClient:
    """Mock that mimics AsyncQdrantClient.search()."""

    def __init__(self, results=None):
        self._results = results or []

    async def search(self, **kwargs):
        return self._results


class _FakeQdrantStore:
    """Mock that mimics QdrantStore.get_client() context manager."""

    def __init__(self, client):
        self._client = client

    @asynccontextmanager
    async def get_client(self):
        yield self._client


class _FakeSearchResult:
    def __init__(self, payload, score):
        self.payload = payload
        self.score = score


class TestQdrantRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_with_results(self):
        fake_results = [
            _FakeSearchResult({"data_type": "meal", "calories": 500}, 0.92),
            _FakeSearchResult({"data_type": "meal", "calories": 350}, 0.85),
        ]
        store = _FakeQdrantStore(_FakeQdrantClient(fake_results))

        async def mock_embed(text): return [0.1] * 3072

        retriever = QdrantRetriever(
            qdrant_store=store,
            embedding_fn=mock_embed,
        )
        results = await retriever.retrieve(
            RetrievalRequest(query="high carb meals", patient_ids=["p1"], data_types=["meal"])
        )
        assert len(results) == 2
        assert results[0].source == "qdrant"
        assert results[0].score == 0.92
        assert results[0].payload["calories"] == 500

    @pytest.mark.asyncio
    async def test_retrieve_empty(self):
        store = _FakeQdrantStore(_FakeQdrantClient([]))

        async def mock_embed(text): return [0.1] * 3072

        retriever = QdrantRetriever(qdrant_store=store, embedding_fn=mock_embed)
        results = await retriever.retrieve(
            RetrievalRequest(query="test", patient_ids=["p1"])
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_retrieve_no_embed_fn_raises(self):
        store = _FakeQdrantStore(_FakeQdrantClient([]))
        retriever = QdrantRetriever(qdrant_store=store, embedding_fn=None)
        with pytest.raises(RuntimeError, match="embedding_fn"):
            await retriever.retrieve(RetrievalRequest(query="test"))

    @pytest.mark.asyncio
    async def test_uses_embedding_cache(self):
        store = _FakeQdrantStore(_FakeQdrantClient([]))
        embed_calls = []

        async def mock_embed(text):
            embed_calls.append(text)
            return [0.1] * 3072

        cache = MagicMock()
        cache.get = MagicMock(return_value=None)  # first call: miss
        cache.set = MagicMock()

        retriever = QdrantRetriever(
            qdrant_store=store, embedding_fn=mock_embed, embedding_cache=cache,
        )
        await retriever.retrieve(RetrievalRequest(query="test query", patient_ids=["p1"]))

        cache.get.assert_called_once_with("test query")
        cache.set.assert_called_once()
        assert len(embed_calls) == 1

    @pytest.mark.asyncio
    async def test_uses_embedding_cache_hit(self):
        store = _FakeQdrantStore(_FakeQdrantClient([]))
        embed_calls = []

        async def mock_embed(text):
            embed_calls.append(text)
            return [0.1] * 3072

        cache = MagicMock()
        cache.get = MagicMock(return_value=[0.2] * 3072)  # cache hit

        retriever = QdrantRetriever(
            qdrant_store=store, embedding_fn=mock_embed, embedding_cache=cache,
        )
        await retriever.retrieve(RetrievalRequest(query="cached query", patient_ids=["p1"]))

        assert len(embed_calls) == 0  # embed_fn never called

    def test_build_filter_patient_ids(self):
        request = RetrievalRequest(query="test", patient_ids=["p1", "p2"])
        f = QdrantRetriever._build_filter(request)
        assert f is not None
        assert len(f.must) == 1
        assert f.must[0].key == "patient_id"

    def test_build_filter_with_dates(self):
        request = RetrievalRequest(
            query="test", patient_ids=["p1"],
            data_types=["meal"], date_start="2026-03-20", date_end="2026-03-24",
        )
        f = QdrantRetriever._build_filter(request)
        assert len(f.must) == 4  # patient_id + data_type + start_time + end_time
        # Verify date fields use epoch ms on start_time/end_time (not string "date")
        keys = {c.key for c in f.must}
        assert "start_time" in keys
        assert "end_time" in keys

    def test_build_filter_empty(self):
        request = RetrievalRequest(query="test")
        f = QdrantRetriever._build_filter(request)
        assert f is None


# ---------------------------------------------------------------------------
# MongoReportRetriever
# ---------------------------------------------------------------------------


class TestMongoReportRetriever:
    def _make_store(self, docs_by_collection: dict[str, list[dict]] | None = None):
        store = AsyncMock()
        docs_by_collection = docs_by_collection or {}

        async def mock_find_many(collection_name, query, projection=None, session=None):
            return docs_by_collection.get(collection_name, [])

        store.find_many = mock_find_many
        return store

    @pytest.mark.asyncio
    async def test_meal_reports(self):
        store = self._make_store({
            "meal_reports": [
                {
                    "date": "2026-03-23",
                    "meals": [
                        {"meal_type": "lunch", "meal_name": "Chicken Rice", "nutrition": {"calories": 500}},
                        {"meal_type": "dinner", "meal_name": "Salad", "nutrition": {"calories": 300}},
                    ],
                },
            ],
        })

        retriever = MongoReportRetriever(store)
        results = await retriever.retrieve(
            RetrievalRequest(
                query="meals yesterday",
                patient_ids=["p123"],
                data_types=["meal"],
                date_start="2026-03-23",
                date_end="2026-03-24",
            )
        )
        assert len(results) == 2  # 2 individual meals from 1 report
        assert results[0].data_type == "meal"
        assert results[0].payload["meal_type"] == "lunch"
        assert results[1].payload["nutrition"]["calories"] == 300

    @pytest.mark.asyncio
    async def test_cgm_reports(self):
        store = self._make_store({
            "cgm_reports": [
                {
                    "metadata": {"date_range": {"start": "2026-03-23T00:00:00", "end": "2026-03-24T00:00:00"}},
                    "cgm_summary_stats": {"average_glucose_mgdl": 145, "gmi": 6.8},
                    "cgm_range_stats": {"in_target_70_180_percent": 62},
                },
            ],
        })

        retriever = MongoReportRetriever(store)
        results = await retriever.retrieve(
            RetrievalRequest(query="glucose", patient_ids=["p123"], data_types=["cgm_range_stats"])
        )
        assert len(results) == 2  # summary + range from 1 report
        types = {r.data_type for r in results}
        assert "cgm_summary_stats" in types
        assert "cgm_range_stats" in types

    @pytest.mark.asyncio
    async def test_fitness_reports(self):
        store = self._make_store({
            "fitness_reports": [
                {"steps": 8500, "active_duration": 45, "peak_activity_time": {"hour": "14:00"}},
            ],
        })

        retriever = MongoReportRetriever(store)
        results = await retriever.retrieve(
            RetrievalRequest(query="activity", patient_ids=["p123"], data_types=["fitness_overview"])
        )
        assert len(results) == 1
        assert results[0].payload["steps"] == 8500
        assert results[0].payload["peak_hour"] == 14

    @pytest.mark.asyncio
    async def test_sleep_reports(self):
        store = self._make_store({
            "sleep_reports": [
                {"duration": {"per_day_average_duration": 420}, "quality": {"sleep_efficiency": 85, "sleep_quality": "good"}},
            ],
        })

        retriever = MongoReportRetriever(store)
        results = await retriever.retrieve(
            RetrievalRequest(query="sleep", patient_ids=["p123"], data_types=["sleep"])
        )
        assert len(results) == 1
        assert results[0].payload["duration_hours"] == 7.0
        assert results[0].payload["sleep_quality"] == "good"

    @pytest.mark.asyncio
    async def test_no_patient_ids_returns_empty(self):
        retriever = MongoReportRetriever(self._make_store())
        results = await retriever.retrieve(
            RetrievalRequest(query="meals", data_types=["meal"])
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_unknown_data_type_returns_empty(self):
        retriever = MongoReportRetriever(self._make_store())
        results = await retriever.retrieve(
            RetrievalRequest(query="test", patient_ids=["p1"], data_types=["unknown_type"])
        )
        assert len(results) == 0

    def test_resolve_collections(self):
        assert MongoReportRetriever._resolve_collections(["meal"]) == {"meal_reports"}
        assert MongoReportRetriever._resolve_collections(["cgm_range_stats"]) == {"cgm_reports"}
        assert MongoReportRetriever._resolve_collections(["fitness_overview"]) == {"fitness_reports"}
        assert MongoReportRetriever._resolve_collections(["sleep"]) == {"sleep_reports"}
        assert MongoReportRetriever._resolve_collections(["unknown"]) == set()
        assert MongoReportRetriever._resolve_collections(["meal", "cgm_range_stats"]) == {"meal_reports", "cgm_reports"}


# ---------------------------------------------------------------------------
# Composite wiring
# ---------------------------------------------------------------------------


class TestCompositeWiring:
    @pytest.mark.asyncio
    async def test_composite_with_real_retrievers(self):
        """Test that Qdrant + Mongo retrievers work together in CompositeRetriever."""
        # Mock Qdrant
        qdrant_results = [_FakeSearchResult({"data_type": "meal", "name": "Pasta"}, 0.88)]
        qdrant_store = _FakeQdrantStore(_FakeQdrantClient(qdrant_results))
        async def mock_embed(text): return [0.1] * 3072

        qdrant_retriever = QdrantRetriever(qdrant_store=qdrant_store, embedding_fn=mock_embed)

        # Mock Mongo
        mongo_store = AsyncMock()
        async def mock_find(coll, query, projection=None, session=None):
            if coll == "meal_reports":
                return [{"date": "2026-03-23", "meals": [{"meal_type": "lunch", "nutrition": {"calories": 400}}]}]
            return []
        mongo_store.find_many = mock_find
        mongo_retriever = MongoReportRetriever(mongo_store)

        # Wire composite
        composite = CompositeRetriever()
        composite.register("mongo_report", mongo_retriever, timeout_seconds=5.0, required=True)
        composite.register("qdrant", qdrant_retriever, timeout_seconds=8.0, required=False)

        result = await composite.retrieve(
            RetrievalRequest(
                query="meals yesterday",
                patient_ids=["p123"],
                data_types=["meal"],
                date_start="2026-03-23",
            )
        )

        assert len(result.items) >= 2  # at least 1 from mongo + 1 from qdrant
        sources = {r.source for r in result.items}
        assert "qdrant" in sources
        assert any("mongo" in s for s in sources)
        assert set(result.executed_sources) == {"mongo_report", "qdrant"}
        assert result.best_score == 0.88
