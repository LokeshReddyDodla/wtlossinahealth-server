"""Tests for QdrantRetriever — filtered scroll + semantic search + filter building."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from contextlib import asynccontextmanager

from lib.ai_foundation.retrieval.base import RetrievalRequest
from lib.ai_foundation.retrieval.qdrant import QdrantRetriever


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class _FakeQdrantClient:
    def __init__(self, search_results=None, scroll_results=None):
        self._search = search_results or []
        self._scroll = scroll_results or []

    async def search(self, **kwargs):
        return self._search

    async def scroll(self, **kwargs):
        return self._scroll, None  # (records, next_offset)


class _FakeQdrantStore:
    def __init__(self, client):
        self._client = client

    @asynccontextmanager
    async def get_client(self):
        yield self._client


class _FakeSearchResult:
    def __init__(self, payload, score):
        self.payload = payload
        self.score = score


class _FakeScrollRecord:
    def __init__(self, payload):
        self.payload = payload


# ---------------------------------------------------------------------------
# Filtered Scroll (Mode 1)
# ---------------------------------------------------------------------------


class TestFilteredScroll:
    @pytest.mark.asyncio
    async def test_retrieve_filtered_with_results(self):
        records = [
            _FakeScrollRecord({"data_type": "meal", "meal_type": "lunch", "nutrition": {"calories": 500}}),
            _FakeScrollRecord({"data_type": "meal", "meal_type": "dinner", "nutrition": {"calories": 350}}),
        ]
        store = _FakeQdrantStore(_FakeQdrantClient(scroll_results=records))
        retriever = QdrantRetriever(qdrant_store=store)

        results = await retriever.retrieve_filtered(
            RetrievalRequest(query="meals today", patient_ids=["p1"], data_types=["meal"])
        )
        assert len(results) == 2
        assert results[0].source == "qdrant_filtered"
        assert results[0].score is None  # no similarity score
        assert results[0].payload["nutrition"]["calories"] == 500

    @pytest.mark.asyncio
    async def test_retrieve_filtered_empty(self):
        store = _FakeQdrantStore(_FakeQdrantClient(scroll_results=[]))
        retriever = QdrantRetriever(qdrant_store=store)

        results = await retriever.retrieve_filtered(
            RetrievalRequest(query="test", patient_ids=["p1"], data_types=["meal"])
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_retrieve_filtered_no_patient_ids_returns_empty(self):
        store = _FakeQdrantStore(_FakeQdrantClient(scroll_results=[]))
        retriever = QdrantRetriever(qdrant_store=store)

        results = await retriever.retrieve_filtered(
            RetrievalRequest(query="test")  # no patient_ids
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_no_embedding_needed_for_filtered(self):
        """Filtered scroll should work without an embedding function."""
        records = [_FakeScrollRecord({"data_type": "meal"})]
        store = _FakeQdrantStore(_FakeQdrantClient(scroll_results=records))
        retriever = QdrantRetriever(qdrant_store=store, embedding_fn=None)

        results = await retriever.retrieve_filtered(
            RetrievalRequest(query="meals", patient_ids=["p1"], data_types=["meal"])
        )
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Semantic Search (Mode 2)
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_retrieve_with_results(self):
        search_results = [
            _FakeSearchResult({"data_type": "meal", "calories": 500}, 0.92),
            _FakeSearchResult({"data_type": "meal", "calories": 350}, 0.85),
        ]
        store = _FakeQdrantStore(_FakeQdrantClient(search_results=search_results))

        async def mock_embed(text): return [0.1] * 3072

        retriever = QdrantRetriever(qdrant_store=store, embedding_fn=mock_embed)
        results = await retriever.retrieve(
            RetrievalRequest(query="high carb meals", patient_ids=["p1"], data_types=["meal"])
        )
        assert len(results) == 2
        assert results[0].source == "qdrant_semantic"
        assert results[0].score == 0.92

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
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()

        retriever = QdrantRetriever(qdrant_store=store, embedding_fn=mock_embed, embedding_cache=cache)
        await retriever.retrieve(RetrievalRequest(query="test", patient_ids=["p1"]))

        cache.get.assert_called_once_with("test")
        cache.set.assert_called_once()
        assert len(embed_calls) == 1

    @pytest.mark.asyncio
    async def test_cache_hit_skips_embedding(self):
        store = _FakeQdrantStore(_FakeQdrantClient([]))
        embed_calls = []

        async def mock_embed(text):
            embed_calls.append(text)
            return [0.1] * 3072

        cache = MagicMock()
        cache.get = AsyncMock(return_value=[0.2] * 3072)

        retriever = QdrantRetriever(qdrant_store=store, embedding_fn=mock_embed, embedding_cache=cache)
        await retriever.retrieve(RetrievalRequest(query="cached", patient_ids=["p1"]))

        assert len(embed_calls) == 0


# ---------------------------------------------------------------------------
# Filter Building
# ---------------------------------------------------------------------------


class TestFilterBuilding:
    def _build(self, **kwargs):
        request = RetrievalRequest(query="test", **kwargs)
        retriever = QdrantRetriever(qdrant_store=MagicMock())
        return retriever._build_full_filter(request)

    def test_no_patient_ids_returns_none(self):
        f = self._build()
        assert f is None

    def test_patient_ids_only(self):
        f = self._build(patient_ids=["p1", "p2"])
        assert f is not None

    def test_with_data_types_and_dates(self):
        f = self._build(
            patient_ids=["p1"], data_types=["meal"],
            date_start="2026-03-20", date_end="2026-03-24",
        )
        assert f is not None
        # Should have should filters with must conditions including start_time/end_time
        all_conditions = []
        if f.must:
            all_conditions.extend(f.must)
        if f.should:
            for sub in f.should:
                if hasattr(sub, 'must') and sub.must:
                    all_conditions.extend(sub.must)
        keys = {c.key for c in all_conditions}
        assert "patient_id" in keys
        assert "start_time" in keys or "data_type" in keys  # date filter applied

    def test_with_time_buckets(self):
        f = self._build(
            patient_ids=["p1"], data_types=["meal"],
            filters={"time_buckets": ["morning", "evening"]},
        )
        assert f is not None

    def test_with_hour_range(self):
        f = self._build(
            patient_ids=["p1"], data_types=["cgm_range_stats"],
            filters={"hour_start": 18, "hour_end": 23},
        )
        assert f is not None

    def test_with_month_filters(self):
        f = self._build(
            patient_ids=["p1"], data_types=["meal"],
            filters={"month_filters": [1, 2, 3]},
        )
        assert f is not None

    def test_with_numeric_filters(self):
        f = self._build(
            patient_ids=["p1"], data_types=["meal"],
            filters={"numeric_filters": [{"key": "calories", "range_condition": {"gte": 500}}]},
        )
        assert f is not None

    def test_stats_events_expansion(self):
        """hypo data types should expand to include hypo_stats and hypo_event."""
        from lib.ai_foundation.retrieval.qdrant import _expand_data_types
        expanded = _expand_data_types(["hypo_stats"])
        assert "hypo_stats" in expanded
        assert "hypo_event" in expanded

    def test_non_filterable_types(self):
        """profile and documents should get separate should clause."""
        f = self._build(
            patient_ids=["p1"], data_types=["profile", "meal"],
        )
        assert f is not None
        # Should have should filters (one for profile, one for timeseries)
        assert f.should is not None or f.must is not None


class TestPlanRetrieval:
    """Plans are matched by plan_status, never by date overlap."""

    def _build(self, **kwargs):
        request = RetrievalRequest(query="test", **kwargs)
        return QdrantRetriever(qdrant_store=MagicMock())._build_full_filter(request)

    @staticmethod
    def _branches(f):
        if f is None:
            return []
        return list(f.should) if getattr(f, "should", None) else [f]

    @classmethod
    def _plan_branch(cls, f):
        for b in cls._branches(f):
            for c in (b.must or []):
                if c.key == "data_type":
                    vals = set(getattr(c.match, "any", None) or [getattr(c.match, "value", None)])
                    if vals & {"diet_plan", "fitness_plan"}:
                        return b
        return None

    @staticmethod
    def _keys(branch):
        return {c.key for c in (branch.must or [])}

    @staticmethod
    def _cond(branch, key):
        return next((c for c in (branch.must or []) if c.key == key), None)

    def test_plan_branch_matches_status_not_dates(self):
        """Requesting diet_plan yields a branch filtered by plan_status=ACTIVE
        with no start_time/end_time — visible regardless of the query window."""
        f = self._build(
            patient_ids=["p1"], data_types=["diet_plan"],
            date_start="2026-07-24", date_end="2026-07-24",
        )
        branch = self._plan_branch(f)
        assert branch is not None
        keys = self._keys(branch)
        assert "plan_status" in keys
        assert "start_time" not in keys and "end_time" not in keys
        assert self._cond(branch, "plan_status").match.value == "ACTIVE"

    def test_history_filter_overrides_status(self):
        """An explicit plan_status list requests history (all statuses)."""
        f = self._build(
            patient_ids=["p1"], data_types=["diet_plan"],
            filters={"plan_status": ["ACTIVE", "EXPIRED", "ARCHIVED"]},
        )
        branch = self._plan_branch(f)
        assert set(self._cond(branch, "plan_status").match.any) == {"ACTIVE", "EXPIRED", "ARCHIVED"}

    def test_all_types_sweep_includes_active_plan_and_excludes_from_date_branch(self):
        """investigate_day (empty data_types) surfaces the active plan via the
        status branch, and the date branch must_not-excludes plan types."""
        f = self._build(
            patient_ids=["p1"], data_types=[],
            date_start="2026-07-24", date_end="2026-07-24",
        )
        assert self._plan_branch(f) is not None  # active plan surfaced
        # the date-filtered branch (has start_time/end_time) excludes plan types
        date_branch = next(
            b for b in self._branches(f)
            if "start_time" in self._keys(b) or "end_time" in self._keys(b)
        )
        mn = getattr(date_branch, "must_not", None) or []
        excluded = set()
        for c in mn:
            if c.key == "data_type":
                excluded |= set(getattr(c.match, "any", None) or [getattr(c.match, "value", None)])
        assert {"diet_plan", "fitness_plan"} <= excluded

    def test_unrelated_query_has_no_plan_branch(self):
        """A glucose-only query must not pull plans in."""
        f = self._build(
            patient_ids=["p1"], data_types=["cgm_summary_stats"],
            date_start="2026-07-24", date_end="2026-07-24",
        )
        assert self._plan_branch(f) is None

    def test_plan_status_not_leaked_into_timeseries_branch(self):
        """plan_status must not become a match condition on meals/glucose."""
        f = self._build(
            patient_ids=["p1"], data_types=["meal"],
            filters={"plan_status": "ACTIVE"},
        )
        for b in self._branches(f):
            if "data_type" in self._keys(b):
                dc = self._cond(b, "data_type")
                vals = set(getattr(dc.match, "any", None) or [getattr(dc.match, "value", None)])
                if "meal" in vals:  # the timeseries branch
                    assert "plan_status" not in self._keys(b)
