"""Data access for the day view.

Postgres queries are ported from `PatientTimelineService._query_*` (cited per
method) so the fixes encoded there travel with them — but they return typed
payload pieces, not display-string `TimelineEvent`s.

ClickHouse reads fix two issues the feed service has: they run **off the event
loop** (`asyncio.to_thread` — clickhouse-driver is sync) and use **bind params**
instead of f-string interpolation. All reads append `FINAL` (ReplacingMergeTree);
times are patient-local naive wall-clock.
"""

import asyncio
import logging
from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.core.clickhouse_store import ClickHouseStore
from lib.models.gamification import DailyTask
from lib.models.mood_entry import MoodEntry
from lib.models.patient_medication import PatientMedication
from lib.models.patient_smbg import PatientSMBG
from lib.models.patient_workout import PatientWorkout
from lib.models.symptom_entry import SymptomEntry
from lib.schemas.day_view import (
    DoseMarker,
    MoodMarker,
    Point,
    StageSpan,
    SymptomMarker,
    TaskItem,
    VitalMarker,
    WorkoutMarker,
)
from lib.schemas.gamification import SourceType
from lib.services.gamification.task_generator import TaskGeneratorService
from lib.services.day_view.mappers import hour_of

logger = logging.getLogger(__name__)

_SLOT_HOURS = {"MORNING": 9, "AFTERNOON": 14, "EVENING": 20, "NIGHT": 22}
_SLEEP_STAGES = ("sleep_deep", "sleep_light", "sleep_rem", "sleep_awake")


class DayViewRepository:
    def __init__(self, clickhouse_store: ClickHouseStore):
        self.clickhouse_store = clickhouse_store

    # ── ClickHouse (off the event loop, bind params) ─────────────────────────

    async def _ch(self, sql: str, params: dict) -> list[tuple]:
        try:
            return await asyncio.to_thread(
                self.clickhouse_store.client.execute, sql, params
            )
        except Exception:
            logger.exception("day-view clickhouse query failed")
            return []

    async def hr_series(self, patient_id: str, day: date) -> list[Point]:
        """Intraday heart rate for the HR spine (and header avg). ~300 samples/day."""
        rows = await self._ch(
            "SELECT value, time FROM aihealth.vitals_data FINAL "
            "WHERE patient_id = %(pid)s AND type = 'heart_rate' "
            "AND toDate(time) = %(d)s ORDER BY time",
            {"pid": patient_id, "d": str(day)},
        )
        out: list[Point] = []
        for value, ts in rows:
            h = hour_of(ts)
            if h is not None:
                out.append((round(h, 4), float(value)))
        return out

    async def sleep_stage_spans(
        self, patient_id: str, day_start: datetime, day_end: datetime
    ) -> list[StageSpan]:
        """Timed stage segments overlapping the day → hypnogram. Hours are relative
        to `day_start`, clipped to [0, 24] (a pre-midnight start clips to 0)."""
        rows = await self._ch(
            "SELECT type, sleep_start_time, sleep_end_time FROM aihealth.sleep_data FINAL "
            "WHERE patient_id = %(pid)s AND type IN %(stages)s "
            "AND sleep_start_time < %(end)s AND sleep_end_time > %(start)s "
            "ORDER BY sleep_start_time",
            {
                "pid": patient_id,
                "stages": _SLEEP_STAGES,
                "start": day_start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": day_end.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        spans: list[StageSpan] = []
        for stage_type, start_ts, end_ts in rows:
            start_h = max(0.0, (start_ts - day_start).total_seconds() / 3600)
            end_h = min(24.0, (end_ts - day_start).total_seconds() / 3600)
            if end_h <= start_h:
                continue
            spans.append((round(start_h, 3), round(end_h, 3), stage_type.replace("sleep_", "")))
        return spans

    async def bp_readings(self, patient_id: str, day: date) -> list[VitalMarker]:
        """Blood pressure readings, systolic/diastolic paired by timestamp."""
        rows = await self._ch(
            "SELECT type, value, time FROM aihealth.vitals_data FINAL "
            "WHERE patient_id = %(pid)s AND type IN ('systolic_bp', 'diastolic_bp') "
            "AND toDate(time) = %(d)s ORDER BY time",
            {"pid": patient_id, "d": str(day)},
        )
        by_time: dict[datetime, dict[str, float]] = {}
        for vital_type, value, ts in rows:
            by_time.setdefault(ts, {})[vital_type] = float(value)
        out: list[VitalMarker] = []
        for ts, bp in by_time.items():
            h = hour_of(ts)
            if h is not None:
                out.append(VitalMarker(t=round(h, 3),
                                       systolic=bp.get("systolic_bp"),
                                       diastolic=bp.get("diastolic_bp")))
        return out

    # ── Postgres (ported from PatientTimelineService, typed output) ──────────

    async def moods(self, pid: UUID, day_start: datetime, day_end: datetime,
                    session: AsyncSession) -> list[MoodMarker]:
        # ported from PatientTimelineService._query_moods
        rows = (await session.execute(
            select(MoodEntry).where(
                MoodEntry.patient_id == pid,
                MoodEntry.recorded_at >= day_start,
                MoodEntry.recorded_at < day_end,
            ).order_by(MoodEntry.recorded_at)
        )).scalars().all()
        out: list[MoodMarker] = []
        for m in rows:
            h = hour_of(m.recorded_at)
            if h is not None:
                out.append(MoodMarker(t=round(h, 3), level=m.level, emoji=m.emoji))
        return out

    async def symptoms(self, pid: UUID, day_start: datetime, day_end: datetime,
                       session: AsyncSession) -> list[SymptomMarker]:
        # ported from PatientTimelineService._query_symptoms
        rows = (await session.execute(
            select(SymptomEntry).where(
                SymptomEntry.patient_id == pid,
                SymptomEntry.recorded_at >= day_start,
                SymptomEntry.recorded_at < day_end,
            ).options(selectinload(SymptomEntry.items)).order_by(SymptomEntry.recorded_at)
        )).scalars().all()
        out: list[SymptomMarker] = []
        for entry in rows:
            h = hour_of(entry.recorded_at)
            if h is None:
                continue
            items = entry.items or []
            names = [i.custom_label or i.symptom_name for i in items]
            severity = max((i.severity for i in items), default=None)
            out.append(SymptomMarker(t=round(h, 3),
                                     name=", ".join(names[:2]) if names else "Symptom",
                                     severity=severity))
        return out

    async def smbg_points(self, pid: UUID, day_start: datetime, day_end: datetime,
                          session: AsyncSession) -> list[Point]:
        # ported from PatientTimelineService._query_smbg (returns spine points, not events)
        rows = (await session.execute(
            select(PatientSMBG).where(
                PatientSMBG.patient_id == pid,
                PatientSMBG.reading_time >= day_start,
                PatientSMBG.reading_time < day_end,
            ).order_by(PatientSMBG.reading_time)
        )).scalars().all()
        out: list[Point] = []
        for r in rows:
            h = hour_of(r.reading_time)
            if h is not None:
                out.append((round(h, 3), float(r.glucose_level)))
        return out

    async def workouts(self, pid: UUID, day: date,
                       session: AsyncSession) -> list[WorkoutMarker]:
        # ported from PatientTimelineService._query_workouts (per-session, has a start time)
        rows = (await session.execute(
            select(PatientWorkout).where(
                PatientWorkout.patient_id == pid,
                PatientWorkout.date == day,
            ).options(selectinload(PatientWorkout.segments))
        )).scalars().all()
        out: list[WorkoutMarker] = []
        for w in rows:
            ts = datetime.combine(w.date, w.time or time(12, 0))
            h = hour_of(ts)
            if h is None:
                continue
            segments = w.segments or []
            total = sum(s.duration_minutes or 0 for s in segments) or (w.duration_minutes or 0)
            types = sorted({s.type for s in segments if s.type}) or ([w.type] if w.type else [])
            out.append(WorkoutMarker(
                t=round(h, 3),
                type=", ".join(types).title() if types else "Workout",
                minutes=int(total) or None,
                kcal=w.calories_burned,
            ))
        return out

    async def care(self, pid: UUID, day: date, session: AsyncSession):
        """Doses (medications = which are due, tasks = taken/missed) + task counts.

        A due dose with no task is "scheduled" rather than dropped.
        Returns (dose_markers, doses_taken, doses_total, tasks_done, tasks_total).
        """
        tasks = (await session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == pid,
                DailyTask.task_date == day,
            ).order_by(DailyTask.completed_at.nulls_last())
        )).scalars().all()

        tasks_total = len(tasks)
        tasks_done = sum(1 for t in tasks if t.status == "completed")

        task_items = [
            TaskItem(
                title=t.title,
                status=t.status,
                task_type=t.task_type,
                category=t.source_type,
                xp=t.xp_reward or 0,
                at=t.completed_at.strftime("%H:%M") if t.completed_at else None,
                target=t.target_value,
                current=t.current_value,
            )
            for t in tasks
        ]

        task_by_slot: dict[str, DailyTask] = {}
        for t in tasks:
            if t.source_type != SourceType.MEDICATION.value:  # stored lowercase
                continue
            slot = (t.task_type or "").replace("TAKE_MEDICATION_", "").lower()
            cur = task_by_slot.get(slot)
            if cur is None or (t.status == "completed" and cur.status != "completed"):
                task_by_slot[slot] = t

        meds = (await session.execute(
            select(PatientMedication).where(
                PatientMedication.patient_id == pid,
                PatientMedication.status == "active",
                PatientMedication.start_date <= day,
                or_(
                    PatientMedication.end_date.is_(None),
                    PatientMedication.end_date >= day,
                ),
            )
        )).scalars().all()

        slot_names: dict[str, list[str]] = {}
        for med in meds:
            if not TaskGeneratorService._is_medication_due(med, day):
                continue
            for dose in (med.doses or []):
                slot = (dose.get("slot") or "").lower()
                if slot:
                    slot_names.setdefault(slot, []).append(med.name)

        markers: list[DoseMarker] = []
        doses_taken = doses_total = 0
        for slot in ("morning", "afternoon", "evening", "night"):
            task = task_by_slot.get(slot)
            names = slot_names.get(slot)
            if not names and task is None:
                continue
            doses_total += 1

            src = names[0] if names else (task.description if task else "")
            label = (src or slot or "•").strip()[:1].upper()

            if task is not None and task.status == "completed" and task.completed_at is not None:
                status = "taken"
                doses_taken += 1
                h = hour_of(task.completed_at)
                at = task.completed_at.strftime("%H:%M")
            else:
                status = "missed" if task is not None else "scheduled"
                h = float(_SLOT_HOURS[slot.upper()])
                at = None
            if h is None:
                continue
            markers.append(DoseMarker(t=round(h, 3), slot=slot, label=label,
                                      status=status, taken=status == "taken", at=at))
        return markers, doses_taken, doses_total, tasks_done, tasks_total, task_items
