"""Tests for plan_checker — pure logic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lib.ai_foundation.agents.meal_analysis.contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
    MealSlot,
)
from lib.ai_foundation.agents.meal_analysis.plan_checker import (
    check_plan,
    _compute_deltas,
    _is_compliant,
)
from lib.schemas.patient_diet_plan import DietMealSlot, DietPlanContent


def _extraction(cal=500, carbs=60, protein=30, fat=20) -> MealExtraction:
    return MealExtraction(
        name="x",
        items=[
            ExtractedFoodItem(
                name="x",
                portion=1,
                unit="piece",
                macros=MacroSet(
                    calories=cal, carbs=carbs, protein=protein, fat=fat
                ),
                portion_confidence=ConfidenceLevel.HIGH,
            )
        ],
        total_macros=MacroSet(calories=cal, carbs=carbs, protein=protein, fat=fat),
        overall_confidence=ConfidenceLevel.HIGH,
    )


def _plan_with_slot(slot_name, *, calories=500, protein=30, carbs=60, fats=20):
    content = DietPlanContent(
        meals=[
            DietMealSlot(
                slot=slot_name,
                calories=calories,
                protein=protein,
                carbs=carbs,
                fats=fats,
            )
        ]
    )
    return SimpleNamespace(content=content)


class TestCheckPlan:
    def test_no_plan(self):
        pc = check_plan(
            extraction=_extraction(), slot=MealSlot.BREAKFAST, active_plan=None
        )
        assert pc.has_plan is False
        assert pc.slot == MealSlot.BREAKFAST

    def test_plan_without_slot_target(self):
        pc = check_plan(
            extraction=_extraction(),
            slot=MealSlot.DINNER,
            active_plan=_plan_with_slot("lunch"),
        )
        assert pc.has_plan is True
        assert pc.compliant is None

    def test_compliant(self):
        pc = check_plan(
            extraction=_extraction(),
            slot=MealSlot.BREAKFAST,
            active_plan=_plan_with_slot("breakfast"),
        )
        assert pc.has_plan is True
        assert pc.compliant is True
        assert pc.deviation_summary is None

    def test_over_calories(self):
        pc = check_plan(
            extraction=_extraction(cal=1000),  # 100% over 500 target
            slot=MealSlot.BREAKFAST,
            active_plan=_plan_with_slot("breakfast", calories=500),
        )
        assert pc.compliant is False
        assert "calories over" in (pc.deviation_summary or "")

    def test_plan_content_as_dict(self):
        plan = SimpleNamespace(
            content={
                "meals": [
                    {"slot": "breakfast", "calories": 500, "carbs": 60, "protein": 30, "fats": 20}
                ]
            }
        )
        pc = check_plan(
            extraction=_extraction(), slot=MealSlot.BREAKFAST, active_plan=plan
        )
        assert pc.compliant is True


class TestCompliantLogic:
    def test_within_tolerance(self):
        deltas = {
            "calories": {"actual": 500, "target": 500, "delta": 0, "delta_pct": 0},
            "carbs": {"actual": 60, "target": 60, "delta": 0, "delta_pct": 0},
            "protein": {"actual": 30, "target": 30, "delta": 0, "delta_pct": 0},
            "fats": {"actual": 20, "target": 20, "delta": 0, "delta_pct": 0},
        }
        assert _is_compliant(deltas) is True

    def test_carbs_50pct_over(self):
        deltas = {
            "calories": {"actual": 500, "target": 500, "delta": 0, "delta_pct": 0},
            "carbs": {"actual": 90, "target": 60, "delta": 30, "delta_pct": 0.5},
            "protein": {"actual": 30, "target": 30, "delta": 0, "delta_pct": 0},
            "fats": {"actual": 20, "target": 20, "delta": 0, "delta_pct": 0},
        }
        assert _is_compliant(deltas) is False
