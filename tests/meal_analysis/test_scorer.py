"""Tests for MealScorer — deterministic GL + cited Insight filtering + computed score."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealAnalysisContext,
)
from lib.ai_foundation.agents.meal_analysis.contracts import (
    ConfidenceLevel,
    EvidenceSource,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
)
from lib.ai_foundation.agents.meal_analysis.scorer import (
    MealScorer,
    _compute_score,
    _gi_for,
    _is_cited,
    _LLMInsight,
    _LLMScoreOut,
    _to_insight,
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


class TestCitedFilter:
    def test_drops_empty_evidence(self):
        i = _LLMInsight(text="Something", source=EvidenceSource.COMPOSITION, evidence="")
        assert _is_cited(i) is False

    def test_drops_blank_evidence(self):
        i = _LLMInsight(text="Something", source=EvidenceSource.COMPOSITION, evidence="   ")
        assert _is_cited(i) is False

    def test_drops_empty_text(self):
        i = _LLMInsight(text="", source=EvidenceSource.COMPOSITION, evidence="GL: 59")
        assert _is_cited(i) is False

    def test_keeps_well_formed(self):
        i = _LLMInsight(
            text="High GL", source=EvidenceSource.COMPOSITION, evidence="GL: 59"
        )
        assert _is_cited(i) is True


class TestComputeScore:
    def test_no_concerns_returns_100(self):
        overall, breakdown = _compute_score([], [])
        assert overall == 100
        assert breakdown == []

    def test_single_concern_deducts(self):
        i = _to_insight(_LLMInsight(
            text="Over plan target", source=EvidenceSource.PLAN, evidence="60g vs 116g"
        ))
        overall, breakdown = _compute_score([i], [])
        assert overall == 100 - 15  # PLAN weight = 15
        assert len(breakdown) == 1
        assert breakdown[0].delta == -15

    def test_positives_add_back(self):
        concern = _to_insight(_LLMInsight(
            text="High GL", source=EvidenceSource.COMPOSITION, evidence="GL: 59"
        ))
        positive = _to_insight(_LLMInsight(
            text="Mounjaro blunts spike", source=EvidenceSource.MEDICATION,
            evidence="Active: Mounjaro (GLP-1)"
        ))
        overall, breakdown = _compute_score([concern], [positive])
        # 100 - 10 (composition) + 8 (medication) = 98
        assert overall == 98

    def test_many_concerns_capped(self):
        concerns = [
            _to_insight(_LLMInsight(
                text=f"c{i}", source=EvidenceSource.HISTORY, evidence=f"ev{i}"
            ))
            for i in range(10)
        ]
        overall, _ = _compute_score(concerns, [])
        # 10 × -20 = -200 but capped at -70 → score = 30
        assert overall == 30

    def test_clamps_to_zero_and_hundred(self):
        # Impossible in practice but verify clamps
        # (uses extreme hypothetical: many big concerns with no positives,
        # capped at _MAX_CONCERN_DEDUCTION = 70)
        big_concerns = [
            _to_insight(_LLMInsight(
                text=f"c{i}", source=EvidenceSource.HISTORY, evidence=f"ev{i}"
            ))
            for i in range(20)
        ]
        overall, _ = _compute_score(big_concerns, [])
        assert 0 <= overall <= 100


@pytest.mark.asyncio
async def test_score_end_to_end_filters_uncited():
    """LLM returns 1 cited concern + 1 uncited; only the cited one survives."""
    llm_out = _LLMScoreOut(
        concerns=[
            _LLMInsight(
                text="High GL",
                source=EvidenceSource.COMPOSITION,
                evidence="GL: 59 (≥20 is high)",
            ),
            _LLMInsight(
                text="Bad vibes",  # uncited → dropped
                source=EvidenceSource.COMPOSITION,
                evidence="",
            ),
        ],
        positives=[],
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
    assert len(score.concerns) == 1
    assert score.concerns[0].text == "High GL"
    assert score.overall == 100 - 10  # composition weight
    assert score.glycemic_load > 0
    assert len(score.breakdown) == 1
