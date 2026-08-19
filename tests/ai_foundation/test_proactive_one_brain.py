"""The monitor detects + classifies deterministically and delegates the words
to the one brain.

Covers the CGM-threshold slice: framing/tier/classification are code, not LLM;
scan_patient routes a crossing to HealthQueryAgent.run_proactive and wraps the
result in the same ScanResult the delivery path already consumes; the brain may
decline (notify=False → no insight).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from lib.services.cgm_threshold_detector import CGMCrossingKind
from lib.ai_foundation.agents.health_query.contracts import ProactiveNarration
from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningTier
from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    CGMThresholdCrossedAnchor, EventTrigger, InsightCategory, InsightSeverity,
    MealLoggedAnchor, SMBGLoggedAnchor, SymptomLoggedAnchor,
)
from lib.ai_foundation.agents.proactive_monitor.event_framing import (
    classify_event, frame_event, trigger_tier,
)

_CGM = EventTrigger.CGM_THRESHOLD_CROSSED


def _anchor(kind: str, value: int = 65):
    return CGMThresholdCrossedAnchor(kind=kind, value=value, unit="mg/dL",
                                     time="2026-07-21T10:00:00Z")


# ── deterministic framing / classification (no LLM) ────────────────────────


@pytest.mark.parametrize("kind,tier", [
    (CGMCrossingKind.SEVERE_HYPO, ReasoningTier.ADVANCED),
    (CGMCrossingKind.HYPO, ReasoningTier.ADVANCED),
    (CGMCrossingKind.HYPER, ReasoningTier.STANDARD),
    (CGMCrossingKind.SEVERE_HYPER, ReasoningTier.STANDARD),
    (CGMCrossingKind.RAPID_DROP, ReasoningTier.STANDARD),
    (CGMCrossingKind.RAPID_SPIKE, ReasoningTier.STANDARD),
])
def test_tier_is_deeper_for_safety_lows(kind, tier):
    assert trigger_tier(_CGM, _anchor(kind.value)) is tier


@pytest.mark.parametrize("kind,category,severity", [
    (CGMCrossingKind.SEVERE_HYPO, InsightCategory.GLUCOSE_HYPO, InsightSeverity.ALERT),
    (CGMCrossingKind.HYPO, InsightCategory.GLUCOSE_HYPO, InsightSeverity.WARNING),
    (CGMCrossingKind.SEVERE_HYPER, InsightCategory.GLUCOSE_SPIKE, InsightSeverity.WARNING),
    (CGMCrossingKind.HYPER, InsightCategory.GLUCOSE_SPIKE, InsightSeverity.ATTENTION),
    (CGMCrossingKind.RAPID_DROP, InsightCategory.GLUCOSE_RAPID_DROP, InsightSeverity.WARNING),
    (CGMCrossingKind.RAPID_SPIKE, InsightCategory.GLUCOSE_RAPID_SPIKE, InsightSeverity.ATTENTION),
])
def test_severity_is_fixed_by_crossing_not_the_model(kind, category, severity):
    assert classify_event(_CGM, _anchor(kind.value)) == (category, severity)


def test_frame_states_the_reading_without_interpretation():
    text = frame_event(_CGM, _anchor("hypo", 62), patient_name="Rohan")
    assert "Rohan" in text and "62 mg/dL" in text and "low" in text


# ── delegation: monitor → one brain → ScanResult ───────────────────────────


def _monitor(narration: ProactiveNarration):
    brain = AsyncMock()
    brain.run_proactive = AsyncMock(return_value=narration)
    agent = ProactiveMonitorAgent(gateway=AsyncMock(), qdrant=None, health_agent=brain)
    return agent, brain


@pytest.mark.asyncio
async def test_crossing_delegates_to_brain_and_wraps_insight():
    agent, brain = _monitor(ProactiveNarration(
        notify=True, title="Glucose is low",
        body="You're at 65 — have a quick snack and it should come back up.",
        suggested_query="What can cause a low?"))

    result = await agent.scan_patient("p1", trigger=_CGM, anchor=_anchor("hypo", 65))

    assert len(result.insights) == 1
    ins = result.insights[0]
    assert ins.body.startswith("You're at 65")
    # severity/category are deterministic, not from the brain
    assert ins.category is InsightCategory.GLUCOSE_HYPO
    assert ins.severity is InsightSeverity.WARNING
    # a safety low was investigated at the deepest tier
    assert brain.run_proactive.call_args.kwargs["tier"] is ReasoningTier.ADVANCED


@pytest.mark.asyncio
async def test_brain_declining_yields_no_insight():
    agent, _ = _monitor(ProactiveNarration(notify=False))
    result = await agent.scan_patient("p1", trigger=_CGM, anchor=_anchor("hyper", 190))
    assert result.insights == [] and result.error is None


# ── all event triggers route to the brain with capped, fixed classification ─


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger,anchor,category,severity,tier", [
    (EventTrigger.MEAL_LOGGED, MealLoggedAnchor(meal_id="m1"),
     InsightCategory.GENERAL, InsightSeverity.INFO, ReasoningTier.STANDARD),
    (EventTrigger.SYMPTOM_LOGGED, SymptomLoggedAnchor(symptom_entry_id="s1"),
     InsightCategory.GENERAL, InsightSeverity.ATTENTION, ReasoningTier.STANDARD),
    (EventTrigger.SMBG_LOGGED, SMBGLoggedAnchor(reading_id="r1"),
     InsightCategory.GENERAL, InsightSeverity.ATTENTION, ReasoningTier.STANDARD),
])
async def test_every_event_trigger_routes_to_the_brain(trigger, anchor, category, severity, tier):
    agent, brain = _monitor(ProactiveNarration(notify=True, title="t", body="a grounded note"))
    result = await agent.scan_patient("p1", trigger=trigger, anchor=anchor)
    assert len(result.insights) == 1
    assert result.insights[0].category is category
    assert result.insights[0].severity is severity
    assert brain.run_proactive.call_args.kwargs["tier"] is tier


# ── cron digest also runs on the one brain ─────────────────────────────────


@pytest.mark.asyncio
async def test_cron_digest_uses_the_brain():
    agent, brain = _monitor(ProactiveNarration(
        notify=True, title="Morning check-in", body="You slept well and glucose held steady."))
    insights = await agent._cron_narration("p1", "Rohan", "morning")
    assert len(insights) == 1
    assert insights[0].category is InsightCategory.DAILY_BRIEF
    assert insights[0].severity is InsightSeverity.INFO
    assert brain.run_proactive.call_args.kwargs["tier"] is ReasoningTier.ADVANCED


@pytest.mark.asyncio
async def test_cron_digest_declines_when_nothing_noteworthy():
    agent, _ = _monitor(ProactiveNarration(notify=False))
    assert await agent._cron_narration("p1", "Rohan", "evening") == []


# ── SMBG graded by its actual reading; entity pinned into context ──────────


def test_glucose_value_grading():
    from lib.ai_foundation.agents.proactive_monitor.event_framing import classify_glucose_value
    assert classify_glucose_value(50) == (InsightCategory.GLUCOSE_HYPO, InsightSeverity.ALERT)
    assert classify_glucose_value(65) == (InsightCategory.GLUCOSE_HYPO, InsightSeverity.WARNING)
    assert classify_glucose_value(120) == (InsightCategory.GENERAL, InsightSeverity.INFO)
    assert classify_glucose_value(200) == (InsightCategory.GLUCOSE_SPIKE, InsightSeverity.ATTENTION)
    assert classify_glucose_value(260) == (InsightCategory.GLUCOSE_SPIKE, InsightSeverity.WARNING)


def test_event_ref_targets_the_logged_entity():
    from lib.ai_foundation.agents.proactive_monitor.event_framing import event_ref
    from lib.ai_foundation.agents.core.refs import RefType
    from lib.ai_foundation.agents.proactive_monitor.contracts import MealLoggedAnchor
    ref = event_ref(EventTrigger.MEAL_LOGGED, MealLoggedAnchor(meal_id="m9"))
    assert ref.type is RefType.MEAL and ref.id == "m9"
    # a CGM crossing has no poolable entity → no ref
    assert event_ref(_CGM, _anchor("hypo")) is None


def _qdrant_returning(payloads):
    from lib.ai_foundation.retrieval.base import RetrievalResult
    q = AsyncMock()
    q.retrieve_filtered = AsyncMock(return_value=[
        RetrievalResult(payload=p, source="test", data_type="smbg") for p in payloads
    ])
    return q


@pytest.mark.asyncio
async def test_smbg_low_reading_is_graded_by_value():
    from lib.ai_foundation.agents.core.refs import RefType
    from lib.ai_foundation.agents.proactive_monitor.contracts import SMBGLoggedAnchor

    agent, brain = _monitor(ProactiveNarration(notify=True, title="Low", body="You're at 50 — treat it."))
    agent._qdrant = _qdrant_returning([{"reading_id": "r1", "glucose_mgdl": 50}])
    result = await agent.scan_patient("p1", trigger=EventTrigger.SMBG_LOGGED,
                                      anchor=SMBGLoggedAnchor(reading_id="r1"))
    ins = result.insights[0]
    # a manual low is graded like a sensor low — not a bland ack
    assert ins.category is InsightCategory.GLUCOSE_HYPO
    assert ins.severity is InsightSeverity.ALERT
    assert brain.run_proactive.call_args.kwargs["tier"] is ReasoningTier.ADVANCED
    # the exact reading is pinned into the brain's context
    refs = brain.run_proactive.call_args.kwargs["refs"]
    assert refs and refs[0].type is RefType.SMBG and refs[0].id == "r1"


@pytest.mark.asyncio
async def test_smbg_falls_back_to_fixed_class_when_value_unavailable():
    from lib.ai_foundation.agents.proactive_monitor.contracts import SMBGLoggedAnchor
    agent, _ = _monitor(ProactiveNarration(notify=True, title="Noted", body="Reading logged."))
    agent._qdrant = _qdrant_returning([])  # reading not in the store yet
    result = await agent.scan_patient("p1", trigger=EventTrigger.SMBG_LOGGED,
                                      anchor=SMBGLoggedAnchor(reading_id="r1"))
    ins = result.insights[0]
    assert ins.category is InsightCategory.GENERAL and ins.severity is InsightSeverity.ATTENTION
