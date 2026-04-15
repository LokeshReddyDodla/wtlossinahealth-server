"""Tests for ai_foundation.cache.embedding_cache — closes a gap.

The EmbeddingCache halves embedding API costs but lacked dedicated coverage.
This file locks every branch:

- get/set/invalidate happy paths
- normalisation: strip + lowercase yields same key for variant inputs
- hash truncation produces stable 24-char digest
- enabled=False short-circuits both reads and writes
- Stats: hits, misses, writes, errors counted correctly
- hit_rate calculation
- Exception handling on Redis errors (returns None on get, swallows on set)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from lib.ai_foundation.cache.embedding_cache import EmbeddingCache, EmbeddingCacheStats


def _store(get_value=None, raises=None):
    store = MagicMock()
    if raises:
        store.get_key = MagicMock(side_effect=raises)
        store.set_key = MagicMock(side_effect=raises)
        store.delete_key = MagicMock(side_effect=raises)
    else:
        store.get_key = MagicMock(return_value=get_value)
        store.set_key = MagicMock(return_value=True)
        store.delete_key = MagicMock(return_value=True)
    return store


# ── get / set / invalidate happy paths ──────────────────────────────────────


class TestGetSetInvalidate:
    def test_get_hit_returns_vector(self):
        vec = [0.1, 0.2, 0.3]
        store = _store(get_value=json.dumps(vec))
        cache = EmbeddingCache(store)
        result = cache.get("hello")
        assert result == vec
        assert cache.stats.hits == 1
        assert cache.stats.misses == 0

    def test_get_miss_returns_none(self):
        store = _store(get_value=None)
        cache = EmbeddingCache(store)
        result = cache.get("hello")
        assert result is None
        assert cache.stats.hits == 0
        assert cache.stats.misses == 1

    def test_set_writes_json_and_ttl(self):
        store = _store()
        cache = EmbeddingCache(store, ttl_seconds=3600)
        vec = [0.5, 0.6, 0.7]
        cache.set("hello", vec)
        store.set_key.assert_called_once()
        args = store.set_key.call_args
        # First positional or kwarg is value
        assert json.loads(args.args[1]) == vec
        assert args.kwargs.get("expire") == 3600
        assert cache.stats.writes == 1

    def test_invalidate_calls_delete(self):
        store = _store()
        cache = EmbeddingCache(store)
        cache.invalidate("hello")
        store.delete_key.assert_called_once()


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


class TestRoundTrip:
    def test_set_then_get_returns_same_vector(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        # Build a real in-memory store stub to verify the round-trip
        backend: dict[str, str] = {}

        store = MagicMock()
        store.set_key = MagicMock(side_effect=lambda k, v, **_: backend.update({k: v}))
        store.get_key = MagicMock(side_effect=lambda k: backend.get(k))
        store.delete_key = MagicMock(side_effect=lambda k: backend.pop(k, None))

        cache = EmbeddingCache(store)
        cache.set("query text", vec)
        result = cache.get("query text")
        assert result == vec

    def test_normalised_set_normalised_get(self):
        backend: dict[str, str] = {}
        store = MagicMock()
        store.set_key = MagicMock(side_effect=lambda k, v, **_: backend.update({k: v}))
        store.get_key = MagicMock(side_effect=lambda k: backend.get(k))
        cache = EmbeddingCache(store)

        cache.set(" Hello World ", [1.0, 2.0])
        # Different surface form, same normalised key
        assert cache.get("hello world") == [1.0, 2.0]


# ── enabled=False short-circuit ────────────────────────────────────────────


class TestEnabledFlag:
    def test_disabled_get_returns_none_without_redis(self):
        store = _store(get_value=json.dumps([1.0]))
        cache = EmbeddingCache(store, enabled=False)
        assert cache.get("hello") is None
        store.get_key.assert_not_called()

    def test_disabled_set_does_not_write(self):
        store = _store()
        cache = EmbeddingCache(store, enabled=False)
        cache.set("hello", [1.0])
        store.set_key.assert_not_called()

    def test_runtime_toggle(self):
        store = _store(get_value=json.dumps([1.0]))
        cache = EmbeddingCache(store, enabled=True)
        cache.enabled = False
        assert cache.get("hello") is None
        cache.enabled = True
        store.get_key = MagicMock(return_value=json.dumps([2.0]))
        assert cache.get("hello") == [2.0]


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

    def test_hit_rate_calculation(self):
        cache = EmbeddingCache(_store(get_value=json.dumps([1.0])))
        cache.get("a")  # hit
        cache.get("b")  # hit
        # Switch to miss
        cache._store.get_key = MagicMock(return_value=None)
        cache.get("c")  # miss
        s = cache.stats
        assert s.hits == 2
        assert s.misses == 1
        assert abs(s.hit_rate - 2/3) < 1e-9

    def test_stats_returns_copy(self):
        """stats property must return a copy so external code can't mutate
        internal counters."""
        cache = EmbeddingCache(_store(get_value=None))
        cache.get("a")  # miss → 1
        s1 = cache.stats
        cache.get("b")  # miss → 2
        s2 = cache.stats
        assert s1.misses == 1   # not mutated by second call
        assert s2.misses == 2

    def test_error_counter_on_get_exception(self):
        store = _store(raises=Exception("Redis exploded"))
        cache = EmbeddingCache(store)
        result = cache.get("hello")
        assert result is None  # graceful fallback
        assert cache.stats.errors == 1

    def test_error_counter_on_set_exception(self):
        store = _store(raises=Exception("Redis down"))
        cache = EmbeddingCache(store)
        cache.set("hello", [1.0])  # should not raise
        assert cache.stats.errors == 1


# ── Exception handling ────────────────────────────────────────────────────


class TestErrorHandling:
    def test_get_with_corrupt_json_returns_none(self):
        store = _store(get_value="not json{{{")
        cache = EmbeddingCache(store)
        result = cache.get("hello")
        # JSON parse error → caught, errors++ , returns None
        assert result is None
        assert cache.stats.errors == 1

    def test_invalidate_swallows_exception(self):
        store = _store(raises=Exception("redis down"))
        cache = EmbeddingCache(store)
        cache.invalidate("hello")  # no raise


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
