"""Tests for ai_foundation.rate_limit.limiter — closes a current coverage gap.

The rate limiter is a critical guardrail (per-tenant throttling, priority-aware,
fail-open on Redis errors) but had no dedicated test file. This locks every
branch of check_and_record / check / record:

- All 4 priority limits + default fallback
- Allowed → not allowed transition at the boundary
- enabled=False short-circuit (always allow)
- Redis exception fail-open
- Key construction format (tenant + priority)
- Race semantics: TTL set after first INCR
- Backwards-compat check() vs check_and_record()
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lib.ai_foundation.agents.state import RequestPriority
from lib.ai_foundation.rate_limit.limiter import (
    DEFAULT_LIMITS,
    RateLimitConfig,
    RateLimiter,
    RateLimitResult,
)


# ── Cache store mock ────────────────────────────────────────────────────────


def _store(get_value=None, incr_value=1, set_returns=True, raises=None):
    """Build a CacheStore mock with configurable return values."""
    store = MagicMock()
    if raises:
        store.set_key = MagicMock(side_effect=raises)
        store.incr_key = MagicMock(side_effect=raises)
        store.get_key = MagicMock(side_effect=raises)
        store.expire_key = MagicMock(side_effect=raises)
    else:
        store.set_key = MagicMock(return_value=set_returns)
        store.incr_key = MagicMock(return_value=incr_value)
        store.get_key = MagicMock(return_value=get_value)
        store.expire_key = MagicMock(return_value=True)
    return store


# ── check_and_record happy path ─────────────────────────────────────────────


class TestCheckAndRecordHappy:
    @pytest.mark.parametrize(
        "priority,expected_limit",
        [
            (RequestPriority.CRITICAL, 10_000),
            (RequestPriority.HIGH, 5_000),
            (RequestPriority.NORMAL, 1_000),
            (RequestPriority.LOW, 500),
        ],
    )
    def test_default_limits_per_priority(self, priority, expected_limit):
        store = _store(incr_value=1)
        limiter = RateLimiter(store)
        result = limiter.check_and_record("tenant_a", priority)
        assert result.allowed is True
        assert result.limit == expected_limit
        assert result.remaining == expected_limit - 1

    def test_first_call_initializes_with_ttl(self):
        store = _store(incr_value=1)
        limiter = RateLimiter(store)
        limiter.check_and_record("tenant_a", RequestPriority.NORMAL)
        # set_key called with NX
        store.set_key.assert_called_once()
        call = store.set_key.call_args
        assert call.kwargs.get("nx") is True
        assert call.kwargs.get("expire") == 3600
        # incr_key called once
        store.incr_key.assert_called_once()
        # When current == 1, expire_key called to ensure TTL
        store.expire_key.assert_called_once()

    def test_subsequent_call_does_not_re_expire(self):
        store = _store(incr_value=42)
        limiter = RateLimiter(store)
        limiter.check_and_record("tenant_a", RequestPriority.NORMAL)
        # Not the first call (incr returned 42) — no re-expire
        store.expire_key.assert_not_called()


# ── Boundary semantics ──────────────────────────────────────────────────────


class TestBoundary:
    @pytest.mark.parametrize(
        "incr_value,expected_allowed,expected_remaining",
        [
            (1, True, 999),
            (500, True, 500),
            (999, True, 1),
            (1000, True, 0),       # exactly at limit — still allowed
            (1001, False, 0),      # over limit — rejected
            (5000, False, 0),
        ],
    )
    def test_at_and_over_limit(
        self, incr_value, expected_allowed, expected_remaining,
    ):
        store = _store(incr_value=incr_value)
        limiter = RateLimiter(store)
        result = limiter.check_and_record("t1", RequestPriority.NORMAL)
        assert result.allowed is expected_allowed
        assert result.remaining == expected_remaining


# ── enabled=False short-circuit ─────────────────────────────────────────────


class TestEnabledFlag:
    def test_disabled_always_allows(self):
        store = _store()
        limiter = RateLimiter(store, enabled=False)
        result = limiter.check_and_record("t1", RequestPriority.NORMAL)
        assert result.allowed is True
        # No Redis interaction
        store.set_key.assert_not_called()
        store.incr_key.assert_not_called()

    def test_disabled_check_does_not_hit_redis(self):
        store = _store()
        limiter = RateLimiter(store, enabled=False)
        result = limiter.check("t1", RequestPriority.LOW)
        assert result.allowed is True
        store.get_key.assert_not_called()

    def test_disabled_record_is_noop(self):
        store = _store()
        limiter = RateLimiter(store, enabled=False)
        limiter.record("t1", RequestPriority.NORMAL)
        store.set_key.assert_not_called()
        store.incr_key.assert_not_called()

    def test_runtime_toggle(self):
        store = _store()
        limiter = RateLimiter(store, enabled=True)
        assert limiter.enabled is True
        limiter.enabled = False
        assert limiter.enabled is False
        result = limiter.check_and_record("t1", RequestPriority.NORMAL)
        store.set_key.assert_not_called()
        assert result.allowed is True


# ── Fail-open on Redis exception ───────────────────────────────────────────


class TestFailOpen:
    def test_check_and_record_fails_open(self):
        store = _store(raises=Exception("Redis down"))
        limiter = RateLimiter(store)
        result = limiter.check_and_record("t1", RequestPriority.NORMAL)
        # Per source: failure path returns allowed=True with full quota
        assert result.allowed is True
        assert result.remaining == 1000
        assert result.limit == 1000

    def test_check_fails_open_to_zero_count(self):
        store = MagicMock()
        store.get_key = MagicMock(side_effect=Exception("Redis down"))
        limiter = RateLimiter(store)
        result = limiter.check("t1", RequestPriority.NORMAL)
        # On exception, current is treated as 0
        assert result.allowed is True
        assert result.remaining == 1000

    def test_record_swallows_exception(self):
        store = _store(raises=Exception("Redis down"))
        limiter = RateLimiter(store)
        limiter.record("t1", RequestPriority.NORMAL)  # should not raise


# ── Key construction ────────────────────────────────────────────────────────


class TestKeyConstruction:
    @pytest.mark.parametrize(
        "tenant_id,priority,expected_key",
        [
            ("t1", RequestPriority.CRITICAL, "rl:t1:critical"),
            ("t1", RequestPriority.HIGH, "rl:t1:high"),
            ("t1", RequestPriority.NORMAL, "rl:t1:normal"),
            ("t1", RequestPriority.LOW, "rl:t1:low"),
            ("facility-abc", RequestPriority.NORMAL, "rl:facility-abc:normal"),
            ("user_42", RequestPriority.LOW, "rl:user_42:low"),
        ],
    )
    def test_build_key(self, tenant_id, priority, expected_key):
        assert RateLimiter._build_key(tenant_id, priority) == expected_key

    def test_tenant_isolation(self):
        """Different tenants get different keys → independent counters."""
        store = _store(incr_value=1)
        limiter = RateLimiter(store)

        limiter.check_and_record("tenant_a", RequestPriority.NORMAL)
        limiter.check_and_record("tenant_b", RequestPriority.NORMAL)

        # Two different keys passed to set_key
        keys_used = {c.args[0] for c in store.set_key.call_args_list}
        assert "rl:tenant_a:normal" in keys_used
        assert "rl:tenant_b:normal" in keys_used


# ── Custom limits override ──────────────────────────────────────────────────


class TestCustomLimits:
    def test_custom_limit_overrides_default(self):
        custom = {
            RequestPriority.NORMAL: RateLimitConfig(
                max_requests=50, window_seconds=60,
            ),
        }
        store = _store(incr_value=1)
        limiter = RateLimiter(store, limits=custom)
        result = limiter.check_and_record("t1", RequestPriority.NORMAL)
        assert result.limit == 50
        assert result.remaining == 49

    def test_unknown_priority_falls_back_to_normal(self):
        """If a priority isn't in the limits dict, defaults to NORMAL."""
        custom = {
            RequestPriority.NORMAL: RateLimitConfig(max_requests=42),
        }
        store = _store(incr_value=1)
        limiter = RateLimiter(store, limits=custom)
        # CRITICAL not in custom dict → fall back via DEFAULT_LIMITS[NORMAL]=1000
        result = limiter.check_and_record("t1", RequestPriority.CRITICAL)
        assert result.limit == 1000


# ── check() (read-only) ────────────────────────────────────────────────────


class TestReadOnlyCheck:
    def test_check_does_not_increment(self):
        store = _store(get_value="42")
        limiter = RateLimiter(store)
        result = limiter.check("t1", RequestPriority.NORMAL)
        assert result.remaining == 1000 - 42
        assert result.allowed is True
        # No incr or set called
        store.incr_key.assert_not_called()
        store.set_key.assert_not_called()

    def test_check_returns_zero_if_key_missing(self):
        store = _store(get_value=None)
        limiter = RateLimiter(store)
        result = limiter.check("t1", RequestPriority.NORMAL)
        assert result.remaining == 1000
        assert result.allowed is True

    @pytest.mark.parametrize(
        "raw_value,expected_allowed",
        [
            ("0", True),
            ("999", True),
            ("1000", False),     # exactly at limit — check() rejects (strictly less than)
            ("1500", False),
        ],
    )
    def test_check_boundary(self, raw_value, expected_allowed):
        store = _store(get_value=raw_value)
        limiter = RateLimiter(store)
        result = limiter.check("t1", RequestPriority.NORMAL)
        assert result.allowed is expected_allowed
