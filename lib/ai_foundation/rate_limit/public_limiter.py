"""
Public Rate Limiter — IP + session + global rate limiting for anonymous endpoints.

Three layers (launch-relaxed, tighten after traffic analysis):
    Per-IP:      500 requests/hour
    Per-session: 500 messages lifetime (counter expires with session)
    Global:      50,000 requests/hour (cost safety valve)

Follows the same fail-open pattern as the tenant-based RateLimiter.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.core.cache_store import CacheStore

logger = logging.getLogger(__name__)

_PREFIX = "pub_rl"
_IP_LIMIT = 500
_IP_WINDOW = 3600
_SESSION_LIMIT = 500
_SESSION_TTL = 1800  # aligned with agent session TTL
_GLOBAL_LIMIT = 50_000
_GLOBAL_WINDOW = 3600


class PublicRateLimitResult(BaseModel):
    allowed: bool
    remaining: int = Field(description="Requests remaining on the tightest constraint.")
    limit: int = Field(description="Limit that was hit (or the tightest).")
    reset_at: float = Field(description="Unix timestamp when the tightest window resets.")
    layer: str = Field(default="", description="Which layer blocked: ip, session, global, or empty.")


class PublicRateLimiter:
    """Rate limiter for anonymous public endpoints."""

    def __init__(self, cache_store: CacheStore) -> None:
        self._store = cache_store

    def check_and_record(self, ip: str, session_id: str) -> PublicRateLimitResult:
        now = time.time()
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

        checks = [
            ("ip", f"{_PREFIX}:ip:{ip_hash}", _IP_LIMIT, _IP_WINDOW),
            ("session", f"{_PREFIX}:sess:{session_id}", _SESSION_LIMIT, _SESSION_TTL),
            ("global", f"{_PREFIX}:global", _GLOBAL_LIMIT, _GLOBAL_WINDOW),
        ]

        for layer, key, limit, window in checks:
            try:
                self._store.set_key(key, "0", expire=window, nx=True)
                current = self._store.incr_key(key)
                if current == 1:
                    self._store.expire_key(key, window)
            except Exception as exc:
                logger.warning("Public rate limiter (%s) Redis error: %s", layer, exc)
                continue

            if current > limit:
                return PublicRateLimitResult(
                    allowed=False,
                    remaining=0,
                    limit=limit,
                    reset_at=now + window,
                    layer=layer,
                )

        return PublicRateLimitResult(
            allowed=True,
            remaining=max(0, _IP_LIMIT - self._get_count(f"{_PREFIX}:ip:{ip_hash}")),
            limit=_IP_LIMIT,
            reset_at=now + _IP_WINDOW,
        )

    def _get_count(self, key: str) -> int:
        try:
            raw = self._store.get_key(key)
            return int(raw) if raw else 0
        except Exception:
            return 0
