"""Unit tests for XP logic — multiplier, levels, daily cap.

Uses stub-loading for modules that need sqlalchemy. Tests pure functions
directly, and uses _load_module for grant_xp tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tests.test_gamification_unit_logic import _base_stubs, _load_module


MODULE_PATH = "lib/services/gamification/xp_service.py"
MODULE_NAME = "test_xp_service"


@pytest.fixture
def xp_module(monkeypatch):
    return _load_module(monkeypatch, MODULE_PATH, MODULE_NAME, _base_stubs())


class TestStreakMultiplier:
    def test_zero(self, xp_module):
        assert xp_module.streak_multiplier(0) == 1.0

    def test_below_7(self, xp_module):
        assert xp_module.streak_multiplier(6) == 1.0

    def test_breakpoints(self, xp_module):
        assert xp_module.streak_multiplier(7) == 1.1
        assert xp_module.streak_multiplier(14) == 1.2
        assert xp_module.streak_multiplier(30) == 1.3
        assert xp_module.streak_multiplier(60) == 1.4
        assert xp_module.streak_multiplier(90) == 1.5

    def test_above_90_capped(self, xp_module):
        assert xp_module.streak_multiplier(365) == 1.5

    def test_between_breakpoints(self, xp_module):
        assert xp_module.streak_multiplier(20) == 1.2


class TestLevelFromXP:
    def test_zero_is_level_1(self, xp_module):
        assert xp_module.level_from_xp(0) == 1

    def test_negative_is_level_1(self, xp_module):
        assert xp_module.level_from_xp(-100) == 1

    def test_exact_threshold(self, xp_module):
        xp_5 = xp_module.xp_for_level(5)
        assert xp_module.level_from_xp(xp_5) == 5

    def test_just_below_threshold(self, xp_module):
        xp_5 = xp_module.xp_for_level(5)
        assert xp_module.level_from_xp(xp_5 - 1) == 4

    def test_max_level_capped(self, xp_module):
        assert xp_module.level_from_xp(999_999_999) == xp_module.MAX_LEVEL

    def test_monotonic(self, xp_module):
        prev = 1
        for xp in range(0, 50_000, 500):
            level = xp_module.level_from_xp(xp)
            assert level >= prev
            prev = level


class TestXPForLevel:
    def test_level_1_is_zero(self, xp_module):
        assert xp_module.xp_for_level(1) == 0

    def test_level_2_positive(self, xp_module):
        assert xp_module.xp_for_level(2) > 0

    def test_monotonic(self, xp_module):
        for lvl in range(1, 50):
            assert xp_module.xp_for_level(lvl + 1) > xp_module.xp_for_level(lvl)
