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

    def check_and_record(
        self,
        tenant_id: str,
        priority: RequestPriority = RequestPriority.NORMAL,
    ) -> RateLimitResult:
        """Atomically check and increment the request counter.

        Uses SET NX + INCR to avoid TOCTOU race between check and record.
        """
        config = self._limits.get(priority, DEFAULT_LIMITS[RequestPriority.NORMAL])

        if not self._enabled:
            return RateLimitResult(
                allowed=True,
                remaining=config.max_requests,
                limit=config.max_requests,
                reset_at=time.time() + config.window_seconds,
            )

        key = self._build_key(tenant_id, priority)

        try:
            # Ensure key exists with TTL (no-op if already exists)
            self._store.set_key(key, "0", expire=config.window_seconds, nx=True)
            # Atomic increment — returns the new count
            current = self._store.incr_key(key)
            # If INCR recreated an expired key (race between SET NX and INCR),
            # the new key has no TTL. Set TTL only — don't overwrite the value.
            if current == 1:
                self._store.expire_key(key, config.window_seconds)
        except Exception as exc:
            logger.warning("Rate limiter failed for %s: %s", tenant_id, exc)
            # Fail open — allow the request on Redis errors
            return RateLimitResult(
                allowed=True, remaining=config.max_requests,
                limit=config.max_requests, reset_at=time.time() + config.window_seconds,
            )

        allowed = current <= config.max_requests
        remaining = max(0, config.max_requests - current)

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            limit=config.max_requests,
            reset_at=time.time() + config.window_seconds,
        )

    # Keep check() and record() as thin wrappers for backwards compatibility
    def check(
        self,
        tenant_id: str,
        priority: RequestPriority = RequestPriority.NORMAL,
    ) -> RateLimitResult:
        """Read-only check (no increment). Use check_and_record() for atomic ops."""
        config = self._limits.get(priority, DEFAULT_LIMITS[RequestPriority.NORMAL])
        if not self._enabled:
            return RateLimitResult(
                allowed=True, remaining=config.max_requests,
                limit=config.max_requests, reset_at=time.time() + config.window_seconds,
            )
        key = self._build_key(tenant_id, priority)
        try:
            raw = self._store.get_key(key)
            current = int(raw) if raw else 0
        except Exception:
            current = 0
        return RateLimitResult(
            allowed=current < config.max_requests,
            remaining=max(0, config.max_requests - current),
            limit=config.max_requests,
            reset_at=time.time() + config.window_seconds,
        )

    def record(
        self,
        tenant_id: str,
        priority: RequestPriority = RequestPriority.NORMAL,
    ) -> None:
        """Increment counter. Prefer check_and_record() for atomic check+increment."""
        if not self._enabled:
            return
        config = self._limits.get(priority, DEFAULT_LIMITS[RequestPriority.NORMAL])
        key = self._build_key(tenant_id, priority)
        try:
            self._store.set_key(key, "0", expire=config.window_seconds, nx=True)
            current = self._store.incr_key(key)
            if current == 1:
                self._store.expire_key(key, config.window_seconds)
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
