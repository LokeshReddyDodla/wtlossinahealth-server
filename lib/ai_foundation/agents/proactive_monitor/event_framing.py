"""Deterministic framing + classification for events handed to the one brain.

The brain (HealthQueryAgent) writes the words. These functions decide — from
the trigger and its anchor alone, never the LLM — three things:

  * how the event is described to the brain (``frame_event``),
  * how deep the brain may investigate (``trigger_tier``),
  * the clinical category + severity of any resulting insight
    (``classify_event``),

so danger level is never the model's to invent.

Glucose crossings from the CGM sensor carry the reading in the anchor, so their
severity is graded by the crossing kind. The manual/log events (meal, SMBG,
symptom, missed dose) carry only an entity id — the brain fetches the details —
so they take a conservative fixed prominence; the brain's grounded copy conveys
the specifics. Cron (daily brief) is not handled here.
"""

from __future__ import annotations

from lib.services.cgm_threshold_detector import CGMCrossingKind
from lib.services.clinical_constants import (
    GLUCOSE_HYPER_MGDL,
    GLUCOSE_HYPO_MGDL,
    GLUCOSE_SEVERE_HYPER_MGDL,
    GLUCOSE_SEVERE_HYPO_MGDL,
)
from lib.ai_foundation.agents.core.refs import Ref, RefType
from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningTier
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    EventTrigger,
    InsightCategory,
    InsightSeverity,
    TriggerAnchor,
)

_CGM = EventTrigger.CGM_THRESHOLD_CROSSED

# CGM crossings where silence is riskiest — the brain gets the deepest budget.
_CGM_SAFETY = frozenset({CGMCrossingKind.SEVERE_HYPO, CGMCrossingKind.HYPO})

# Category + severity per crossing. Severity is clinical authority (it drives
# the broker's urgent routing + channel), so it is fixed here, not by the model.
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

# Manual/log events: conservative fixed category, severity, and tier. Symptoms
# are capped at ATTENTION (no triage rules exist); a missed dose is coaching,
# never dosing advice; a meal is wellness. SMBG takes ATTENTION because a
# finger-stick can be out of range — the brain fetches the value and says so.
_EVENT_CLASS: dict[EventTrigger, tuple[InsightCategory, InsightSeverity]] = {
    EventTrigger.MEAL_LOGGED: (InsightCategory.GENERAL, InsightSeverity.INFO),
    EventTrigger.SMBG_LOGGED: (InsightCategory.GENERAL, InsightSeverity.ATTENTION),
    EventTrigger.SYMPTOM_LOGGED: (InsightCategory.GENERAL, InsightSeverity.ATTENTION),
    EventTrigger.MEDICATION_MISSED: (InsightCategory.COACHING_MEDICATION, InsightSeverity.ATTENTION),
}

_EVENT_TIER: dict[EventTrigger, ReasoningTier] = {
    EventTrigger.MEAL_LOGGED: ReasoningTier.STANDARD,
    EventTrigger.SMBG_LOGGED: ReasoningTier.STANDARD,
    EventTrigger.SYMPTOM_LOGGED: ReasoningTier.STANDARD,
    EventTrigger.MEDICATION_MISSED: ReasoningTier.BASIC,
}

# Neutral, interpretation-free descriptions — the brain forms its own view.
_EVENT_FRAME: dict[EventTrigger, str] = {
    EventTrigger.MEAL_LOGGED:
        "just logged a meal. Investigate how it fits their day and recent "
        "patterns, and decide whether a brief, grounded observation would help.",
    EventTrigger.SMBG_LOGGED:
        "just logged a finger-prick glucose reading. Look up the reading and "
        "its context, and decide whether a brief, grounded check-in would help.",
    EventTrigger.SYMPTOM_LOGGED:
        "just logged a symptom. Look at their recent data for context and decide "
        "whether a brief, supportive note would help — do not attempt triage.",
    EventTrigger.MEDICATION_MISSED:
        "appears to have missed a scheduled medication dose. Decide whether a "
        "gentle reminder would help — never suggest a dose or a schedule change.",
}


# A logged entity the brain should pin as context (so it reasons about THIS
# meal/reading, not just recent history). CGM crossings + missed doses carry no
# poolable entity id, so they get no ref.
_EVENT_REF: dict[EventTrigger, tuple[RefType, str]] = {
    EventTrigger.MEAL_LOGGED: (RefType.MEAL, "meal_id"),
    EventTrigger.SMBG_LOGGED: (RefType.SMBG, "reading_id"),
    EventTrigger.SYMPTOM_LOGGED: (RefType.SYMPTOM, "symptom_entry_id"),
}


def _crossing(anchor: TriggerAnchor) -> CGMCrossingKind:
    return CGMCrossingKind(anchor.kind)  # raises on an unknown kind — fail loud, not silent


def event_ref(trigger: EventTrigger, anchor: TriggerAnchor) -> Ref | None:
    """The entity the event is about, for pinning into the brain's context."""
    spec = _EVENT_REF.get(trigger)
    if spec is None:
        return None
    ref_type, id_attr = spec
    entity_id = getattr(anchor, id_attr, None)
    return Ref(type=ref_type, id=entity_id) if entity_id else None


def classify_glucose_value(value: float) -> tuple[InsightCategory, InsightSeverity]:
    """Grade a discrete glucose reading (e.g. a finger-stick) by the shared ADA
    thresholds — the same scale as CGM crossings, so a manual low is treated as
    seriously as a sensor low, not flattened to a generic acknowledgement."""
    if value <= GLUCOSE_SEVERE_HYPO_MGDL:
        return InsightCategory.GLUCOSE_HYPO, InsightSeverity.ALERT
    if value < GLUCOSE_HYPO_MGDL:
        return InsightCategory.GLUCOSE_HYPO, InsightSeverity.WARNING
    if value >= GLUCOSE_SEVERE_HYPER_MGDL:
        return InsightCategory.GLUCOSE_SPIKE, InsightSeverity.WARNING
    if value > GLUCOSE_HYPER_MGDL:
        return InsightCategory.GLUCOSE_SPIKE, InsightSeverity.ATTENTION
    return InsightCategory.GENERAL, InsightSeverity.INFO


def severity_tier(severity: InsightSeverity) -> ReasoningTier:
    """How deep to investigate, scaled to how serious the reading is."""
    if severity in (InsightSeverity.ALERT, InsightSeverity.WARNING):
        return ReasoningTier.ADVANCED
    if severity is InsightSeverity.ATTENTION:
        return ReasoningTier.STANDARD
    return ReasoningTier.BASIC


def is_wired(trigger: EventTrigger) -> bool:
    """Whether this trigger is answered by the one brain (vs. the legacy scan)."""
    return trigger is _CGM or trigger in _EVENT_CLASS


def trigger_tier(trigger: EventTrigger, anchor: TriggerAnchor) -> ReasoningTier:
    if trigger is _CGM:
        return ReasoningTier.ADVANCED if _crossing(anchor) in _CGM_SAFETY else ReasoningTier.STANDARD
    if trigger in _EVENT_TIER:
        return _EVENT_TIER[trigger]
    raise ValueError(f"trigger_tier: {trigger} is not wired to the brain")


def classify_event(
    trigger: EventTrigger, anchor: TriggerAnchor,
) -> tuple[InsightCategory, InsightSeverity]:
    if trigger is _CGM:
        return _CGM_CLASS[_crossing(anchor)]
    if trigger in _EVENT_CLASS:
        return _EVENT_CLASS[trigger]
    raise ValueError(f"classify_event: {trigger} is not wired to the brain")


def frame_event(
    trigger: EventTrigger, anchor: TriggerAnchor, patient_name: str | None = None,
) -> str:
    who = patient_name or "The patient"
    if trigger is _CGM:
        readable = _CGM_READABLE[_crossing(anchor)]
        return (
            f"{who}'s glucose just crossed into the {readable} range, reading "
            f"{anchor.value} {anchor.unit}. Investigate what led up to this using "
            f"their recent data, and decide whether a brief, grounded check-in "
            f"would genuinely help them right now."
        )
    if trigger in _EVENT_FRAME:
        return f"{who} {_EVENT_FRAME[trigger]}"
    raise ValueError(f"frame_event: {trigger} is not wired to the brain")


def frame_cron(patient_name: str | None, scan_period: str) -> str:
    """The scheduled (no-trigger) digest ask — a proactive check-in, not a reply.

    The brain reviews all domains and decides whether anything is worth a push;
    unlike an event, there is no single thing that just happened.
    """
    who = patient_name or "the patient"
    when = {"morning": "this morning", "afternoon": "this afternoon",
            "evening": "this evening"}.get(scan_period, "today")
    return (
        f"Produce a short, warm proactive check-in for {who} for {when}. Review "
        f"their recent data across all domains; if there is something genuinely "
        f"useful, grounded, and worth their attention, say it briefly. If nothing "
        f"is noteworthy, do not notify."
    )
