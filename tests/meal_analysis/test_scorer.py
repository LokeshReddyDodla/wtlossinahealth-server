"""Tests for MealScorer — deterministic GL + LLM concerns/positives."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.meal_analysis.contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
)
from lib.ai_foundation.agents.meal_analysis.scorer import (
    MealScorer,
    _gi_for,
    _LLMScoreOut,
    estimate_glycemic_load,
)


def _item(carbs=50, fiber=2, tags=None) -> ExtractedFoodItem:
    return ExtractedFoodItem(
        name="x",
        portion=1,
        unit="piece",
        macros=MacroSet(calories=300, carbs=carbs, fiber=fiber, protein=5, fat=5),
        portion_confidence=ConfidenceLevel.HIGH,
        tags=tags or [],
    )


def _extraction(items) -> MealExtraction:
    return MealExtraction(
        name="x",
        items=items,
        total_macros=MacroSet(),
        overall_confidence=ConfidenceLevel.HIGH,
    )


class TestGlycemicLoad:
    def test_default_gi_55(self):
        gl = estimate_glycemic_load(_extraction([_item(carbs=50, fiber=0)]))
        assert gl == round(50 * 55 / 100, 1)

    def test_subtracts_fiber(self):
        gl = estimate_glycemic_load(_extraction([_item(carbs=50, fiber=10)]))
        assert gl == round(40 * 55 / 100, 1)

    def test_uses_tag_gi(self):
        gl = estimate_glycemic_load(
            _extraction([_item(carbs=50, fiber=0, tags=["fiber_rich"])])
        )
        assert gl == round(50 * 40 / 100, 1)

    def test_zero_for_no_carbs(self):
        gl = estimate_glycemic_load(_extraction([_item(carbs=0, fiber=0)]))
        assert gl == 0.0


class TestGiFor:
    def test_unknown_tags_default(self):
        assert _gi_for(["unknown"]) == 55

    def test_averages_known(self):
        assert _gi_for(["fried", "fiber_rich"]) == (65 + 40) // 2


@pytest.mark.asyncio
async def test_score_uses_gl_and_llm_output():
    from datetime import datetime

    from lib.ai_foundation.agents.meal_analysis.context_loader import (
        MealAnalysisContext,
    )

    llm_out = _LLMScoreOut(
        overall=45,
        processed_flag=False,
        concerns=["high carbs"],
        positives=["home cooked"],
    )
    gw = MagicMock()
    gw.extract = AsyncMock(return_value=(llm_out, MagicMock()))

    template = MagicMock()
    template.render = MagicMock(return_value="PROMPT")
    prompts = MagicMock()
    prompts.get = MagicMock(return_value=template)

    scorer = MealScorer(gateway=gw, prompt_registry=prompts)
    ctx = MealAnalysisContext(patient_id="p", local_now=datetime.utcnow())
    extraction = _extraction([_item(carbs=50, fiber=0)])

    score = await scorer.score(extraction=extraction, context=ctx, slot="breakfast")
    assert score.overall == 45
    assert score.concerns == ["high carbs"]
    assert score.positives == ["home cooked"]
    assert score.glycemic_load > 0
