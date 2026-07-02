"""Deterministic fixture doubles for the eval harness.

The agent runs with a real gateway and real prompts; only the data layer
is faked so every eval case sees exactly the records its YAML declares.
Fixture dates are generated relative to "now" so cases like "yesterday"
stay valid forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from lib.ai_foundation.memory.base import MemoryFact
from lib.ai_foundation.retrieval.base import RetrievalRequest, RetrievalResult
from lib.ai_foundation.retrieval.qdrant import _expand_data_types

EVAL_PATIENT_ID = "eval-patient-0001"
EVAL_PATIENT_NAME = "Asha"
EVAL_TIMEZONE = "Asia/Kolkata"


def _epoch_ms(dt: datetime) -> float:
    return dt.timestamp() * 1000


def _day(days_ago: int, hour: int = 12) -> datetime:
    # Dates in the PATIENT'S timezone — the agent resolves "yesterday" from
    # local_time (IST), so a UTC-based fixture would be one day off in the
    # IST evening.
    now = datetime.now(ZoneInfo(EVAL_TIMEZONE))
    return (now - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0,
    )


def default_records() -> list[dict[str, Any]]:
    """A realistic week of data for the default eval patient.

    Ground truth the judge and checks refer to:
    - Yesterday's glucose: avg 148 mg/dL, TIR 72%, one spike to 214 after lunch
    - Yesterday's meals: poha breakfast, rice+dal lunch (the spike meal)
    - One hypo event 3 days ago (54 mg/dL, overnight)
    - Steps around 6,500/day
    - NO sleep data, NO vitals data (fabrication traps rely on this)
    """
    records: list[dict[str, Any]] = []

    for days_ago in range(1, 8):
        d = _day(days_ago)
        avg = 148 if days_ago == 1 else 138 + (days_ago % 3) * 4
        tir = 72 if days_ago == 1 else 78
        records.append({
            "data_type": "cgm_summary_stats",
            "start_time": _epoch_ms(d.replace(hour=0)),
            "end_time": _epoch_ms(d.replace(hour=23)),
            "text_repr": (
                f"CGM daily summary for {d.date().isoformat()}: "
                f"average glucose {avg} mg/dL, time in range {tir}%, "
                f"GMI 6.8%, readings 288."
            ),
        })

    spike_day = _day(1)
    records.append({
        "data_type": "rapid_spike_event",
        "start_time": _epoch_ms(spike_day.replace(hour=13)),
        "end_time": _epoch_ms(spike_day.replace(hour=14)),
        "text_repr": (
            f"Rapid glucose spike on {spike_day.date().isoformat()} at 1:15 PM: "
            f"rose from 132 to 214 mg/dL in 45 minutes, shortly after lunch."
        ),
    })

    hypo_day = _day(3)
    records.append({
        "data_type": "hypo_event",
        "start_time": _epoch_ms(hypo_day.replace(hour=3)),
        "end_time": _epoch_ms(hypo_day.replace(hour=4)),
        "text_repr": (
            f"Hypoglycemia event on {hypo_day.date().isoformat()} at 3:20 AM: "
            f"glucose dropped to 54 mg/dL, duration 35 minutes, overnight."
        ),
    })

    records.append({
        "data_type": "meal",
        "start_time": _epoch_ms(_day(1, hour=8)),
        "end_time": _epoch_ms(_day(1, hour=8)),
        "text_repr": (
            f"Meal on {_day(1).date().isoformat()} 8:30 AM (breakfast): "
            f"poha with peanuts — approx 310 kcal, 52g carbs, 9g protein."
        ),
    })
    records.append({
        "data_type": "meal",
        "start_time": _epoch_ms(_day(1, hour=13)),
        "end_time": _epoch_ms(_day(1, hour=13)),
        "text_repr": (
            f"Meal on {_day(1).date().isoformat()} 1:00 PM (lunch): "
            f"white rice with dal and papad — approx 620 kcal, 96g carbs, 16g protein."
        ),
    })

    for days_ago in range(1, 8):
        d = _day(days_ago)
        steps = 6500 + (days_ago % 4) * 300
        records.append({
            "data_type": "fitness_overview",
            "start_time": _epoch_ms(d.replace(hour=0)),
            "end_time": _epoch_ms(d.replace(hour=23)),
            "text_repr": (
                f"Fitness overview for {d.date().isoformat()}: {steps} steps, "
                f"22 active minutes, 1.9 km walked."
            ),
        })

    records.append({
        "data_type": "medication",
        "start_time": _epoch_ms(_day(30)),
        "end_time": _epoch_ms(_day(0)),
        "text_repr": "Current medications: Metformin 500mg twice daily (morning, evening).",
    })

    records.append({
        "data_type": "profile",
        "start_time": _epoch_ms(_day(365)),
        "end_time": _epoch_ms(_day(0)),
        "text_repr": (
            f"Patient profile: {EVAL_PATIENT_NAME}, 42-year-old female, "
            f"type 2 diabetes diagnosed 2022, height 158cm, weight 68kg."
        ),
    })

    return records


def default_facts() -> list[MemoryFact]:
    return [
        MemoryFact(key="diabetes_type", value="type 2", category="condition", is_permanent=True),
        MemoryFact(key="dietary_preference", value="vegetarian", category="preference"),
        MemoryFact(key="health_goal", value="improve time in range above 75%", category="goal"),
    ]


# ── Fakes ────────────────────────────────────────────────────────────────────


class FixtureRetriever:
    """Drop-in for QdrantRetriever backed by an in-memory record list."""

    name = "fixture"

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def _matches(self, rec: dict[str, Any], request: RetrievalRequest) -> bool:
        types = _expand_data_types(request.data_types) if request.data_types else []
        if types and rec["data_type"] not in types:
            # profile is always relevant (mirrors QdrantRetriever's should-branch)
            if rec["data_type"] != "profile":
                return False
        # Compare by LOCAL date, not raw epoch vs UTC midnight — fixture
        # records are anchored to the patient's day (IST), and "yesterday"
        # means the local calendar day.
        if rec["data_type"] not in ("profile", "medication"):
            rec_date = datetime.fromtimestamp(
                rec["start_time"] / 1000, ZoneInfo(EVAL_TIMEZONE),
            ).date()
            if request.date_start and rec_date < datetime.fromisoformat(request.date_start[:10]).date():
                return False
            if request.date_end and rec_date > datetime.fromisoformat(request.date_end[:10]).date():
                return False
        return True

    async def retrieve_filtered(self, request: RetrievalRequest) -> list[RetrievalResult]:
        if not request.patient_ids:
            return []
        hits = [r for r in self._records if self._matches(r, request)]
        hits.sort(key=lambda r: r["start_time"], reverse=True)
        return [
            RetrievalResult(
                payload={**r, "patient_id": request.patient_ids[0]},
                source="fixture",
                data_type=r["data_type"],
            )
            for r in hits[: request.limit]
        ]

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        # Semantic search degrades to filtered scroll — deterministic on purpose.
        return await self.retrieve_filtered(request)


class FakeMemory:
    """In-memory MemoryStore double."""

    def __init__(self, facts: list[MemoryFact] | None = None) -> None:
        self.facts: dict[str, MemoryFact] = {f.key: f for f in (facts or [])}

    async def get_patient_facts(self, patient_id: str) -> list[MemoryFact]:
        return list(self.facts.values())

    async def upsert_patient_facts(self, patient_id: str, facts: list[MemoryFact]) -> None:
        for f in facts:
            self.facts[f.key] = f

    async def delete_patient_fact(self, patient_id: str, key: str) -> bool:
        return self.facts.pop(key, None) is not None

    async def get_thread_turns(self, thread_id: str, limit: int = 10) -> list:
        return []

    async def get_thread_summary(self, thread_id: str):
        return None


class FakeResolver:
    async def resolve_names(self, patient_ids: list[str]) -> dict[str, str]:
        return {pid: EVAL_PATIENT_NAME for pid in patient_ids}

    async def resolve_timezones(self, patient_ids: list[str]) -> dict[str, str]:
        return {pid: EVAL_TIMEZONE for pid in patient_ids}


class FakeInsightTracker:
    async def get_history(self, patient_id: str, limit: int = 5, **kwargs) -> list:
        return []


class FakeMetabolicService:
    async def risk_profile(self, patient_id: str) -> dict[str, Any]:
        return {}
