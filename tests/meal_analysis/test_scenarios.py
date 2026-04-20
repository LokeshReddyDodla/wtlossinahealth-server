"""
Scenario tests — the canonical user stories we aligned on during design.

Each scenario mocks only the minimal seam it needs and asserts on the
behaviour promised in the plan.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent


def _noop_gateway() -> MagicMock:
    gw = MagicMock()
    gw.set_langfuse_context = MagicMock(return_value=None)
    gw.langfuse_trace_input = MagicMock(return_value=None)
    gw.langfuse_trace_output = MagicMock(return_value=None)
    return gw
from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealAnalysisContext,
)
from lib.ai_foundation.agents.meal_analysis.contracts import (
    Alternative,
    AlternativeSource,
    ConfidenceLevel,
    ExtractedFoodItem,
    GlucosePrediction,
    MacroSet,
    MealEvidenceRef,
    MealExtraction,
    MealPreviewRequest,
    MealScore,
    MealSlot,
    MealSource,
    PatientMealRef,
    RepeatSuggestion,
)


# ── shared helpers ────────────────────────────────────────────────────────


def _paratha_extraction() -> MealExtraction:
    return MealExtraction(
        name="Aloo paratha with curd",
        items=[
            ExtractedFoodItem(
                name="aloo paratha",
                portion=2,
                unit="piece",
                macros=MacroSet(calories=840, carbs=116, fiber=8, protein=18, fat=32),
                portion_confidence=ConfidenceLevel.HIGH,
                tags=["high_carb", "fried"],
            )
        ],
        total_macros=MacroSet(calories=840, carbs=116, fiber=8, protein=18, fat=32),
        overall_confidence=ConfidenceLevel.HIGH,
    )


def _make_agent(
    *,
    context: MealAnalysisContext,
    extraction: MealExtraction,
    score: MealScore,
    alts: list[Alternative],
    glucose: GlucosePrediction | None,
) -> MealAnalysisAgent:
    ctx_loader = MagicMock()
    ctx_loader.load = AsyncMock(return_value=context)

    extractor = MagicMock()
    extractor.extract = AsyncMock(return_value=extraction)

    scorer = MagicMock()
    scorer.score = AsyncMock(return_value=score)

    alternatives = MagicMock()
    alternatives.rank = AsyncMock(return_value=(alts, []))

    glucose_pred = MagicMock()
    glucose_pred.predict = AsyncMock(return_value=glucose)

    return MealAnalysisAgent(
        gateway=_noop_gateway(),
        qdrant_retriever=MagicMock(),
        context_loader=ctx_loader,
        extractor=extractor,
        scorer=scorer,
        alternatives=alternatives,
        glucose_predictor=glucose_pred,
    )


# ── scenarios ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_priya_hero_case():
    """Priya — T2 diabetic with CGM + history. Should get history-sourced
    alternatives and a glucose prediction."""
    ctx = MealAnalysisContext(
        patient_id="priya",
        local_now=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
        has_cgm=True,
        profile={"first_name": "Priya", "locale": "en_IN"},
    )

    history_alt = Alternative(
        item_to_replace="aloo paratha",
        swap_with="besan chilla",
        reason="kept glucose below 135 twice last week",
        predicted_glucose_delta=-35,
        source=AlternativeSource.HISTORY,
        frequency_in_history=4,
        evidence=[
            MealEvidenceRef(
                meal_id=uuid.uuid4(),
                meal_name="Besan chilla with mint chutney",
                consumed_at=datetime(2026, 4, 15, 8, 30),
                glucose_peak=132,
                glucose_peak_minutes_after=60,
            )
        ],
    )
    prediction = GlucosePrediction(
        range_mg_dl_low=170,
        range_mg_dl_high=190,
        peak_minutes_after=60,
        confidence=ConfidenceLevel.HIGH,
        n_similar_meals=4,
        rationale="peaked above 180 in 4 of 4 similar past meals",
    )

    agent = _make_agent(
        context=ctx,
        extraction=_paratha_extraction(),
        score=MealScore(overall=45, glycemic_load=59.4, concerns=["high carbs"]),
        alts=[history_alt],
        glucose=prediction,
    )
    req = MealPreviewRequest(
        slot=MealSlot.BREAKFAST,
        source=MealSource.PHOTO,
        consumed_at=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
        image_url="http://x/priya.jpg",
    )
    result = await agent.analyze(patient_id="priya", request=req)

    assert result.predicted_glucose is not None
    assert result.predicted_glucose.confidence == ConfidenceLevel.HIGH
    assert any(a.source == AlternativeSource.HISTORY for a in result.alternatives)
    assert result.alternatives[0].evidence


@pytest.mark.asyncio
async def test_rahul_cold_start_no_cgm():
    """Rahul — day 3, no CGM, no history. Gets guideline-sourced alternatives
    and no glucose prediction."""
    ctx = MealAnalysisContext(
        patient_id="rahul",
        local_now=datetime(2026, 4, 20, 13, 0, tzinfo=timezone.utc),
        has_cgm=False,
        recent_meals=[],
    )
    alt = Alternative(
        item_to_replace="biryani",
        swap_with="brown rice pulao with raita",
        reason="similar cuisine, lower simple carbs",
        source=AlternativeSource.GUIDELINE,
    )
    agent = _make_agent(
        context=ctx,
        extraction=_paratha_extraction(),
        score=MealScore(overall=50, glycemic_load=40.0),
        alts=[alt],
        glucose=None,
    )
    req = MealPreviewRequest(
        slot=MealSlot.LUNCH,
        source=MealSource.PHOTO,
        consumed_at=datetime(2026, 4, 20, 13, 0, tzinfo=timezone.utc),
        image_url="http://x/rahul.jpg",
    )
    result = await agent.analyze(patient_id="rahul", request=req)

    assert result.predicted_glucose is None
    assert all(a.source == AlternativeSource.GUIDELINE for a in result.alternatives)


@pytest.mark.asyncio
async def test_pre_emptive_check_no_consumed_at():
    """User at restaurant — hasn't eaten yet. consumed_at is None."""
    ctx = MealAnalysisContext(
        patient_id="x",
        local_now=datetime(2026, 4, 20, 19, 0, tzinfo=timezone.utc),
    )
    agent = _make_agent(
        context=ctx,
        extraction=_paratha_extraction(),
        score=MealScore(overall=55, glycemic_load=30.0),
        alts=[],
        glucose=None,
    )
    req = MealPreviewRequest(
        slot=MealSlot.DINNER,
        source=MealSource.PHOTO,
        image_url="http://x/menu.jpg",
        consumed_at=None,  # pre-emptive
    )
    result = await agent.analyze(patient_id="x", request=req)
    assert result.extraction.name == "Aloo paratha with curd"


@pytest.mark.asyncio
async def test_slot_collision_flagged():
    """User already logged breakfast; uploads breakfast again."""
    existing_breakfast = PatientMealRef(
        meal_id=uuid.uuid4(),
        meal_name="Idli sambar",
        consumed_at=datetime(2026, 4, 20, 8, 0),
        slot=MealSlot.BREAKFAST,
    )
    ctx = MealAnalysisContext(
        patient_id="x",
        local_now=datetime(2026, 4, 20, 10, 30, tzinfo=timezone.utc),
        today_meals_by_slot={MealSlot.BREAKFAST: [existing_breakfast]},
    )
    agent = _make_agent(
        context=ctx,
        extraction=_paratha_extraction(),
        score=MealScore(overall=50, glycemic_load=40.0),
        alts=[],
        glucose=None,
    )
    req = MealPreviewRequest(
        slot=MealSlot.BREAKFAST,
        source=MealSource.PHOTO,
        image_url="http://x/2nd-breakfast.jpg",
    )
    result = await agent.analyze(patient_id="x", request=req)

    assert result.repeat.already_logged_this_slot_today is True
    assert result.repeat.suggestion == RepeatSuggestion.ASK_CONFIRM
    assert result.repeat.same_slot_meal_today == existing_breakfast
