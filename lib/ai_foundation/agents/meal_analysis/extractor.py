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

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.prompts.registry import PromptRegistry

from .context_loader import MealAnalysisContext
from .contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    MacroSet,
    MealExtraction,
    MicroSet,
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
        model_task: ModelTask = ModelTask.MEAL_ANALYSIS,
    ) -> None:
        self._gateway = gateway
        self._prompts = prompt_registry
        self._task = model_task

    async def extract(
        self,
        *,
        context: MealAnalysisContext,
        slot: str,
        image_urls: list[str] | None = None,
        text: str | None = None,
        items: list[ExtractedFoodItem] | None = None,
        portion_note: str | None = None,
        trace_id: str | None = None,
    ) -> MealExtraction:
        """Produce a MealExtraction.

        Paths:
            - ``items`` given → LLM recomputes macros from name+portion+unit
              so portion/name edits in the preview re-score accurately.
            - image/text given → vision/text extraction.
        """
        input_boxes: dict[str, list[int]] | None = None
        if items is not None and len(items) > 0:
            input_boxes = {
                it.name.strip().lower(): it.box_2d
                for it in items
                if it.box_2d
            }
            text_description = _items_to_text(items, portion_note=portion_note)
            image_urls = None
            text = text_description
            portion_note = None

        if not image_urls and not text:
            raise ValueError(
                "MealExtractor requires image_url(s), text, or items"
            )

        user_messages = _build_messages(
            prompt_text=self._render_prompt(
                context=context,
                slot=slot,
                image_urls=image_urls,
                text=text,
                portion_note=portion_note,
            ),
            image_urls=image_urls,
            text=text,
        )

        extraction, _ = await self._gateway.extract(
            messages=user_messages,
            response_model=MealExtraction,
            task=self._task,
            timeout=settings.MEAL_LLM_TIMEOUT_SECONDS,
            trace_id=trace_id,
        )
        _ensure_totals(extraction)
        if input_boxes:
            _restore_boxes(extraction, input_boxes)
        return extraction

    # ── helpers ──────────────────────────────────────────────────────────

    def _render_prompt(
        self,
        *,
        context: MealAnalysisContext,
        slot: str,
        image_urls: list[str] | None,
        text: str | None,
        portion_note: str | None,
    ) -> str:
        template = self._prompts.get(EXTRACTION_PROMPT_NAME)
        image_desc = f"{len(image_urls)} image(s) provided" if image_urls else "(none)"
        return template.render(
            patient_context=_patient_context_string(context),
            slot=slot or "",
            image_url=image_desc,
            text=text or "(none)",
            portion_note=portion_note or "(none)",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _items_to_text(
    items: list[ExtractedFoodItem], *, portion_note: str | None = None
) -> str:
    """Convert a list of items into a natural-language description for the LLM."""
    lines = [
        f"- {it.name}: {it.portion} {it.unit}"
        for it in items
    ]
    text = "\n".join(lines)
    if portion_note:
        text += f"\n\nPortion note: {portion_note}"
    return text


def _compose_from_items(items: list[ExtractedFoodItem]) -> MealExtraction:
    macros, micros = _sum_nutrition(items)

    name = ", ".join(it.name for it in items[:3])
    if len(items) > 3:
        name += f", +{len(items) - 3} more"

    return MealExtraction(
        name=name or "Custom meal",
        items=items,
        total_macros=macros,
        total_micros=micros,
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
    """Recompute totals deterministically from items. Items are the source of
    truth; the LLM's totals are advisory and routinely wrong (mis-summed,
    missing micros). Recomputing every time keeps totals consistent with what
    we display per item.
    """
    if not extraction.items:
        return
    macros, micros = _sum_nutrition(extraction.items)
    extraction.total_macros = macros
    extraction.total_micros = micros


def _sum_nutrition(items: list[ExtractedFoodItem]) -> tuple[MacroSet, MicroSet]:
    """Sum per-item macros and micros. Treats missing fields as 0."""
    macros = MacroSet()
    micros = MicroSet()
    for it in items:
        macros.calories += it.macros.calories or 0
        macros.carbs += it.macros.carbs or 0
        macros.carbs_simple += it.macros.carbs_simple or 0
        macros.carbs_complex += it.macros.carbs_complex or 0
        macros.fiber += it.macros.fiber or 0
        macros.protein += it.macros.protein or 0
        macros.fat += it.macros.fat or 0

        micros.sodium_mg = (micros.sodium_mg or 0) + (it.micros.sodium_mg or 0)
        micros.potassium_mg = (micros.potassium_mg or 0) + (it.micros.potassium_mg or 0)
        micros.calcium_mg = (micros.calcium_mg or 0) + (it.micros.calcium_mg or 0)
        micros.iron_mg = (micros.iron_mg or 0) + (it.micros.iron_mg or 0)
        micros.magnesium_mg = (micros.magnesium_mg or 0) + (it.micros.magnesium_mg or 0)
        micros.zinc_mg = (micros.zinc_mg or 0) + (it.micros.zinc_mg or 0)
    return macros, micros


def _restore_boxes(
    extraction: MealExtraction, boxes: dict[str, list[int]]
) -> None:
    """Carry forward box_2d from the input items the client sent.

    When items are provided (edit re-preview), the LLM gets text only and
    returns box_2d=null.  The original boxes are still valid for items whose
    name didn't change.
    """
    for item in extraction.items:
        if not item.box_2d:
            box = boxes.get(item.name.strip().lower())
            if box:
                item.box_2d = box


def _build_messages(
    *,
    prompt_text: str,
    image_urls: list[str] | None,
    text: str | None,
) -> list[dict[str, Any]]:
    """Build a vision-capable multimodal message array."""
    user_content: list[dict[str, Any]] = []
    if text:
        user_content.append({"type": "text", "text": text})
    for url in (image_urls or []):
        user_content.append(
            {"type": "image_url", "image_url": {"url": url}}
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
