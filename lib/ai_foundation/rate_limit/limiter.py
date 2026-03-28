"""
Rate Limiter — per-tenant, priority-aware rate limiting backed by Redis.

Uses a sliding window counter to enforce rate limits. Higher priority
requests get higher limits. Designed for multi-tenant deployments where
different health facilities have different quotas.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from lib.ai_foundation.agents.state import RequestPriority

if TYPE_CHECKING:
    from lib.core.cache_store import CacheStore

logger = logging.getLogger(__name__)

_RATE_LIMIT_PREFIX = "rl"


class RateLimitConfig(BaseModel):
    """Rate limit configuration for a priority level."""

    max_requests: int = Field(description="Maximum requests allowed in the window.")
    window_seconds: int = Field(
        default=3600,
        description="Sliding window duration in seconds.",
    )


class RateLimitResult(BaseModel):
    """Result of a rate limit check."""

    allowed: bool
    remaining: int = Field(description="Requests remaining in the current window.")
    limit: int = Field(description="Total limit for this window.")
    reset_at: float = Field(description="Unix timestamp when the window resets.")


# Default limits per priority level
DEFAULT_LIMITS: dict[RequestPriority, RateLimitConfig] = {
    RequestPriority.CRITICAL: RateLimitConfig(max_requests=10_000, window_seconds=3600),
    RequestPriority.HIGH: RateLimitConfig(max_requests=5_000, window_seconds=3600),
    RequestPriority.NORMAL: RateLimitConfig(max_requests=1_000, window_seconds=3600),
    RequestPriority.LOW: RateLimitConfig(max_requests=500, window_seconds=3600),
}


class RateLimiter:
    """Per-tenant rate limiter with priority awareness.

    Uses Redis counters with TTL for automatic window expiry.

    Example::

        limiter = RateLimiter(cache_store)

        result = limiter.check("facility_123", RequestPriority.NORMAL)
        if result.allowed:
            limiter.record("facility_123", RequestPriority.NORMAL)
            # proceed with request
        else:
            # return 429 Too Many Requests
    """

    def __init__(
        self,
        cache_store: CacheStore,
        *,
        limits: dict[RequestPriority, RateLimitConfig] | None = None,
        enabled: bool = True,
    ) -> None:
        self._store = cache_store
        self._limits = limits or DEFAULT_LIMITS
        self._enabled = enabled

    def check(
        self,
        tenant_id: str,
        priority: RequestPriority = RequestPriority.NORMAL,
    ) -> RateLimitResult:
        """Check if a request is allowed under the rate limit.

        Does NOT increment the counter — call ``record()`` after the
        request is accepted.
        """
        if not self._enabled:
            config = self._limits.get(priority, DEFAULT_LIMITS[RequestPriority.NORMAL])
            return RateLimitResult(
                allowed=True,
                remaining=config.max_requests,
                limit=config.max_requests,
                reset_at=time.time() + config.window_seconds,
            )

        config = self._limits.get(priority, DEFAULT_LIMITS[RequestPriority.NORMAL])
        key = self._build_key(tenant_id, priority)

        try:
            raw = self._store.get_key(key)
            current = int(raw) if raw else 0
        except Exception:
            current = 0

        remaining = max(0, config.max_requests - current)
        allowed = current < config.max_requests

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            limit=config.max_requests,
            reset_at=time.time() + config.window_seconds,
        )

    def record(
        self,
        tenant_id: str,
        priority: RequestPriority = RequestPriority.NORMAL,
    ) -> None:
        """Increment the request counter for a tenant."""
        if not self._enabled:
            return

        config = self._limits.get(priority, DEFAULT_LIMITS[RequestPriority.NORMAL])
        key = self._build_key(tenant_id, priority)

        try:
            # Use SET NX to create with TTL only if key doesn't exist
            created = self._store.set_key(key, "1", expire=config.window_seconds, nx=True)
            if not created:
                # Key exists — increment without resetting TTL
                namespaced_key = f"{self._store._get_namespace()}:{key.strip()}"
                self._store._get_client().incr(namespaced_key)
        except Exception as exc:
            logger.warning("Rate limiter record failed for %s: %s", tenant_id, exc)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @staticmethod
    def _build_key(tenant_id: str, priority: RequestPriority) -> str:
        return f"{_RATE_LIMIT_PREFIX}:{tenant_id}:{priority.value}"
