"""
Meal scorer.

Hybrid: deterministic glycemic load + LLM for concerns/positives/overall.
Keeps quantitative math out of the LLM's hands.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.prompts.registry import PromptRegistry

from .context_loader import MealAnalysisContext
from .contracts import MealExtraction, MealScore

logger = logging.getLogger(__name__)


SCORING_PROMPT_NAME = "meal_analysis_scoring"

# Rough carb→GI heuristic table for GL estimation. Not a medical source —
# a usable approximation for LLM-free GL math. Downstream LLM can override
# commentary; this just anchors the number.
_DEFAULT_GI = 55
_GI_BY_TAG = {
    "fried": 65,
    "high_carb": 70,
    "refined": 75,
    "whole_grain": 45,
    "fiber_rich": 40,
    "low_gi": 35,
    "plant_based": 45,
    "protein_rich": 35,
    "processed": 70,
    "dairy": 35,
}


class _LLMScoreOut(BaseModel):
    overall: int = Field(..., ge=0, le=100)
    processed_flag: bool = False
    concerns: list[str] = Field(default_factory=list)
    positives: list[str] = Field(default_factory=list)


class MealScorer:
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

    async def score(
        self,
        *,
        extraction: MealExtraction,
        context: MealAnalysisContext,
        slot: str,
        trace_id: str | None = None,
    ) -> MealScore:
        gl = estimate_glycemic_load(extraction)

        template = self._prompts.get(SCORING_PROMPT_NAME)
        prompt = template.render(
            extraction_json=json.dumps(extraction.model_dump(mode="json")),
            glycemic_load=f"{gl:.1f}",
            patient_context=_patient_context_string(context),
            slot=slot or "",
        )

        llm_out, _ = await self._gateway.extract(
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "Return the MealScore fields only.",
                },
            ],
            response_model=_LLMScoreOut,
            task=self._task,
            trace_id=trace_id,
        )

        return MealScore(
            overall=llm_out.overall,
            glycemic_load=gl,
            processed_flag=llm_out.processed_flag,
            concerns=llm_out.concerns,
            positives=llm_out.positives,
        )


# ---------------------------------------------------------------------------
# Glycemic load (deterministic)
# ---------------------------------------------------------------------------


def estimate_glycemic_load(extraction: MealExtraction) -> float:
    """GL ≈ sum over items of (carbs_g * estimated_GI / 100).

    Uses tag heuristics to pick a per-item GI; falls back to 55 (moderate).
    Fiber is subtracted from carbs for the GL base.
    """
    total_gl = 0.0
    for it in extraction.items:
        carbs = (it.macros.carbs or 0) - (it.macros.fiber or 0)
        if carbs <= 0:
            continue
        gi = _gi_for(it.tags)
        total_gl += carbs * gi / 100.0
    return round(total_gl, 1)


def _gi_for(tags: list[str]) -> int:
    tag_gis = [_GI_BY_TAG[t] for t in tags if t in _GI_BY_TAG]
    if not tag_gis:
        return _DEFAULT_GI
    return sum(tag_gis) // len(tag_gis)


def _patient_context_string(context: MealAnalysisContext) -> str:
    mems = "; ".join(
        f"{m.key}={m.value}" for m in (context.memories or [])[:6]
    )
    return json.dumps(
        {
            "profile": context.profile or {},
            "memories": mems,
            "has_cgm": context.has_cgm,
        },
        default=str,
    )
