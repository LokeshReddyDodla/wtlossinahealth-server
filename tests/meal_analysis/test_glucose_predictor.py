"""Tests for GlucosePredictor."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealAnalysisContext,
)
from lib.ai_foundation.agents.meal_analysis.contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
)
from lib.ai_foundation.agents.meal_analysis.glucose_predictor import (
    GlucosePredictor,
    _LLMGlucoseOut,
)


def _extraction() -> MealExtraction:
    return MealExtraction(
        name="x",
        items=[
            ExtractedFoodItem(
                name="x",
                portion=1,
                unit="piece",
                macros=MacroSet(calories=420, carbs=58, protein=9, fat=16),
                portion_confidence=ConfidenceLevel.HIGH,
            )
        ],
        total_macros=MacroSet(calories=420, carbs=58, protein=9, fat=16),
        overall_confidence=ConfidenceLevel.HIGH,
    )


def _deps(llm_return: _LLMGlucoseOut):
    gw = MagicMock()
    gw.extract = AsyncMock(return_value=(llm_return, MagicMock()))
    template = MagicMock()
    template.render = MagicMock(return_value="PROMPT")
    prompts = MagicMock()
    prompts.get = MagicMock(return_value=template)
    return gw, prompts


@pytest.mark.asyncio
async def test_returns_none_without_cgm():
    gw, prompts = _deps(_LLMGlucoseOut(skip=False))
    pred = GlucosePredictor(gateway=gw, prompt_registry=prompts)
    ctx = MealAnalysisContext(
        patient_id="p", local_now=datetime.utcnow(), has_cgm=False
    )
    out = await pred.predict(
        extraction=_extraction(), context=ctx, glycemic_load=25.5, slot="breakfast"
    )
    assert out is None
    gw.extract.assert_not_called()


@pytest.mark.asyncio
async def test_returns_none_on_skip():
    gw, prompts = _deps(_LLMGlucoseOut(skip=True))
    pred = GlucosePredictor(gateway=gw, prompt_registry=prompts)
    ctx = MealAnalysisContext(
        patient_id="p", local_now=datetime.utcnow(), has_cgm=True
    )
    out = await pred.predict(
        extraction=_extraction(), context=ctx, glycemic_load=25.5, slot="breakfast"
    )
    assert out is None


@pytest.mark.asyncio
async def test_returns_prediction_when_complete():
    gw, prompts = _deps(
        _LLMGlucoseOut(
            skip=False,
            range_mg_dl_low=150,
            range_mg_dl_high=185,
            peak_minutes_after=60,
            confidence=ConfidenceLevel.HIGH,
            n_similar_meals=4,
            evidence=[],
            rationale="based on 4 past paratha meals",
        )
    )
    pred = GlucosePredictor(gateway=gw, prompt_registry=prompts)
    ctx = MealAnalysisContext(
        patient_id="p", local_now=datetime.utcnow(), has_cgm=True
    )
    out = await pred.predict(
        extraction=_extraction(), context=ctx, glycemic_load=25.5, slot="breakfast"
    )
    assert out is not None
    assert out.range_mg_dl_low == 150
    assert out.range_mg_dl_high == 185
    assert out.confidence == ConfidenceLevel.HIGH


@pytest.mark.asyncio
async def test_returns_none_when_incomplete():
    gw, prompts = _deps(
        _LLMGlucoseOut(
            skip=False,
            range_mg_dl_low=150,
            # missing range_mg_dl_high, peak_minutes_after, confidence
        )
    )
    pred = GlucosePredictor(gateway=gw, prompt_registry=prompts)
    ctx = MealAnalysisContext(
        patient_id="p", local_now=datetime.utcnow(), has_cgm=True
    )
    out = await pred.predict(
        extraction=_extraction(), context=ctx, glycemic_load=25.5, slot="breakfast"
    )
    assert out is None
