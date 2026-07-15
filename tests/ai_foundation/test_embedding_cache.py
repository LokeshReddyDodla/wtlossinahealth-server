"""Tests for ai_foundation.cache.embedding_cache — closes a gap.

The EmbeddingCache halves embedding API costs but lacked dedicated coverage.
This file locks every branch:

- get/set/invalidate happy paths (async, backed by CacheStore a-methods)
- normalisation: strip + lowercase yields same key for variant inputs
- hash truncation produces stable 24-char digest
- enabled=False short-circuits both reads and writes
- Stats: hits, misses, writes, errors counted correctly
- hit_rate calculation
- Exception handling on Redis errors (returns None on get, swallows on set)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.cache.embedding_cache import EmbeddingCache, EmbeddingCacheStats


def _store(get_value=None, raises=None):
    store = MagicMock()
    if raises:
        store.aget_key = AsyncMock(side_effect=raises)
        store.aset_key = AsyncMock(side_effect=raises)
        store.adelete_key = AsyncMock(side_effect=raises)
    else:
        store.aget_key = AsyncMock(return_value=get_value)
        store.aset_key = AsyncMock(return_value=True)
        store.adelete_key = AsyncMock(return_value=True)
    return store


# ── get / set / invalidate happy paths ──────────────────────────────────────


class TestGetSetInvalidate:
    @pytest.mark.asyncio
    async def test_get_hit_returns_vector(self):
        vec = [0.1, 0.2, 0.3]
        store = _store(get_value=json.dumps(vec))
        cache = EmbeddingCache(store)
        result = await cache.get("hello")
        assert result == vec
        assert cache.stats.hits == 1
        assert cache.stats.misses == 0

    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self):
        store = _store(get_value=None)
        cache = EmbeddingCache(store)
        result = await cache.get("hello")
        assert result is None
        assert cache.stats.hits == 0
        assert cache.stats.misses == 1

    @pytest.mark.asyncio
    async def test_set_writes_json_and_ttl(self):
        store = _store()
        cache = EmbeddingCache(store, ttl_seconds=3600)
        vec = [0.5, 0.6, 0.7]
        await cache.set("hello", vec)
        store.aset_key.assert_called_once()
        args = store.aset_key.call_args
        # First positional or kwarg is value
        assert json.loads(args.args[1]) == vec
        assert args.kwargs.get("expire") == 3600
        assert cache.stats.writes == 1

    @pytest.mark.asyncio
    async def test_invalidate_calls_delete(self):
        store = _store()
        cache = EmbeddingCache(store)
        await cache.invalidate("hello")
        store.adelete_key.assert_called_once()


# ── Normalisation ───────────────────────────────────────────────────────────


class TestKeyNormalisation:
    @pytest.mark.parametrize(
        "text_a,text_b",
        [
            ("hello", "hello"),
            ("hello", "HELLO"),
            ("hello", " hello "),
            ("hello world", "hello world"),
            (" Hello World ", "hello world"),
            ("MixedCase", "mixedcase"),
        ],
    )
    def test_variants_yield_same_key(self, text_a, text_b):
        assert EmbeddingCache._build_key(text_a) == EmbeddingCache._build_key(text_b)

    @pytest.mark.parametrize(
        "text_a,text_b",
        [
            ("hello", "hello!"),       # punctuation differs
            ("hello", "world"),
            ("a", "b"),
            ("hello world", "helloworld"),  # whitespace meaningful
            ("query 1", "query 2"),
        ],
    )
    def test_different_inputs_yield_different_keys(self, text_a, text_b):
        assert EmbeddingCache._build_key(text_a) != EmbeddingCache._build_key(text_b)

    def test_key_format_prefix_and_length(self):
        key = EmbeddingCache._build_key("anything")
        assert key.startswith("emb_cache:")
        # 24-char hex digest after prefix
        digest = key.split(":", 1)[1]
        assert len(digest) == 24
        assert all(c in "0123456789abcdef" for c in digest)


# ── Round-trip (set then get) ──────────────────────────────────────────────


def _backend_store(backend: dict[str, str]) -> MagicMock:
    store = MagicMock()

    async def _set(k, v, **_):
        backend[k] = v

    async def _get(k):
        return backend.get(k)

    async def _delete(k):
        backend.pop(k, None)

    store.aset_key = AsyncMock(side_effect=_set)
    store.aget_key = AsyncMock(side_effect=_get)
    store.adelete_key = AsyncMock(side_effect=_delete)
    return store


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_set_then_get_returns_same_vector(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        backend: dict[str, str] = {}
        cache = EmbeddingCache(_backend_store(backend))
        await cache.set("query text", vec)
        result = await cache.get("query text")
        assert result == vec

    @pytest.mark.asyncio
    async def test_normalised_set_normalised_get(self):
        backend: dict[str, str] = {}
        cache = EmbeddingCache(_backend_store(backend))

        await cache.set(" Hello World ", [1.0, 2.0])
        # Different surface form, same normalised key
        assert await cache.get("hello world") == [1.0, 2.0]


# ── enabled=False short-circuit ────────────────────────────────────────────


class TestEnabledFlag:
    @pytest.mark.asyncio
    async def test_disabled_get_returns_none_without_redis(self):
        store = _store(get_value=json.dumps([1.0]))
        cache = EmbeddingCache(store, enabled=False)
        assert await cache.get("hello") is None
        store.aget_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_set_does_not_write(self):
        store = _store()
        cache = EmbeddingCache(store, enabled=False)
        await cache.set("hello", [1.0])
        store.aset_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_runtime_toggle(self):
        store = _store(get_value=json.dumps([1.0]))
        cache = EmbeddingCache(store, enabled=True)
        cache.enabled = False
        assert await cache.get("hello") is None
        cache.enabled = True
        store.aget_key = AsyncMock(return_value=json.dumps([2.0]))
        assert await cache.get("hello") == [2.0]


# ── Stats ───────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_starts_zero(self):
        cache = EmbeddingCache(_store())
        s = cache.stats
        assert s.hits == 0
        assert s.misses == 0
        assert s.writes == 0
        assert s.errors == 0
        assert s.hit_rate == 0.0

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self):
        cache = EmbeddingCache(_store(get_value=json.dumps([1.0])))
        await cache.get("a")  # hit
        await cache.get("b")  # hit
        # Switch to miss
        cache._store.aget_key = AsyncMock(return_value=None)
        await cache.get("c")  # miss
        s = cache.stats
        assert s.hits == 2
        assert s.misses == 1
        assert abs(s.hit_rate - 2/3) < 1e-9

    @pytest.mark.asyncio
    async def test_stats_returns_copy(self):
        """stats property must return a copy so external code can't mutate
        internal counters."""
        cache = EmbeddingCache(_store(get_value=None))
        await cache.get("a")  # miss → 1
        s1 = cache.stats
        await cache.get("b")  # miss → 2
        s2 = cache.stats
        assert s1.misses == 1   # not mutated by second call
        assert s2.misses == 2

    @pytest.mark.asyncio
    async def test_error_counter_on_get_exception(self):
        store = _store(raises=Exception("Redis exploded"))
        cache = EmbeddingCache(store)
        result = await cache.get("hello")
        assert result is None  # graceful fallback
        assert cache.stats.errors == 1

    @pytest.mark.asyncio
    async def test_error_counter_on_set_exception(self):
        store = _store(raises=Exception("Redis down"))
        cache = EmbeddingCache(store)
        await cache.set("hello", [1.0])  # should not raise
        assert cache.stats.errors == 1


# ── Exception handling ────────────────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_get_with_corrupt_json_returns_none(self):
        store = _store(get_value="not json{{{")
        cache = EmbeddingCache(store)
        result = await cache.get("hello")
        # JSON parse error → caught, errors++ , returns None
        assert result is None
        assert cache.stats.errors == 1

    @pytest.mark.asyncio
    async def test_invalidate_swallows_exception(self):
        store = _store(raises=Exception("redis down"))
        cache = EmbeddingCache(store)
        await cache.invalidate("hello")  # no raise


# ── EmbeddingCacheStats model ─────────────────────────────────────────────


class TestStatsModel:
    def test_default_zero(self):
        s = EmbeddingCacheStats()
        assert s.hit_rate == 0.0

    def test_only_hits(self):
        s = EmbeddingCacheStats(hits=5, misses=0)
        assert s.hit_rate == 1.0

    def test_only_misses(self):
        s = EmbeddingCacheStats(hits=0, misses=5)
        assert s.hit_rate == 0.0

    def test_split(self):
        s = EmbeddingCacheStats(hits=3, misses=1)
        assert abs(s.hit_rate - 0.75) < 1e-9
