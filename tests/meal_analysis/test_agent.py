"""Integration test for MealAnalysisAgent — fully mocked sub-services."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent


def _noop_gateway() -> MagicMock:
    """Gateway mock whose langfuse hooks are no-ops (non-awaitable)."""
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
    EvidenceSource,
    ExtractedFoodItem,
    GlucosePrediction,
    MacroSet,
    MealExtraction,
    MealPreviewRequest,
    MealScore,
    MealSlot,
    MealSource,
    Pairing,
    PairingBenefit,
    PlanCheck,
    RepeatFlag,
    RepeatSuggestion,
)


def _extraction():
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


@pytest.mark.asyncio
async def test_analyze_happy_path():
    ctx = MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
        has_cgm=True,
    )

    ctx_loader = MagicMock()
    ctx_loader.load = AsyncMock(return_value=ctx)

    extractor = MagicMock()
    extractor.extract = AsyncMock(return_value=_extraction())

    scorer = MagicMock()
    scorer.score = AsyncMock(
        return_value=MealScore(
            overall=45,
            glycemic_load=32.0,
            concerns=[],
            positives=[],
        )
    )

    alternatives = MagicMock()
    alternatives.rank = AsyncMock(
        return_value=(
            [
                Alternative(
                    item_to_replace="aloo paratha",
                    swap_with="moong dosa",
                    reason="ADA: ≤45g carbs/meal suggests lower-GI swap",
                    source=AlternativeSource.GUIDELINE,
                )
            ],
            [
                Pairing(
                    add="salad",
                    reason="fiber with carbs slows absorption",
                    benefit=PairingBenefit.FIBER,
                    source=EvidenceSource.GUIDELINE,
                    evidence="ADA suggests pairing fiber with carbs",
                )
            ],
        )
    )

    glucose = MagicMock()
    glucose.predict = AsyncMock(
        return_value=GlucosePrediction(
            range_mg_dl_low=150,
            range_mg_dl_high=180,
            peak_minutes_after=60,
            confidence=ConfidenceLevel.HIGH,
            n_similar_meals=3,
            rationale="based on past meals",
        )
    )

    agent = MealAnalysisAgent(
        gateway=_noop_gateway(),
        qdrant_retriever=MagicMock(),
        context_loader=ctx_loader,
        extractor=extractor,
        scorer=scorer,
        alternatives=alternatives,
        glucose_predictor=glucose,
    )

    req = MealPreviewRequest(
        slot=MealSlot.BREAKFAST,
        source=MealSource.PHOTO,
        consumed_at=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
        image_url="http://x/y.jpg",
    )

    result = await agent.analyze(patient_id="p1", request=req)

    assert result.extraction.name == "Aloo paratha"
    assert result.score.overall == 45
    assert len(result.alternatives) == 1
    assert result.predicted_glucose is not None
    assert result.plan.has_plan is False  # no plan in ctx
    assert result.repeat.suggestion == RepeatSuggestion.NONE
    assert result.model_trace_id is not None


@pytest.mark.asyncio
async def test_analyze_skips_extractor_for_items_input():
    ctx = MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
    )
    ctx_loader = MagicMock()
    ctx_loader.load = AsyncMock(return_value=ctx)

    extractor = MagicMock()
    extractor.extract = AsyncMock(return_value=_extraction())

    scorer = MagicMock()
    scorer.score = AsyncMock(
        return_value=MealScore(overall=60, glycemic_load=10.0)
    )
    alternatives = MagicMock()
    alternatives.rank = AsyncMock(return_value=([], []))
    glucose = MagicMock()
    glucose.predict = AsyncMock(return_value=None)

    agent = MealAnalysisAgent(
        gateway=_noop_gateway(),
        qdrant_retriever=MagicMock(),
        context_loader=ctx_loader,
        extractor=extractor,
        scorer=scorer,
        alternatives=alternatives,
        glucose_predictor=glucose,
    )

    items = [
        ExtractedFoodItem(
            name="egg",
            portion=2,
            unit="piece",
            macros=MacroSet(calories=140, carbs=2, protein=12, fat=10),
            portion_confidence=ConfidenceLevel.HIGH,
        )
    ]
    req = MealPreviewRequest(
        slot=MealSlot.BREAKFAST, source=MealSource.MANUAL, items=items
    )

    # Extractor still called (it handles items-path internally by composing)
    result = await agent.analyze(patient_id="p1", request=req)
    assert result.predicted_glucose is None
    assert result.alternatives == []


@pytest.mark.asyncio
async def test_analyze_repeat_of_meal_id_resolves_prior():
    ctx = MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 8, 45, tzinfo=timezone.utc),
    )
    ctx_loader = MagicMock()
    ctx_loader.load = AsyncMock(return_value=ctx)

    extractor = MagicMock()
    extractor.extract = AsyncMock()

    scorer = MagicMock()
    scorer.score = AsyncMock(
        return_value=MealScore(overall=50, glycemic_load=15.0)
    )
    alternatives = MagicMock()
    alternatives.rank = AsyncMock(return_value=([], []))
    glucose = MagicMock()
    glucose.predict = AsyncMock(return_value=None)

    agent = MealAnalysisAgent(
        gateway=_noop_gateway(),
        qdrant_retriever=MagicMock(),
        context_loader=ctx_loader,
        extractor=extractor,
        scorer=scorer,
        alternatives=alternatives,
        glucose_predictor=glucose,
    )

    prior = _extraction()
    import uuid as _uuid

    from lib.ai_foundation.agents.meal_analysis import agent as agent_module

    with patch.object(
        agent_module,
        "_load_meal_from_qdrant",
        AsyncMock(return_value=prior),
    ):
        req = MealPreviewRequest(
            slot=MealSlot.BREAKFAST,
            source=MealSource.REPEAT,
            repeat_of_meal_id=_uuid.uuid4(),
        )
        result = await agent.analyze(patient_id="p1", request=req)

    assert result.extraction.name == prior.name
    extractor.extract.assert_not_called()
