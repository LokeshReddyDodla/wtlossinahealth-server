"""
Meal extractor.

Image/text → MealExtraction via ModelGateway (structured output).
Skips the LLM call when the client sends `items` (manual entry / edit re-preview)
or `repeat_of_meal_id` (the agent resolves the prior extraction upstream).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.prompts.registry import PromptRegistry

from .context_loader import MealAnalysisContext
from .contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
)

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT_NAME = "meal_analysis_extraction"


class MealExtractor:
    """One-shot LLM call that turns an image/text into MealExtraction."""

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        prompt_registry: PromptRegistry,
        model_task: ModelTask = ModelTask.STRUCTURED_ANALYSIS,
    ) -> None:
        self._gateway = gateway
        self._prompts = prompt_registry
        self._task = model_task

    async def extract(
        self,
        *,
        context: MealAnalysisContext,
        slot: str,
        image_url: str | None = None,
        text: str | None = None,
        items: list[ExtractedFoodItem] | None = None,
        portion_note: str | None = None,
        trace_id: str | None = None,
    ) -> MealExtraction:
        """Produce a MealExtraction.

        Fast paths:
            - `items` given → skip LLM, compose MealExtraction from items.
        """
        if items is not None and len(items) > 0:
            return _compose_from_items(items)

        if not image_url and not text:
            raise ValueError(
                "MealExtractor requires image_url, text, or items"
            )

        user_messages = _build_messages(
            prompt_text=self._render_prompt(
                context=context,
                slot=slot,
                image_url=image_url,
                text=text,
                portion_note=portion_note,
            ),
            image_url=image_url,
            text=text,
        )

        extraction, _ = await self._gateway.extract(
            messages=user_messages,
            response_model=MealExtraction,
            task=self._task,
            trace_id=trace_id,
        )
        _ensure_totals(extraction)
        return extraction

    # ── helpers ──────────────────────────────────────────────────────────

    def _render_prompt(
        self,
        *,
        context: MealAnalysisContext,
        slot: str,
        image_url: str | None,
        text: str | None,
        portion_note: str | None,
    ) -> str:
        template = self._prompts.get(EXTRACTION_PROMPT_NAME)
        return template.render(
            patient_context=_patient_context_string(context),
            slot=slot or "",
            image_url=image_url or "(none)",
            text=text or "(none)",
            portion_note=portion_note or "(none)",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compose_from_items(items: list[ExtractedFoodItem]) -> MealExtraction:
    total = MacroSet()
    for it in items:
        total.calories += it.macros.calories or 0
        total.carbs += it.macros.carbs or 0
        total.carbs_simple += it.macros.carbs_simple or 0
        total.carbs_complex += it.macros.carbs_complex or 0
        total.fiber += it.macros.fiber or 0
        total.protein += it.macros.protein or 0
        total.fat += it.macros.fat or 0

    name = ", ".join(it.name for it in items[:3])
    if len(items) > 3:
        name += f", +{len(items) - 3} more"

    return MealExtraction(
        name=name or "Custom meal",
        items=items,
        total_macros=total,
        tags=_dedup_tags([t for it in items for t in it.tags]),
        overall_confidence=_lowest_confidence(items),
    )


def _dedup_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _lowest_confidence(items: list[ExtractedFoodItem]) -> ConfidenceLevel:
    ranks = {ConfidenceLevel.HIGH: 3, ConfidenceLevel.MEDIUM: 2, ConfidenceLevel.LOW: 1}
    best = ConfidenceLevel.HIGH
    for it in items:
        if ranks[it.portion_confidence] < ranks[best]:
            best = it.portion_confidence
    return best


def _ensure_totals(extraction: MealExtraction) -> None:
    """If LLM returned zero totals but per-item macros, sum them in."""
    tm = extraction.total_macros
    if (tm.calories or tm.carbs or tm.protein or tm.fat) > 0:
        return
    if not extraction.items:
        return
    totals = MacroSet()
    for it in extraction.items:
        totals.calories += it.macros.calories or 0
        totals.carbs += it.macros.carbs or 0
        totals.carbs_simple += it.macros.carbs_simple or 0
        totals.carbs_complex += it.macros.carbs_complex or 0
        totals.fiber += it.macros.fiber or 0
        totals.protein += it.macros.protein or 0
        totals.fat += it.macros.fat or 0
    extraction.total_macros = totals


def _build_messages(
    *,
    prompt_text: str,
    image_url: str | None,
    text: str | None,
) -> list[dict[str, Any]]:
    """Build a vision-capable multimodal message array."""
    user_content: list[dict[str, Any]] = []
    if text:
        user_content.append({"type": "text", "text": text})
    if image_url:
        user_content.append(
            {"type": "image_url", "image_url": {"url": image_url}}
        )
    if not user_content:
        user_content.append({"type": "text", "text": "No input provided."})

    return [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": user_content},
    ]


def _patient_context_string(context: MealAnalysisContext) -> str:
    """A compact JSON-ish block the LLM can use for personalization."""
    profile = context.profile or {}
    memory_snippets = [
        f"- {m.key}: {m.value}"
        for m in (context.memories or [])[:8]
    ]
    plan = context.active_diet_plan
    plan_line = "none"
    if plan is not None:
        try:
            plan_line = (
                f"calories={plan.calories}, carbs={plan.carbs}, "
                f"protein={plan.protein}, fats={plan.fats}"
            )
        except Exception:
            plan_line = "present"

    parts = [
        "Profile: " + json.dumps(
            {k: _safe(v) for k, v in profile.items()}, default=str
        ),
        f"Active diet plan: {plan_line}",
        f"Has CGM: {context.has_cgm}",
    ]
    if memory_snippets:
        parts.append("Memories:\n" + "\n".join(memory_snippets))
    return "\n".join(parts)


def _safe(v: Any) -> Any:
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)
