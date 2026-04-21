"""
Glucose predictor.

LLM-reasoned estimate of post-meal glucose response. Never a trained
predictor — reasons over the patient's own cited CGM-linked past meals.

Returns None when:
    - the patient has no CGM (has_cgm == False), or
    - the LLM declines ('skip=true') due to insufficient evidence.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.prompts.registry import PromptRegistry

from .alternatives import _prep_recent_meals
from .context_loader import MealAnalysisContext
from .contracts import (
    ConfidenceLevel,
    GlucosePrediction,
    MealEvidenceRef,
    MealExtraction,
)

logger = logging.getLogger(__name__)


GLUCOSE_PROMPT_NAME = "meal_analysis_glucose_prediction"


class _LLMGlucoseOut(BaseModel):
    skip: bool = False
    range_mg_dl_low: int | None = None
    range_mg_dl_high: int | None = None
    peak_minutes_after: int | None = None
    confidence: ConfidenceLevel | None = None
    n_similar_meals: int = 0
    evidence: list[MealEvidenceRef] = Field(default_factory=list)
    rationale: str = ""


class GlucosePredictor:
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

    async def predict(
        self,
        *,
        extraction: MealExtraction,
        context: MealAnalysisContext,
        glycemic_load: float,
        slot: str,
        trace_id: str | None = None,
    ) -> GlucosePrediction | None:
        if not context.has_cgm:
            return None

        template = self._prompts.get(GLUCOSE_PROMPT_NAME)
        prompt = template.render(
            extraction_json=json.dumps(extraction.model_dump(mode="json")),
            glycemic_load=f"{glycemic_load:.1f}",
            recent_meals_json=json.dumps(
                _prep_recent_meals(context.recent_meals), default=str
            ),
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
                {"role": "user", "content": "Return the glucose prediction."},
            ],
            response_model=_LLMGlucoseOut,
            task=self._task,
            trace_id=trace_id,
        )

        if llm_out.skip:
            return None

        if (
            llm_out.range_mg_dl_low is None
            or llm_out.range_mg_dl_high is None
            or llm_out.peak_minutes_after is None
            or llm_out.confidence is None
        ):
            logger.debug(
                "glucose_predictor: LLM returned skip=False but missing fields; dropping"
            )
            return None

        return GlucosePrediction(
            range_mg_dl_low=llm_out.range_mg_dl_low,
            range_mg_dl_high=llm_out.range_mg_dl_high,
            peak_minutes_after=llm_out.peak_minutes_after,
            confidence=llm_out.confidence,
            n_similar_meals=llm_out.n_similar_meals,
            evidence=llm_out.evidence,
            rationale=llm_out.rationale,
        )


def _patient_context_string(context: MealAnalysisContext) -> str:
    mems = "; ".join(
        f"{m.key}={m.value}" for m in (context.memories or [])[:8]
    )
    return json.dumps(
        {
            "profile": context.profile or {},
            "memories": mems,
        },
        default=str,
    )
