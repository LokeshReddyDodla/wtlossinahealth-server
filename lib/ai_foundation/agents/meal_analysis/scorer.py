"""
Meal scorer.

Every concern/positive the LLM returns MUST declare a ``source`` and
``evidence``. Uncited insights are dropped server-side before the score
is computed. The overall 0–100 is derived from weighted deductions on
the cited concerns, not LLM-assigned — so a patient can always see the
exact breakdown of why they got a 72.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.prompts.registry import PromptRegistry

from .context_loader import MealAnalysisContext
from .contracts import (
    EvidenceSource,
    Insight,
    MealExtraction,
    MealScore,
    ScoreBreakdownItem,
)

logger = logging.getLogger(__name__)


SCORING_PROMPT_NAME = "meal_analysis_scoring"

# GI heuristic table for GL estimation — per-item best-guess GI by tag.
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

# Source weights for the computed score. Higher weight = that source
# carries more authority (per-source, not per-concern).
_CONCERN_WEIGHT_BY_SOURCE: dict[EvidenceSource, int] = {
    EvidenceSource.HISTORY: 20,      # cited past peaks: strong signal
    EvidenceSource.PLAN: 15,         # plan deviation: concrete
    EvidenceSource.GUIDELINE: 12,    # clinical rule: important but general
    EvidenceSource.MEDICATION: 8,    # med interaction: secondary concern
    EvidenceSource.PROFILE: 10,      # allergy / dietary pref: hard constraint
    EvidenceSource.COMPOSITION: 10,  # GL/macro math: direct from meal
}
_POSITIVE_WEIGHT_BY_SOURCE: dict[EvidenceSource, int] = {
    EvidenceSource.HISTORY: 10,
    EvidenceSource.PLAN: 8,
    EvidenceSource.GUIDELINE: 6,
    EvidenceSource.MEDICATION: 8,
    EvidenceSource.PROFILE: 5,
    EvidenceSource.COMPOSITION: 5,
}
_SCORE_BASELINE = 100
_MAX_CONCERN_DEDUCTION = 70  # caps total deductions so score never goes below 30 purely from concerns


class _LLMInsight(BaseModel):
    """What the LLM returns. Strict: text/source/evidence all required."""

    text: str
    source: EvidenceSource
    evidence: str


class _LLMScoreOut(BaseModel):
    concerns: list[_LLMInsight] = Field(default_factory=list)
    positives: list[_LLMInsight] = Field(default_factory=list)


class MealScorer:
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
            active_medications_json=json.dumps(
                context.medications or [], default=str
            ),
            active_plan_json=json.dumps(
                context.active_diet_plan or {}, default=str
            ),
            recent_cgm_events_json=json.dumps(
                (context.cgm_events or [])[: settings.MEAL_PROMPT_CGM_EVENTS_LIMIT],
                default=str,
            ),
            slot=slot or "",
        )

        llm_out, _ = await self._gateway.extract(
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "Return cited concerns and positives only.",
                },
            ],
            response_model=_LLMScoreOut,
            task=self._task,
            timeout=settings.MEAL_LLM_TIMEOUT_SECONDS,
            trace_id=trace_id,
        )

        cited_concerns = [_to_insight(i) for i in llm_out.concerns if _is_cited(i)]
        cited_positives = [_to_insight(i) for i in llm_out.positives if _is_cited(i)]

        # Observability for the egg-allergy class of bug: log every
        # source=profile insight alongside what the patient's profile and
        # memories actually contain. Grep `meal_scorer.profile_insight` to
        # spot phantom allergies / conditions in real traffic.
        _log_profile_insights(cited_concerns, cited_positives, context)

        overall, breakdown = _compute_score(cited_concerns, cited_positives)

        return MealScore(
            overall=overall,
            glycemic_load=gl,
            concerns=cited_concerns,
            positives=cited_positives,
            breakdown=breakdown,
        )


# ---------------------------------------------------------------------------
# Citation filtering + score computation
# ---------------------------------------------------------------------------


def _log_profile_insights(
    concerns: list[Insight], positives: list[Insight], context: MealAnalysisContext,
) -> None:
    """Surface every source=profile insight in logs so we can audit whether
    the LLM is fabricating profile/allergy/condition claims for real
    patients. INFO level so it ships to production logs by default."""
    profile_keys = list((context.profile or {}).keys())
    memory_pairs = [
        f"{getattr(m, 'key', '?')}={getattr(m, 'value', '?')}"
        for m in (context.memories or [])
    ]
    for ins in (*concerns, *positives):
        if ins.source == EvidenceSource.PROFILE:
            logger.info(
                "meal_scorer.profile_insight | patient=%s text=%r evidence=%r profile_keys=%s memories=%s",
                (context.patient_id or "?")[:8],
                ins.text,
                ins.evidence,
                profile_keys,
                memory_pairs,
            )


def _is_cited(insight: _LLMInsight) -> bool:
    """Drop insights where evidence is missing/blank or text is empty."""
    if not insight.text.strip():
        return False
    if not insight.evidence.strip():
        return False
    return True


def _to_insight(src: _LLMInsight) -> Insight:
    return Insight(text=src.text.strip(), source=src.source, evidence=src.evidence.strip())


def _compute_score(
    concerns: list[Insight], positives: list[Insight]
) -> tuple[int, list[ScoreBreakdownItem]]:
    """Derive a defensible 0–100 from cited concerns (deduct) and positives (add back).

    Starts from 100. Each concern subtracts by source weight. Each positive
    adds back by source weight, capped to prevent gaming. Deduction total is
    capped at _MAX_CONCERN_DEDUCTION so even a terrible meal is bounded.
    """
    breakdown: list[ScoreBreakdownItem] = []

    raw_deduction = 0
    for c in concerns:
        delta = -_CONCERN_WEIGHT_BY_SOURCE.get(c.source, 5)
        raw_deduction += -delta
        breakdown.append(
            ScoreBreakdownItem(delta=delta, source=c.source, evidence=c.evidence)
        )

    if raw_deduction > _MAX_CONCERN_DEDUCTION:
        # Scale down proportionally
        scale = _MAX_CONCERN_DEDUCTION / raw_deduction
        rescaled: list[ScoreBreakdownItem] = []
        for item in breakdown:
            rescaled.append(
                ScoreBreakdownItem(
                    delta=int(item.delta * scale),
                    source=item.source,
                    evidence=item.evidence,
                )
            )
        breakdown = rescaled
        raw_deduction = _MAX_CONCERN_DEDUCTION

    raw_bonus = 0
    for p in positives:
        delta = _POSITIVE_WEIGHT_BY_SOURCE.get(p.source, 3)
        raw_bonus += delta
        breakdown.append(
            ScoreBreakdownItem(delta=delta, source=p.source, evidence=p.evidence)
        )

    overall = _SCORE_BASELINE - raw_deduction + raw_bonus
    # Clamp
    overall = max(0, min(100, overall))
    return overall, breakdown


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
