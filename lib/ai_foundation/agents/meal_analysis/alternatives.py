"""
Alternatives engine.

Ranks swaps and pairings for the current meal. Prefers items from the
patient's own history; falls back to culturally-matched guidelines when
history is empty or unfit.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.prompts.registry import PromptRegistry

from .context_loader import MealAnalysisContext
from .contracts import Alternative, MealExtraction, Pairing

logger = logging.getLogger(__name__)


ALTERNATIVES_PROMPT_NAME = "meal_analysis_alternatives"
RECENT_MEALS_LIMIT = 20


class _LLMAlternativesOut(BaseModel):
    alternatives: list[Alternative] = Field(default_factory=list)
    pairings: list[Pairing] = Field(default_factory=list)


class AlternativesEngine:
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

    async def rank(
        self,
        *,
        extraction: MealExtraction,
        context: MealAnalysisContext,
        glycemic_load: float,
        slot: str,
        trace_id: str | None = None,
    ) -> tuple[list[Alternative], list[Pairing]]:
        template = self._prompts.get(ALTERNATIVES_PROMPT_NAME)
        recent = _prep_recent_meals(context.recent_meals)
        prompt = template.render(
            extraction_json=json.dumps(extraction.model_dump(mode="json")),
            glycemic_load=f"{glycemic_load:.1f}",
            recent_meals_json=json.dumps(recent, default=str),
            cgm_events_json=json.dumps(
                context.cgm_events or [], default=str
            ),
            medications_json=json.dumps(
                context.medications or [], default=str
            ),
            recent_workouts_json=json.dumps(
                context.recent_workouts or [], default=str
            ),
            has_cgm=str(context.has_cgm).lower(),
            patient_context=_patient_context_string(context),
            slot=slot or "",
        )

        llm_out, _ = await self._gateway.extract(
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "Return alternatives and pairings.",
                },
            ],
            response_model=_LLMAlternativesOut,
            task=self._task,
            trace_id=trace_id,
        )

        return list(llm_out.alternatives), list(llm_out.pairings)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prep_recent_meals(recent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim to essentials so the LLM context stays tight."""
    trimmed: list[dict[str, Any]] = []
    for meal in (recent or [])[:RECENT_MEALS_LIMIT]:
        trimmed.append(
            {
                "meal_id": meal.get("meal_id"),
                "name": meal.get("name"),
                "slot": meal.get("slot"),
                "consumed_at": meal.get("consumed_at"),
                "tags": meal.get("tags") or [],
                "macros": meal.get("macros") or {},
                "items": [
                    {"name": it.get("name"), "quantity": it.get("serving_quantity")}
                    for it in (meal.get("items") or [])
                ],
            }
        )
    return trimmed


def _patient_context_string(context: MealAnalysisContext) -> str:
    mems = "; ".join(
        f"{m.key}={m.value}" for m in (context.memories or [])[:8]
    )
    return json.dumps(
        {
            "profile": context.profile or {},
            "memories": mems,
            "has_cgm": context.has_cgm,
        },
        default=str,
    )
