"""Tests for AlternativesEngine."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.meal_analysis.alternatives import (
    AlternativesEngine,
    _LLMAlternativesOut,
    _prep_recent_meals,
)
from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealAnalysisContext,
)
from lib.ai_foundation.agents.meal_analysis.contracts import (
    Alternative,
    AlternativeSource,
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
    Pairing,
    PairingBenefit,
)


def _extraction() -> MealExtraction:
    return MealExtraction(
        name="Aloo paratha with curd",
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


class TestPrepRecent:
    def test_trims_fields(self):
        out = _prep_recent_meals([{"name": "x", "items": [{"name": "a", "serving_quantity": 1, "ignored": True}]}])
        assert "ignored" not in out[0]["items"][0]

    def test_respects_limit(self):
        from lib.ai_foundation.config import settings as _s
        many = [{"name": f"m{i}"} for i in range(50)]
        out = _prep_recent_meals(many)
        assert len(out) == _s.MEAL_PROMPT_RECENT_MEALS_LIMIT


@pytest.mark.asyncio
async def test_rank_returns_llm_output():
    out = _LLMAlternativesOut(
        alternatives=[
            Alternative(
                item_to_replace="aloo paratha",
                swap_with="moong dosa",
                reason="kept glucose below 135 twice last week",
                predicted_glucose_delta=-30,
                source=AlternativeSource.HISTORY,
                frequency_in_history=2,
            )
        ],
        pairings=[
            Pairing(
                add="salad with lemon", reason="fiber helps blunt spike", benefit=PairingBenefit.FIBER
            )
        ],
    )
    gw = MagicMock()
    gw.extract = AsyncMock(return_value=(out, MagicMock()))

    template = MagicMock()
    template.render = MagicMock(return_value="PROMPT")
    prompts = MagicMock()
    prompts.get = MagicMock(return_value=template)

    engine = AlternativesEngine(gateway=gw, prompt_registry=prompts)
    ctx = MealAnalysisContext(patient_id="p", local_now=datetime.utcnow())
    alts, pairs = await engine.rank(
        extraction=_extraction(), context=ctx, glycemic_load=25.5, slot="breakfast"
    )
    assert len(alts) == 1
    assert alts[0].source == AlternativeSource.HISTORY
    assert len(pairs) == 1
    assert pairs[0].benefit == PairingBenefit.FIBER


@pytest.mark.asyncio
async def test_cold_start_empty_history_still_works():
    out = _LLMAlternativesOut(
        alternatives=[
            Alternative(
                item_to_replace="aloo paratha",
                swap_with="besan chilla",
                reason="higher protein, similar culture, lower GI",
                source=AlternativeSource.GUIDELINE,
            )
        ],
        pairings=[],
    )
    gw = MagicMock()
    gw.extract = AsyncMock(return_value=(out, MagicMock()))
    template = MagicMock()
    template.render = MagicMock(return_value="PROMPT")
    prompts = MagicMock()
    prompts.get = MagicMock(return_value=template)

    engine = AlternativesEngine(gateway=gw, prompt_registry=prompts)
    ctx = MealAnalysisContext(
        patient_id="p",
        local_now=datetime.utcnow(),
        recent_meals=[],  # cold start
    )
    alts, _ = await engine.rank(
        extraction=_extraction(), context=ctx, glycemic_load=25.5, slot="breakfast"
    )
    assert alts[0].source == AlternativeSource.GUIDELINE
