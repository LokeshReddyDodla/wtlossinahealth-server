"""Tests for repeat_detector."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealAnalysisContext,
)
from lib.ai_foundation.agents.meal_analysis.contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
    MealSlot,
    PatientMealRef,
    RepeatSuggestion,
)
from lib.ai_foundation.agents.meal_analysis.repeat_detector import (
    _count_in_last_days,
    _item_overlap,
    _names_match,
    _suggest,
    detect_repeat,
)


def _extraction(name="Aloo paratha", items=("aloo paratha", "curd")) -> MealExtraction:
    return MealExtraction(
        name=name,
        items=[
            ExtractedFoodItem(
                name=n,
                portion=1,
                unit="piece",
                macros=MacroSet(calories=100, carbs=20, protein=5, fat=3),
                portion_confidence=ConfidenceLevel.HIGH,
            )
            for n in items
        ],
        total_macros=MacroSet(calories=100, carbs=20, protein=5, fat=3),
        overall_confidence=ConfidenceLevel.HIGH,
    )


def _ctx(today_meals=None, recent=None) -> MealAnalysisContext:
    return MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 8, 45),
        today_meals_by_slot=today_meals or {},
        recent_meals=recent or [],
    )


def _prev_meal(
    name="Aloo paratha",
    items=("aloo paratha",),
    days_ago=1,
    slot="breakfast",
):
    consumed_at = (datetime(2026, 4, 20, 8, 45) - timedelta(days=days_ago)).isoformat()
    return {
        "meal_id": str(uuid.uuid4()),
        "name": name,
        "consumed_at": consumed_at,
        "slot": slot,
        "items": [{"name": n} for n in items],
    }


class TestNamesMatch:
    def test_exact_name(self):
        assert _names_match(_extraction("Paratha"), {"name": "paratha", "items": []})

    def test_item_overlap_when_name_differs(self):
        assert _names_match(
            _extraction("A", items=("egg", "toast")),
            {"name": "B", "items": [{"name": "egg"}, {"name": "toast"}]},
        )


class TestItemOverlap:
    def test_empty_sides(self):
        assert _item_overlap(_extraction(items=()), {"items": []}) == 0.0

    def test_full_overlap(self):
        ov = _item_overlap(
            _extraction(items=("a", "b")),
            {"items": [{"name": "a"}, {"name": "b"}]},
        )
        assert ov == 1.0


class TestCountInLastDays:
    def test_counts_matches_only(self):
        n = _count_in_last_days(
            extraction=_extraction(),
            recent_meals=[
                _prev_meal(days_ago=1),
                _prev_meal(days_ago=2),
                _prev_meal(name="Dosa", items=("dosa",), days_ago=3),
            ],
            now=datetime(2026, 4, 20, 8, 45),
            days=7,
        )
        assert n == 2

    def test_outside_window_excluded(self):
        n = _count_in_last_days(
            extraction=_extraction(),
            recent_meals=[_prev_meal(days_ago=10)],
            now=datetime(2026, 4, 20, 8, 45),
            days=7,
        )
        assert n == 0


class TestSuggest:
    def test_collision_wins(self):
        assert _suggest(
            slot_collision=True, same_as_prev=True, count_7d=5
        ) == RepeatSuggestion.ASK_CONFIRM

    def test_log_again_when_3_plus(self):
        assert _suggest(
            slot_collision=False, same_as_prev=True, count_7d=3
        ) == RepeatSuggestion.LOG_AGAIN

    def test_none_default(self):
        assert _suggest(
            slot_collision=False, same_as_prev=False, count_7d=0
        ) == RepeatSuggestion.NONE


class TestDetectRepeatIntegration:
    def test_slot_collision_flag(self):
        today = {
            MealSlot.BREAKFAST: [
                PatientMealRef(
                    meal_id=uuid.uuid4(),
                    meal_name="Idli",
                    consumed_at=datetime(2026, 4, 20, 8, 0),
                    slot=MealSlot.BREAKFAST,
                )
            ]
        }
        rf = detect_repeat(
            extraction=_extraction(),
            context=_ctx(today_meals=today),
            slot=MealSlot.BREAKFAST,
        )
        assert rf.already_logged_this_slot_today is True
        assert rf.suggestion == RepeatSuggestion.ASK_CONFIRM

    def test_frequency_drives_log_again(self):
        rf = detect_repeat(
            extraction=_extraction(),
            context=_ctx(
                recent=[
                    _prev_meal(days_ago=1),
                    _prev_meal(days_ago=3),
                    _prev_meal(days_ago=5),
                ]
            ),
            slot=MealSlot.LUNCH,
        )
        assert rf.same_meal_count_last_7d == 3
        assert rf.suggestion == RepeatSuggestion.LOG_AGAIN

    def test_cold_start_empty(self):
        rf = detect_repeat(
            extraction=_extraction(),
            context=_ctx(),
            slot=MealSlot.BREAKFAST,
        )
        assert rf.already_logged_this_slot_today is False
        assert rf.same_as_previous_meal is None
        assert rf.same_meal_count_last_7d == 0
        assert rf.suggestion == RepeatSuggestion.NONE
