"""Data access for progress trends.

Three sources, each already the single source of truth for its domain:
ClickHouse vitals summary (labs/vitals), stored daily CGM reports (glucose),
Postgres DailyTask + PlayerProfile (engagement). No new write path.
"""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.core.clickhouse_store import ClickHouseStore
from lib.models.care_intent import CareIntent
from lib.models.care_intent_event import CareIntentEvent
from lib.models.gamification import DailyTask, PlayerProfile
from lib.models.patient import Patient
from lib.models.patient_body_composition_record import (
    PatientBodyCompositionRecord,
)
from lib.models.patient_smbg import PatientSMBG

logger = logging.getLogger(__name__)

# Confirmed body-composition columns surfaced as progress series, keyed by the
# canonical metric key the frontend/registry already uses.
_BODY_COMPOSITION_COLUMNS = {
    "weight": "weight_kg",
    "skeletal_muscle_mass": "skeletal_muscle_mass_kg",
    "percent_body_fat": "percent_body_fat",
    "visceral_fat_level": "visceral_fat_level",
    "body_fat_mass": "body_fat_mass_kg",
    "skeletal_muscle_index": "skeletal_muscle_index",
}


class ProgressRepository:
    def __init__(self, clickhouse_store: ClickHouseStore):
        self.clickhouse_store = clickhouse_store

    async def vitals_daily(
        self, patient_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        """Daily avg per vital type — rows are {date, type, avg, min, max, count}.
        query_vitals_summary is sync (clickhouse-driver), so run it off the loop."""
        try:
            return await asyncio.to_thread(
                self.clickhouse_store.query_vitals_summary, patient_id, start, end
            )
        except Exception:
            logger.exception("progress vitals query failed")
            return []

    async def task_completion_daily(
        self, pid, start: date, end: date, session: AsyncSession
    ) -> list[tuple[date, float]]:
        """Per-day task completion % over the range."""
        rows = (await session.execute(
            select(
                DailyTask.task_date,
                func.count().label("total"),
                func.sum(case((DailyTask.status == "completed", 1), else_=0)).label("done"),
            )
            .where(
                DailyTask.patient_id == pid,
                DailyTask.task_date >= start,
                DailyTask.task_date <= end,
            )
            .group_by(DailyTask.task_date)
        )).all()
        out: list[tuple[date, float]] = []
        for task_date, total, done in rows:
            if total:
                out.append((task_date, round((done or 0) / total * 100, 1)))
        return out

    async def clinical_profile(
        self, pid, session: AsyncSession
    ) -> tuple[float | None, bool, str | None, float | None]:
        """(age, is_pregnant, diabetes_type, bmi) — the facts that set glucose
        target tiers and whether reducing calories/carbs is a care goal.
        Pregnancy is true if flagged in either reproductive_health or history."""
        patient = (await session.execute(
            select(Patient).options(
                selectinload(Patient.reproductive_health),
                selectinload(Patient.diabetic_history),
            ).where(Patient.patient_id == pid)
        )).scalar_one_or_none()
        if patient is None:
            return None, False, None, None
        repro = patient.reproductive_health
        history = patient.diabetic_history
        is_pregnant = bool((repro and repro.is_pregnant) or (history and history.is_pregnant))
        diabetes_type = history.type_of_diabetes if history else None
        h = patient.height_cm or patient.height
        w = patient.weight_kg or patient.weight
        bmi = round(w / (h / 100) ** 2, 1) if h and w and h > 0 else None
        return patient.age, is_pregnant, diabetes_type, bmi

    async def streak(self, pid, session: AsyncSession) -> tuple[int, int]:
        profile = (await session.execute(
            select(PlayerProfile).where(PlayerProfile.patient_id == pid)
        )).scalar_one_or_none()
        if profile is None:
            return 0, 0
        return profile.current_streak or 0, profile.longest_streak or 0

    async def smbg_daily(
        self, pid, start_dt: datetime, end_dt: datetime, session: AsyncSession
    ) -> list[tuple[date, float]]:
        """Daily average finger-stick glucose over the range (non-CGM patients)."""
        rows = (await session.execute(
            select(
                func.date(PatientSMBG.reading_time).label("d"),
                func.avg(PatientSMBG.glucose_level),
            )
            .where(
                PatientSMBG.patient_id == pid,
                PatientSMBG.reading_time >= start_dt,
                PatientSMBG.reading_time < end_dt,
            )
            .group_by(func.date(PatientSMBG.reading_time))
        )).all()
        out: list[tuple[date, float]] = []
        for d, avg in rows:
            dd = d if isinstance(d, date) else date.fromisoformat(str(d))
            out.append((dd, round(float(avg), 1)))
        return out

    async def smbg_by_type_daily(
        self, pid, start_dt: datetime, end_dt: datetime, session: AsyncSession
    ) -> dict[str, list[tuple[date, float]]]:
        """Daily average finger-stick glucose split by reading type
        (fasting/before_meal/after_meal/random) — the tagged view a provider
        reads instead of the blended average."""
        rows = (await session.execute(
            select(
                PatientSMBG.type,
                func.date(PatientSMBG.reading_time).label("d"),
                func.avg(PatientSMBG.glucose_level),
            )
            .where(
                PatientSMBG.patient_id == pid,
                PatientSMBG.reading_time >= start_dt,
                PatientSMBG.reading_time < end_dt,
            )
            .group_by(PatientSMBG.type, func.date(PatientSMBG.reading_time))
        )).all()
        out: dict[str, list[tuple[date, float]]] = {}
        for t, d, avg in rows:
            dd = d if isinstance(d, date) else date.fromisoformat(str(d))
            out.setdefault(str(t or "random"), []).append((dd, round(float(avg), 1)))
        return out

    async def body_composition_daily(
        self, pid, start_dt: datetime, end_dt: datetime, session: AsyncSession
    ) -> dict[str, list[tuple[date, float]]]:
        """Confirmed body-composition scans in range as per-metric point series.

        Each scan is one point (episodic, not daily); values are read straight
        from the promoted typed columns, so no recomputation or interpretation.
        """
        model = PatientBodyCompositionRecord
        when = func.coalesce(model.test_datetime, model.created_at)
        rows = (await session.execute(
            select(
                when.label("when"),
                *[getattr(model, col) for col in _BODY_COMPOSITION_COLUMNS.values()],
            )
            .where(
                model.patient_id == pid,
                model.status == "confirmed",
                when >= start_dt,
                when < end_dt,
            )
            .order_by(when)
        )).all()

        out: dict[str, list[tuple[date, float]]] = {}
        for row in rows:
            when_value = row[0]
            if when_value is None:
                continue
            d = when_value.date() if isinstance(when_value, datetime) else when_value
            for idx, key in enumerate(_BODY_COMPOSITION_COLUMNS, start=1):
                value = row[idx]
                if value is not None:
                    out.setdefault(key, []).append((d, round(float(value), 2)))
        return out

    async def care_intent_adherence(
        self, pid, start: date, end: date, session: AsyncSession
    ) -> list[dict]:
        """Per active care intent: followed/missed/unclear day-counts over the
        range, plus the most recent barrier note. Daily verdicts are written by
        the monitor's morning scan (one row per intent per day)."""
        intents = (await session.execute(
            select(CareIntent)
            .where(CareIntent.patient_id == pid, CareIntent.status == "active")
            .order_by(CareIntent.created_at)
        )).scalars().all()
        if not intents:
            return []
        ids = [i.care_intent_id for i in intents]

        counts = (await session.execute(
            select(
                CareIntentEvent.care_intent_id,
                CareIntentEvent.status,
                func.count().label("n"),
            )
            .where(
                CareIntentEvent.care_intent_id.in_(ids),
                CareIntentEvent.event_date >= start,
                CareIntentEvent.event_date <= end,
            )
            .group_by(CareIntentEvent.care_intent_id, CareIntentEvent.status)
        )).all()
        tally: dict = {}
        for cid, status, n in counts:
            tally.setdefault(cid, {})[status] = n

        # Most recent barrier note per intent — desc order, first seen wins.
        note_rows = (await session.execute(
            select(CareIntentEvent.care_intent_id, CareIntentEvent.note)
            .where(
                CareIntentEvent.care_intent_id.in_(ids),
                CareIntentEvent.note.isnot(None),
                CareIntentEvent.event_date >= start,
                CareIntentEvent.event_date <= end,
            )
            .order_by(CareIntentEvent.event_date.desc())
        )).all()
        last_note: dict = {}
        for cid, note in note_rows:
            last_note.setdefault(cid, note)

        out: list[dict] = []
        for i in intents:
            t = tally.get(i.care_intent_id, {})
            followed = int(t.get("followed", 0))
            missed = int(t.get("missed", 0))
            decided = followed + missed
            out.append({
                "care_intent_id": str(i.care_intent_id),
                "summary": i.patient_summary,
                "author": i.author_name,
                "followed": followed,
                "missed": missed,
                "unclear": int(t.get("unclear", 0)),
                "rate": round(followed / decided, 2) if decided else None,
                "last_note": last_note.get(i.care_intent_id),
            })
        return out
