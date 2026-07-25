"""Live smoke test for the one-brain proactive monitor.

Runs a real event through the real pipeline — HealthQueryAgent.run_proactive
against live Qdrant/Postgres/Mongo + the real model gateway — and prints the
insight the brain produced. It does NOT send a push (delivery lives in the
event_scan worker), so it is safe to run against a real patient id.

Requires the same env/credentials the app uses (DB URLs, model API keys).

Usage:
    python scripts/smoke_proactive_one_brain.py <patient_id>
    python scripts/smoke_proactive_one_brain.py <patient_id> --kind severe_hypo --value 48
    python scripts/smoke_proactive_one_brain.py <patient_id> --cron          # daily digest
    python scripts/smoke_proactive_one_brain.py <patient_id> --trigger meal_logged --entity <meal_id>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.core.container import container
from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    CGMThresholdCrossedAnchor,
    EventTrigger,
    MealLoggedAnchor,
    MedicationMissedAnchor,
    SMBGLoggedAnchor,
    SymptomLoggedAnchor,
)


def _anchor(trigger: EventTrigger, args):
    now = "2026-07-22T10:00:00Z"
    if trigger is EventTrigger.CGM_THRESHOLD_CROSSED:
        return CGMThresholdCrossedAnchor(kind=args.kind, value=args.value, unit="mg/dL", time=now)
    if trigger is EventTrigger.MEAL_LOGGED:
        return MealLoggedAnchor(meal_id=args.entity, event_time=now)
    if trigger is EventTrigger.SMBG_LOGGED:
        return SMBGLoggedAnchor(reading_id=args.entity, event_time=now)
    if trigger is EventTrigger.SYMPTOM_LOGGED:
        return SymptomLoggedAnchor(symptom_entry_id=args.entity, event_time=now)
    if trigger is EventTrigger.MEDICATION_MISSED:
        return MedicationMissedAnchor(daily_task_id=args.entity, slot="morning",
                                      medication_name="(smoke)", task_date="2026-07-22", event_time=now)
    raise SystemExit(f"unsupported trigger {trigger}")


async def _run(args) -> None:
    monitor = container.resolve(ProactiveMonitorAgent)
    if monitor._health_agent is None:  # noqa: SLF001 — smoke check
        raise SystemExit("FAIL: no health_agent injected — the monitor is not wired to the one brain")

    if args.cron:
        print(f"→ cron digest for {args.patient_id} ...")
        result = await monitor.scan_patient(args.patient_id, args.name)
    else:
        trigger = EventTrigger(args.trigger)
        anchor = _anchor(trigger, args)
        print(f"→ {trigger.value} for {args.patient_id} ...")
        result = await monitor.scan_patient(args.patient_id, args.name, trigger=trigger, anchor=anchor)

    if result.error:
        raise SystemExit(f"FAIL: {result.error}")
    if not result.insights:
        print("OK (brain declined — no notification warranted)")
        return
    for i in result.insights:
        print("\n--- insight (NOT delivered) ---")
        print(f"category : {i.category.value}")
        print(f"severity : {i.severity.value}")
        print(f"title    : {i.title}")
        print(f"body     : {i.body}")
        print(f"follow-up: {i.suggested_query}")
    print(f"\nOK ({result.scan_duration_ms} ms)")


def main() -> None:
    p = argparse.ArgumentParser(description="Live smoke test — one-brain proactive monitor")
    p.add_argument("patient_id")
    p.add_argument("--name", default=None, help="patient first name for the greeting")
    p.add_argument("--cron", action="store_true", help="run the scheduled digest instead of an event")
    p.add_argument("--trigger", default="cgm_threshold_crossed",
                   help="event trigger (default cgm_threshold_crossed)")
    p.add_argument("--kind", default="hypo", help="CGM crossing kind (hypo/severe_hypo/hyper/...)")
    p.add_argument("--value", type=int, default=62, help="CGM reading mg/dL")
    p.add_argument("--entity", default="", help="entity id for meal/smbg/symptom/medication triggers")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
