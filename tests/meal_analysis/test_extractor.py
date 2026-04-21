"""Tests for MealExtractor."""

from __future__ import annotations

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
from lib.ai_foundation.agents.meal_analysis.extractor import (
    MealExtractor,
    _build_messages,
    _compose_from_items,
    _ensure_totals,
    _lowest_confidence,
)


def _ctx() -> MealAnalysisContext:
    from datetime import datetime

    return MealAnalysisContext(
        patient_id="p1",
        local_now=datetime(2026, 4, 20, 8, 45),
        profile={"first_name": "Priya"},
        memories=[],
    )


def _item(name="Paratha", conf=ConfidenceLevel.HIGH, cals=420, carbs=58) -> ExtractedFoodItem:
    return ExtractedFoodItem(
        name=name,
        portion=1,
        unit="piece",
        macros=MacroSet(calories=cals, carbs=carbs, protein=9, fat=16),
        portion_confidence=conf,
    )


class TestComposeFromItems:
    def test_sums_totals(self):
        extraction = _compose_from_items([_item(cals=420, carbs=58), _item("Curd", cals=62, carbs=5)])
        assert extraction.total_macros.calories == 482
        assert extraction.total_macros.carbs == 63

    def test_takes_lowest_confidence(self):
        extraction = _compose_from_items(
            [_item(conf=ConfidenceLevel.HIGH), _item(conf=ConfidenceLevel.LOW)]
        )
        assert extraction.overall_confidence == ConfidenceLevel.LOW

    def test_builds_name_from_items(self):
        extraction = _compose_from_items([_item("A"), _item("B")])
        assert "A" in extraction.name and "B" in extraction.name


class TestEnsureTotals:
    def test_recomputes_when_zero(self):
        items = [_item(cals=100, carbs=20)]
        ex = MealExtraction(
            name="x",
            items=items,
            total_macros=MacroSet(),
            overall_confidence=ConfidenceLevel.HIGH,
        )
        _ensure_totals(ex)
        assert ex.total_macros.calories == 100
        assert ex.total_macros.carbs == 20

    def test_keeps_non_zero_totals(self):
        items = [_item(cals=100)]
        ex = MealExtraction(
            name="x",
            items=items,
            total_macros=MacroSet(calories=999),
            overall_confidence=ConfidenceLevel.HIGH,
        )
        _ensure_totals(ex)
        assert ex.total_macros.calories == 999


class TestLowestConfidence:
    def test_picks_low_over_high(self):
        out = _lowest_confidence(
            [_item(conf=ConfidenceLevel.HIGH), _item(conf=ConfidenceLevel.LOW)]
        )
        assert out == ConfidenceLevel.LOW

    def test_all_high(self):
        assert _lowest_confidence([_item(conf=ConfidenceLevel.HIGH)]) == ConfidenceLevel.HIGH


class TestBuildMessages:
    def test_system_and_user(self):
        msgs = _build_messages(prompt_text="SYS", image_url=None, text="hello")
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert any(p.get("type") == "text" for p in msgs[1]["content"])

    def test_image_included(self):
        msgs = _build_messages(prompt_text="SYS", image_url="http://x/y.jpg", text=None)
        assert any(p.get("type") == "image_url" for p in msgs[1]["content"])


@pytest.mark.asyncio
class TestExtract:
    async def test_items_path_recomputes_via_llm(self):
        """Items path re-calls the LLM so edits to portion/name re-score."""
        ex = MealExtraction(
            name="paratha",
            items=[_item(cals=210, carbs=29)],  # recomputed by LLM
            total_macros=MacroSet(calories=210, carbs=29),
            overall_confidence=ConfidenceLevel.HIGH,
        )
        gw = MagicMock()
        gw.extract = AsyncMock(return_value=(ex, MagicMock()))
        template = MagicMock()
        template.render = MagicMock(return_value="PROMPT")
        prompts = MagicMock()
        prompts.get = MagicMock(return_value=template)

        extractor = MealExtractor(gateway=gw, prompt_registry=prompts)
        out = await extractor.extract(
            context=_ctx(),
            slot="breakfast",
            items=[_item()],
        )
        assert out.total_macros.calories == 210
        gw.extract.assert_awaited_once()

    async def test_calls_gateway_when_image(self):
        ex = MealExtraction(
            name="paratha",
            items=[_item()],
            total_macros=MacroSet(calories=420, carbs=58),
            overall_confidence=ConfidenceLevel.HIGH,
        )
        gw = MagicMock()
        gw.extract = AsyncMock(return_value=(ex, MagicMock()))

        template = MagicMock()
        template.render = MagicMock(return_value="PROMPT")
        prompts = MagicMock()
        prompts.get = MagicMock(return_value=template)

        extractor = MealExtractor(gateway=gw, prompt_registry=prompts)
        out = await extractor.extract(
            context=_ctx(),
            slot="breakfast",
            image_url="http://x/y.jpg",
        )
        assert out.name == "paratha"
        gw.extract.assert_awaited_once()

    async def test_raises_on_no_input(self):
        gw = MagicMock()
        prompts = MagicMock()
        extractor = MealExtractor(gateway=gw, prompt_registry=prompts)

        with pytest.raises(ValueError):
            await extractor.extract(context=_ctx(), slot="breakfast")
