"""Tests for NotificationBudget — daily cap with priority bypass."""

from unittest.mock import MagicMock, patch

import pytest


class FakeCacheStore:
    def __init__(self):
        self._data = {}

    def get_key(self, key):
        return self._data.get(key)

    def incr_key(self, key):
        self._data[key] = int(self._data.get(key) or 0) + 1
        return self._data[key]

    def expire_key(self, key, seconds):
        pass


class BrokenCacheStore:
    def get_key(self, key):
        raise ConnectionError("Redis is down")

    def incr_key(self, key):
        raise ConnectionError("Redis is down")

    def expire_key(self, key, seconds):
        raise ConnectionError("Redis is down")


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the module-level _cache before each test."""
    import lib.services.notification_budget as mod
    mod._cache = None
    yield
    mod._cache = None


@pytest.fixture
def budget_with_fake_redis():
    """Inject a fake Redis cache into the budget module."""
    import lib.services.notification_budget as mod
    fake = FakeCacheStore()
    mod._cache = fake
    return mod, fake


@pytest.fixture
def budget_with_broken_redis():
    """Inject a broken Redis cache."""
    import lib.services.notification_budget as mod
    mod._cache = BrokenCacheStore()
    return mod


class TestCanSend:
    def test_fresh_patient_can_send(self, budget_with_fake_redis):
        mod, _ = budget_with_fake_redis
        assert mod.can_send("patient-1", "streak_reminder") is True

    def test_at_cap_blocks_low_priority(self, budget_with_fake_redis):
        mod, fake = budget_with_fake_redis
        # Simulate 8 sends
        for _ in range(8):
            mod.record_sent("patient-1")
        assert mod.can_send("patient-1", "streak_reminder") is False
        assert mod.can_send("patient-1", "health_insight") is False
        assert mod.can_send("patient-1", "re_engagement") is False

    def test_at_cap_allows_medication_reminder(self, budget_with_fake_redis):
        mod, _ = budget_with_fake_redis
        for _ in range(8):
            mod.record_sent("patient-1")
        assert mod.can_send("patient-1", "medication_reminder") is True

    def test_all_always_send_types_bypass_cap(self, budget_with_fake_redis):
        mod, _ = budget_with_fake_redis
        for _ in range(10):
            mod.record_sent("patient-1")
        for notif_type in mod.ALWAYS_SEND:
            assert mod.can_send("patient-1", notif_type) is True

    def test_different_patients_independent(self, budget_with_fake_redis):
        mod, _ = budget_with_fake_redis
        for _ in range(8):
            mod.record_sent("patient-1")
        assert mod.can_send("patient-1", "streak_reminder") is False
        assert mod.can_send("patient-2", "streak_reminder") is True


class TestRecordSent:
    def test_increments_counter(self, budget_with_fake_redis):
        mod, _ = budget_with_fake_redis
        mod.record_sent("patient-1")
        mod.record_sent("patient-1")
        assert mod.can_send("patient-1", "streak_reminder") is True  # 2 < 8

    def test_reaches_cap(self, budget_with_fake_redis):
        mod, _ = budget_with_fake_redis
        for _ in range(8):
            mod.record_sent("patient-1")
        assert mod.can_send("patient-1", "streak_reminder") is False


class TestRedisFallback:
    def test_can_send_returns_true_when_redis_down(self, budget_with_broken_redis):
        mod = budget_with_broken_redis
        assert mod.can_send("patient-1", "streak_reminder") is True

    def test_record_sent_doesnt_crash_when_redis_down(self, budget_with_broken_redis):
        mod = budget_with_broken_redis
        mod.record_sent("patient-1")  # should not raise
