"""Shared fixtures for meal_analysis tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.meal_analysis.contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
    MealSlot,
    MealSource,
)


@pytest.fixture
def patient_id() -> str:
    return "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def local_now() -> datetime:
    return datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc)


@pytest.fixture
def sample_extraction() -> MealExtraction:
    return MealExtraction(
        name="Aloo paratha with curd",
        items=[
            ExtractedFoodItem(
                name="Aloo paratha",
                portion=2,
                unit="piece",
                macros=MacroSet(
                    calories=420,
                    carbs=58,
                    carbs_simple=8,
                    carbs_complex=50,
                    fiber=4,
                    protein=9,
                    fat=16,
                ),
                portion_confidence=ConfidenceLevel.HIGH,
                tags=["high_carb", "fried"],
            ),
            ExtractedFoodItem(
                name="Curd",
                portion=100,
                unit="g",
                macros=MacroSet(
                    calories=62, carbs=5, carbs_simple=5, protein=3.5, fat=3
                ),
                portion_confidence=ConfidenceLevel.HIGH,
                tags=["dairy", "probiotic"],
            ),
        ],
        total_macros=MacroSet(
            calories=482,
            carbs=63,
            carbs_simple=13,
            carbs_complex=50,
            fiber=4,
            protein=12.5,
            fat=19,
        ),
        tags=["high_carb", "indian"],
        cuisine="Indian",
        overall_confidence=ConfidenceLevel.HIGH,
    )


@pytest.fixture
def mock_profile_service() -> MagicMock:
    svc = MagicMock()
    svc.fetch_patient_profile = AsyncMock(
        return_value=MagicMock(
            patient_id="p1",
            first_name="Priya",
            date_of_birth=None,
            gender="female",
            height=162,
            weight=68,
            locale="en_IN",
            timezone="Asia/Kolkata",
        )
    )
    return svc


@pytest.fixture
def mock_diet_plan_service() -> MagicMock:
    svc = MagicMock()
    svc.get_active_diet_plan = AsyncMock(return_value=None)
    return svc


@pytest.fixture
def mock_memory_store() -> MagicMock:
    store = MagicMock()
    store.get_patient_facts = AsyncMock(return_value=[])
    return store


@pytest.fixture
def preview_request_kwargs():
    return dict(
        slot=MealSlot.BREAKFAST,
        source=MealSource.PHOTO,
        consumed_at=datetime(2026, 4, 20, 8, 45),
    )
