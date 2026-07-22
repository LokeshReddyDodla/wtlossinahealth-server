"""Deterministic framing + classification for events handed to the one brain.

The brain (HealthQueryAgent) writes the words. These functions decide — from
the trigger and its anchor alone, never the LLM — three things:

  * how the event is described to the brain (``frame_event``),
  * how deep the brain may investigate (``trigger_tier``),
  * the clinical category + severity of any resulting insight
    (``classify_event``),

so danger level is never the model's to invent. Only CGM threshold crossings
are wired to the brain today; other triggers stay on the legacy path until
migrated, and raise here if routed by mistake.
"""

from __future__ import annotations

from lib.services.cgm_threshold_detector import CGMCrossingKind
from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningTier
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    CGMThresholdCrossedAnchor,
    EventTrigger,
    InsightCategory,
    InsightSeverity,
)

# Crossings where silence is riskiest — the brain gets the deepest tool budget.
_CGM_SAFETY = frozenset({CGMCrossingKind.SEVERE_HYPO, CGMCrossingKind.HYPO})

# Category + severity per crossing. Severity is clinical authority: it drives
# the broker's urgent routing and the notification channel, so it is fixed
# here, not chosen by the model.
_CGM_CLASS: dict[CGMCrossingKind, tuple[InsightCategory, InsightSeverity]] = {
    CGMCrossingKind.SEVERE_HYPO: (InsightCategory.GLUCOSE_HYPO, InsightSeverity.ALERT),
    CGMCrossingKind.HYPO: (InsightCategory.GLUCOSE_HYPO, InsightSeverity.WARNING),
    CGMCrossingKind.SEVERE_HYPER: (InsightCategory.GLUCOSE_SPIKE, InsightSeverity.WARNING),
    CGMCrossingKind.HYPER: (InsightCategory.GLUCOSE_SPIKE, InsightSeverity.ATTENTION),
    CGMCrossingKind.RAPID_DROP: (InsightCategory.GLUCOSE_RAPID_DROP, InsightSeverity.WARNING),
    CGMCrossingKind.RAPID_SPIKE: (InsightCategory.GLUCOSE_RAPID_SPIKE, InsightSeverity.ATTENTION),
}

_CGM_READABLE: dict[CGMCrossingKind, str] = {
    CGMCrossingKind.SEVERE_HYPO: "very low",
    CGMCrossingKind.HYPO: "low",
    CGMCrossingKind.SEVERE_HYPER: "very high",
    CGMCrossingKind.HYPER: "high",
    CGMCrossingKind.RAPID_DROP: "rapidly falling",
    CGMCrossingKind.RAPID_SPIKE: "rapidly rising",
}


def _crossing(anchor: CGMThresholdCrossedAnchor) -> CGMCrossingKind:
    return CGMCrossingKind(anchor.kind)  # raises on an unknown kind — fail loud, not silent


def trigger_tier(trigger: EventTrigger, anchor: CGMThresholdCrossedAnchor) -> ReasoningTier:
    if trigger is EventTrigger.CGM_THRESHOLD_CROSSED:
        return ReasoningTier.ADVANCED if _crossing(anchor) in _CGM_SAFETY else ReasoningTier.STANDARD
    raise ValueError(f"trigger_tier: {trigger} is not wired to the brain yet")


def classify_event(
    trigger: EventTrigger, anchor: CGMThresholdCrossedAnchor,
) -> tuple[InsightCategory, InsightSeverity]:
    if trigger is EventTrigger.CGM_THRESHOLD_CROSSED:
        return _CGM_CLASS[_crossing(anchor)]
    raise ValueError(f"classify_event: {trigger} is not wired to the brain yet")


def frame_event(
    trigger: EventTrigger, anchor: CGMThresholdCrossedAnchor, patient_name: str | None = None,
) -> str:
    """A neutral, factual description of the event for the brain to investigate.

    Deliberately carries no interpretation or severity language — the brain
    forms its own view from the data; this only states what happened.
    """
    if trigger is EventTrigger.CGM_THRESHOLD_CROSSED:
        who = patient_name or "The patient"
        readable = _CGM_READABLE[_crossing(anchor)]
        return (
            f"{who}'s glucose just crossed into the {readable} range, reading "
            f"{anchor.value} {anchor.unit}. Investigate what led up to this using "
            f"their recent data, and decide whether a brief, grounded check-in "
            f"would genuinely help them right now."
        )
    raise ValueError(f"frame_event: {trigger} is not wired to the brain yet")
