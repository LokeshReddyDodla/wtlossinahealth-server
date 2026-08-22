"""Meal-preview shadow path: flag-off is a no-op; SAFETY never serves."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealAnalysisContext,
)
from lib.ai_foundation.agents.meal_analysis.contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    GlucosePrediction,
    MacroSet,
    MealExtraction,
)
from lib.ai_foundation.config import settings


def _extraction() -> MealExtraction:
    return MealExtraction(
        name="Aloo paratha",
        items=[
            ExtractedFoodItem(
                name="aloo paratha",
                portion=1,
                unit="piece",
                macros=MacroSet(calories=420, carbs=58, protein=9, fat=16),
                portion_confidence=ConfidenceLevel.HIGH,
            )
        ],
        total_macros=MacroSet(calories=420, carbs=58, protein=9, fat=16),
        overall_confidence=ConfidenceLevel.HIGH,
    )


def _llm_prediction() -> GlucosePrediction:
    return GlucosePrediction(
        range_mg_dl_low=150,
        range_mg_dl_high=180,
        peak_minutes_after=60,
        confidence=ConfidenceLevel.HIGH,
        n_similar_meals=3,
        rationale="based on past meals",
    )


def test_brain_shadow_flag_defaults_off():
    assert settings.BRAIN_SHADOW_ENABLED is False


def _agent(glucose: MagicMock) -> MealAnalysisAgent:
    return MealAnalysisAgent(
        gateway=MagicMock(),
        qdrant_retriever=MagicMock(),
        context_loader=MagicMock(),
        extractor=MagicMock(),
        scorer=MagicMock(),
        alternatives=MagicMock(),
        glucose_predictor=glucose,
    )


@pytest.mark.asyncio
async def test_flag_off_leaves_llm_serving_path(monkeypatch):
    """Default-off: assess is not called; LLM prediction is what serves."""
    monkeypatch.setattr(settings, "BRAIN_SHADOW_ENABLED", False)

    def _should_not_run(*_a, **_k):
        raise AssertionError("assess must not run when shadow flag is off")

    # Patch the function maybe_shadow_brain would import only if enabled.
    monkeypatch.setattr(
        "lib.ai_foundation.clinical.aihealth_brain.assess",
        _should_not_run,
    )

    glucose = MagicMock()
    llm = _llm_prediction()
    glucose.predict = AsyncMock(return_value=llm)

    ctx = MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
        has_cgm=True,
    )
    out = await _agent(glucose)._predict_glucose(
        patient_id="p1",
        extraction=_extraction(),
        context=ctx,
        glycemic_load=32.0,
        slot="breakfast",
        trace_id="t1",
        meal_hour=8,
    )

    assert out is llm
    assert out.range_mg_dl_low == 150
    assert out.range_mg_dl_high == 180
    assert out.rationale == "based on past meals"
    glucose.predict.assert_awaited_once()


@pytest.mark.asyncio
async def test_flag_on_safety_does_not_replace_llm(monkeypatch, caplog):
    """Shadow SAFETY + protein_first must not become the served prediction."""
    monkeypatch.setattr(settings, "BRAIN_SHADOW_ENABLED", True)

    def _leaky_safety(_state, _meal):
        return {
            "output_mode": "SAFETY",
            "lever": {"name": "protein_first", "say": "dal first"},
            "safety_flags": ["PRE_HYPO"],
            "prediction": {"rise_mgdl": 12},
        }

    monkeypatch.setattr(
        "lib.ai_foundation.clinical.aihealth_brain._load_pin_assess",
        lambda: None,
    )
    monkeypatch.setattr(
        "lib.ai_foundation.clinical.aihealth_brain._metabolic_assess",
        _leaky_safety,
    )

    glucose = MagicMock()
    llm = _llm_prediction()
    glucose.predict = AsyncMock(return_value=llm)
    ctx = MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
        has_cgm=True,
        cgm_events=[{"peak_value": 70, "start_time": 1}],
    )

    with caplog.at_level("INFO"):
        out = await _agent(glucose)._predict_glucose(
            patient_id="p1",
            extraction=_extraction(),
            context=ctx,
            glycemic_load=32.0,
            slot="breakfast",
            trace_id="t1",
            meal_hour=8,
        )

    assert out is llm
    assert out.rationale == "based on past meals"
    shadow_lines = [r.message for r in caplog.records if "brain_shadow" in r.message]
    assert shadow_lines
    assert all("protein_first" not in line for line in shadow_lines)


@pytest.mark.asyncio
async def test_flag_on_brain_throw_keeps_llm(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SHADOW_ENABLED", True)

    def _boom(_state, _meal):
        raise RuntimeError("pin exploded")

    monkeypatch.setattr(
        "lib.ai_foundation.clinical.aihealth_brain._load_pin_assess",
        lambda: None,
    )
    monkeypatch.setattr(
        "lib.ai_foundation.clinical.aihealth_brain._metabolic_assess",
        _boom,
    )

    glucose = MagicMock()
    llm = _llm_prediction()
    glucose.predict = AsyncMock(return_value=llm)
    ctx = MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
        has_cgm=True,
    )
    out = await _agent(glucose)._predict_glucose(
        patient_id="p1",
        extraction=_extraction(),
        context=ctx,
        glycemic_load=32.0,
        slot="breakfast",
        trace_id="t1",
        meal_hour=8,
    )
    assert out is llm
    glucose.predict.assert_awaited_once()
