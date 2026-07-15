"""
Embedding Cache — avoids redundant embedding API calls.

Caches embedding vectors in Redis keyed by a hash of the input text.
When the same (or identical) text needs embedding again within the TTL,
the cached vector is returned instantly. Saves ~50% of embedding API
calls at scale.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from lib.core.cache_store import CacheStore

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "emb_cache"


class EmbeddingCacheStats(BaseModel):
    """Observable counters for embedding cache performance."""

    hits: int = 0
    misses: int = 0
    writes: int = 0
    errors: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class EmbeddingCache:
    """Redis-backed cache for embedding vectors.

    Args:
        cache_store: The ``CacheStore`` instance (from ``lib/core``).
        ttl_seconds: Time-to-live for cached embeddings. Default 24 hours.
        enabled: Master switch.

    The cache key is::

        emb_cache:<sha256(normalised_text)[:24]>

    Example::

        cache = EmbeddingCache(cache_store, ttl_seconds=86400)

        # Try cache first
        vector = await cache.get("How were my sugars this week?")
        if vector is None:
            vector = await openai.embeddings.create(input=text, ...)
            await cache.set("How were my sugars this week?", vector)
    """

    def __init__(
        self,
        cache_store: CacheStore,
        *,
        ttl_seconds: int = 86_400,
        enabled: bool = True,
    ) -> None:
        self._store = cache_store
        self._ttl = ttl_seconds
        self._enabled = enabled
        self._stats = EmbeddingCacheStats()

    # -- Public API ---------------------------------------------------------

    async def get(self, text: str) -> list[float] | None:
        """Look up a cached embedding vector. Returns ``None`` on miss."""
        if not self._enabled:
            return None

        key = self._build_key(text)
        try:
            raw = await self._store.aget_key(key)
            if raw is None:
                self._stats.misses += 1
                return None

            vector = json.loads(raw)
            self._stats.hits += 1
            logger.debug("Embedding cache HIT: %s", key)
            return vector

        except Exception as exc:
            self._stats.errors += 1
            logger.warning("Embedding cache GET error: %s", exc)
            return None

    async def set(self, text: str, vector: list[float]) -> None:
        """Store an embedding vector in cache."""
        if not self._enabled:
            return

        key = self._build_key(text)
        try:
            payload = json.dumps(vector)
            await self._store.aset_key(key, payload, expire=self._ttl)
            self._stats.writes += 1
            logger.debug("Embedding cache SET: %s (ttl=%ds)", key, self._ttl)
        except Exception as exc:
            self._stats.errors += 1
            logger.warning("Embedding cache SET error: %s", exc)

    async def invalidate(self, text: str) -> None:
        """Explicitly remove a cached embedding."""
        key = self._build_key(text)
        try:
            await self._store.adelete_key(key)
        except Exception as exc:
            logger.warning("Embedding cache DELETE error: %s", exc)

    @property
    def stats(self) -> EmbeddingCacheStats:
        return self._stats.model_copy()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _build_key(text: str) -> str:
        """Deterministic cache key from normalised text."""
        normalised = text.strip().lower()
        digest = hashlib.sha256(normalised.encode()).hexdigest()[:24]
        return f"{_CACHE_PREFIX}:{digest}"
