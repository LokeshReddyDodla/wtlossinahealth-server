"""Tests for ai_foundation.rate_limit.public_limiter.

This limiter is the ONLY guard on the anonymous product-bot endpoints, so
every layer and failure mode is locked:

- Three layers checked in order: ip → session → global
- First over-limit layer short-circuits with its name
- IP is sha256-hashed (privacy) — raw IP never reaches Redis keys
- Redis error on a layer skips that layer (fail-open) but checks the rest
- Allowed result reports remaining quota on the IP layer
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.rate_limit.public_limiter import (
    PublicRateLimiter,
    PublicRateLimitResult,
    _GLOBAL_LIMIT,
    _IP_LIMIT,
    _SESSION_LIMIT,
)


def _store(incr_value=1, raises=None):
    store = MagicMock()
    if raises:
        store.aset_key = AsyncMock(side_effect=raises)
        store.aincr_key = AsyncMock(side_effect=raises)
        store.aget_key = AsyncMock(side_effect=raises)
        store.aexpire_key = AsyncMock(side_effect=raises)
    else:
        store.aset_key = AsyncMock(return_value=True)
        store.aincr_key = AsyncMock(return_value=incr_value)
        store.aget_key = AsyncMock(return_value=str(incr_value))
        store.aexpire_key = AsyncMock(return_value=True)
    return store


class TestAllowedPath:
    @pytest.mark.asyncio
    async def test_under_all_limits_allows(self):
        limiter = PublicRateLimiter(_store(incr_value=1))
        result = await limiter.check_and_record("1.2.3.4", "sess_1")
        assert result.allowed is True
        assert result.layer == ""
        assert result.limit == _IP_LIMIT

    @pytest.mark.asyncio
    async def test_all_three_layers_checked(self):
        store = _store(incr_value=1)
        limiter = PublicRateLimiter(store)
        await limiter.check_and_record("1.2.3.4", "sess_1")
        keys = [c.args[0] for c in store.aincr_key.call_args_list]
        assert any(":ip:" in k for k in keys)
        assert any(":sess:" in k for k in keys)
        assert any(":global" in k for k in keys)

    @pytest.mark.asyncio
    async def test_remaining_reflects_ip_count(self):
        store = _store(incr_value=10)
        # aget_key returns "10" → remaining = _IP_LIMIT - 10 (but incr already
        # allowed since 10 <= limit)
        limiter = PublicRateLimiter(store)
        result = await limiter.check_and_record("1.2.3.4", "sess_1")
        assert result.allowed is True
        assert result.remaining == _IP_LIMIT - 10


class TestPrivacy:
    @pytest.mark.asyncio
    async def test_ip_is_hashed_in_key(self):
        store = _store()
        limiter = PublicRateLimiter(store)
        raw_ip = "203.0.113.99"
        await limiter.check_and_record(raw_ip, "sess_1")
        expected_hash = hashlib.sha256(raw_ip.encode()).hexdigest()[:16]
        keys = [c.args[0] for c in store.aincr_key.call_args_list]
        ip_keys = [k for k in keys if ":ip:" in k]
        assert ip_keys, "no IP-layer key used"
        assert expected_hash in ip_keys[0]
        assert raw_ip not in ip_keys[0]


class TestBlockedLayers:
    @pytest.mark.asyncio
    async def test_ip_layer_blocks_first(self):
        limiter = PublicRateLimiter(_store(incr_value=_IP_LIMIT + 1))
        result = await limiter.check_and_record("1.2.3.4", "sess_1")
        assert result.allowed is False
        assert result.layer == "ip"
        assert result.limit == _IP_LIMIT
        assert result.remaining == 0

    @pytest.mark.asyncio
    async def test_session_layer_blocks(self):
        store = MagicMock()
        store.aset_key = AsyncMock(return_value=True)
        store.aexpire_key = AsyncMock(return_value=True)
        # ip under limit, session over limit
        store.aincr_key = AsyncMock(side_effect=[1, _SESSION_LIMIT + 1])
        limiter = PublicRateLimiter(store)
        result = await limiter.check_and_record("1.2.3.4", "sess_1")
        assert result.allowed is False
        assert result.layer == "session"
        assert result.limit == _SESSION_LIMIT

    @pytest.mark.asyncio
    async def test_global_layer_blocks(self):
        store = MagicMock()
        store.aset_key = AsyncMock(return_value=True)
        store.aexpire_key = AsyncMock(return_value=True)
        store.aincr_key = AsyncMock(side_effect=[1, 1, _GLOBAL_LIMIT + 1])
        limiter = PublicRateLimiter(store)
        result = await limiter.check_and_record("1.2.3.4", "sess_1")
        assert result.allowed is False
        assert result.layer == "global"
        assert result.limit == _GLOBAL_LIMIT


class TestFailOpen:
    @pytest.mark.asyncio
    async def test_full_redis_outage_allows(self):
        limiter = PublicRateLimiter(_store(raises=Exception("Redis down")))
        result = await limiter.check_and_record("1.2.3.4", "sess_1")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_one_layer_error_still_checks_others(self):
        store = MagicMock()
        store.aset_key = AsyncMock(return_value=True)
        store.aexpire_key = AsyncMock(return_value=True)
        # ip layer raises, session layer over limit → still blocked by session
        store.aincr_key = AsyncMock(
            side_effect=[Exception("boom"), _SESSION_LIMIT + 1],
        )
        limiter = PublicRateLimiter(store)
        result = await limiter.check_and_record("1.2.3.4", "sess_1")
        assert result.allowed is False
        assert result.layer == "session"


class TestResultModel:
    def test_result_shape(self):
        result = PublicRateLimitResult(
            allowed=False, remaining=0, limit=500, reset_at=123.0, layer="ip",
        )
        assert result.layer == "ip"
        assert result.allowed is False
