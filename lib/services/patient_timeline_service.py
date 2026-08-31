import asyncio
import logging
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from lib.models.gamification import DailyTask
from lib.models.mood_entry import MoodEntry
from lib.models.patient_meal import PatientMeal
from lib.models.patient_smbg import PatientSMBG
from lib.models.patient_workout import PatientWorkout
from lib.models.sleep_checkin import SleepCheckin
from lib.models.symptom_entry import SymptomEntry
from lib.schemas.patient_timeline import (
    DaySummary,
    TimelineEvent,
    TimelineEventType,
    TimelineResponse,
)
from lib.services.reports.cgm.service import CGMReportService
from lib.services.reports.fitness.service import FitnessReportService
from lib.services.reports.meal.service import MealReportService
from lib.services.reports.sleep.service import SleepReportService
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class PatientTimelineService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
        insight_tracker: InsightTracker,
        cgm_report_service: CGMReportService,
        meal_report_service: MealReportService,
        fitness_report_service: FitnessReportService,
        sleep_report_service: SleepReportService,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.insight_tracker = insight_tracker
        self.cgm_report_service = cgm_report_service
        self.meal_report_service = meal_report_service
        self.fitness_report_service = fitness_report_service
        self.sleep_report_service = sleep_report_service

    @with_postgres_session
    async def get_timeline(
        self,
        patient_id: str,
        selected_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> TimelineResponse:
        # Fetch each raw source once; events and the summary both derive from
        # the same fetches, so the strip can't disagree with the feed.
        (
            pg_events,
            vitals_rows,
            insight_events,
            cgm_report,
            meal_report,
            sleep_report,
            fitness_report,
        ) = await asyncio.gather(
            self._get_postgres_events(patient_id, selected_date, postgres_session),
            self._fetch_vitals_rows(patient_id, selected_date),
            self._get_insight_events(patient_id, selected_date),
            self._safe_fetch(self.cgm_report_service.fetch_daily_report, patient_id, selected_date),
            self._safe_fetch(self.meal_report_service.fetch_daily_report, patient_id, selected_date),
            self._safe_fetch(self.sleep_report_service.fetch_daily_report, patient_id, selected_date),
            self._safe_fetch(self.fitness_report_service.fetch_daily_report, patient_id, selected_date),
        )

        data_events = (
            pg_events
            + self._build_vital_events(vitals_rows)
            + self._build_cgm_events(cgm_report)
        )

        sleep_quality = self._extract_sleep_quality(sleep_report)
        self._enrich_meals(data_events, self._extract_meal_glucose(meal_report))
        self._enrich_sleep(data_events, sleep_quality)
        data_events.extend(self._extract_inactive_periods(fitness_report, selected_date))

        summary = self._build_summary(vitals_rows, fitness_report, cgm_report)

        # Sleep on the strip uses the checkin's self-rating, matching the feed —
        # not the device classification, which can disagree with it.
        sleep_evt = next(
            (e for e in data_events if e.type == TimelineEventType.SLEEP), None
        )
        if sleep_evt:
            hrs = sleep_evt.data.get("hours_slept")
            rated = sleep_evt.data.get("quality")
            if isinstance(hrs, (int, float)) and hrs > 0:
                summary.sleep_hours = round(hrs, 1)
            if rated:
                summary.sleep_quality = f"Quality {rated}/5"
            elif sleep_quality.get("classification"):
                summary.sleep_quality = sleep_quality["classification"].title()

        self._anchor_insights(insight_events, data_events)
        events = data_events + insight_events
        events.sort(key=lambda e: e.timestamp)
        return TimelineResponse(
            date=selected_date,
            patient_id=patient_id,
            event_count=len(events),
            events=events,
            summary=summary,
        )

    # ── Report enrichments (MongoDB) ─────────────────────────────────────

    @staticmethod
    async def _safe_fetch(fetch_fn, *args):
        try:
            return await fetch_fn(*args)
        except Exception:
            return None

    @staticmethod
    def _extract_meal_glucose(meal_report: dict | None) -> dict:
        if not meal_report or "meals" not in meal_report:
            return {}
        glucose_by_time: dict[str, dict] = {}
        for meal in meal_report["meals"]:
            meal_time = meal.get("time", "")
            before = meal.get("glucose_before_meal") or []
            after = meal.get("glucose_after_meal") or []
            if before or after:
                glucose_by_time[meal_time] = {
                    "glucose_before": [
                        {"timestamp": str(r[0]), "value": r[1]} for r in before
                    ] if before else [],
                    "glucose_after": [
                        {"timestamp": str(r[0]), "value": r[1]} for r in after
                    ] if after else [],
                }
        return glucose_by_time

    @staticmethod
    def _extract_sleep_quality(sleep_report: dict | None) -> dict:
        if not sleep_report:
            return {}
        quality = {}
        quality_data = sleep_report.get("quality_analysis") or sleep_report.get("quality") or {}
        if isinstance(quality_data, dict):
            if "sleep_quality" in quality_data:
                quality["classification"] = quality_data["sleep_quality"]
            if "sleep_efficiency" in quality_data:
                quality["efficiency"] = quality_data["sleep_efficiency"]
            if "restorative_sleep" in quality_data:
                quality["restorative_pct"] = quality_data["restorative_sleep"]
        duration_data = sleep_report.get("duration_analysis") or sleep_report.get("duration") or {}
        if isinstance(duration_data, dict) and "total_duration" in duration_data:
            quality["total_duration_minutes"] = duration_data["total_duration"]
        return quality

    @staticmethod
    def _extract_inactive_periods(
        fitness_report: dict | None, selected_date: date,
    ) -> list[TimelineEvent]:
        if not fitness_report:
            return []
        periods = fitness_report.get("inactive_periods") or []
        events: list[TimelineEvent] = []
        for period in periods:
            start_str = period.get("start_time")
            duration = period.get("inactive_duration", 0)
            if not start_str or duration < 90:
                continue
            try:
                ts = datetime.fromisoformat(start_str)
            except (ValueError, TypeError):
                continue
            hours = duration // 60
            mins = duration % 60
            dur_label = f"{hours}h {mins}m" if hours else f"{mins} min"
            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.INACTIVE_PERIOD,
                title=f"Inactive: {dur_label}",
                subtitle=None,
                data={"duration_minutes": duration},
            ))
        return events

    @staticmethod
    def _enrich_meals(events: list[TimelineEvent], meal_glucose: dict) -> None:
        if not meal_glucose:
            return
        for event in events:
            if event.type != TimelineEventType.MEAL:
                continue
            meal_time = event.timestamp.time().strftime("%H:%M:%S")
            # Try matching with and without seconds
            glucose = meal_glucose.get(meal_time) or meal_glucose.get(meal_time[:5])
            if glucose:
                event.data["glucose_before"] = glucose.get("glucose_before", [])
                event.data["glucose_after"] = glucose.get("glucose_after", [])

    @staticmethod
    def _enrich_sleep(events: list[TimelineEvent], sleep_quality: dict) -> None:
        # Stash the device analysis on the event (for the detail screen) but
        # DON'T touch the subtitle — the device label and the user's self-rating
        # can disagree, and showing both reads as a contradiction.
        if not sleep_quality:
            return
        for event in events:
            if event.type == TimelineEventType.SLEEP:
                event.data.update(sleep_quality)

    # ── CGM events from daily report (MongoDB) ───────────────────────────

    def _build_cgm_events(self, report: dict | None) -> list[TimelineEvent]:
        if not report:
            return []

        events: list[TimelineEvent] = []

        hyper_stats = report.get("hyper_stats") or {}
        for evt in hyper_stats.get("hyper_events") or []:
            ts = self._parse_ts(evt.get("start_time"))
            if not ts:
                continue
            peak = evt.get("peak_glucose_mgdl", 0)
            duration = evt.get("duration_minutes", 0)
            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.CGM_EVENT,
                title=f"High glucose: {int(peak)} mg/dL",
                subtitle=f"Above 180 for {int(duration)} min",
                data={
                    "cgm_event_type": "hyper",
                    "peak_glucose": peak,
                    "duration_minutes": duration,
                    "start_time": str(evt.get("start_time")),
                    "end_time": str(evt.get("end_time")),
                },
            ))

        for evt in (hyper_stats.get("rapid_spike_stats") or {}).get("spike_events") or []:
            ts = self._parse_ts(evt.get("start_time"))
            if not ts:
                continue
            initial = evt.get("initial_glucose_mgdl", 0)
            peak = evt.get("peak_glucose_mgdl", 0)
            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.CGM_EVENT,
                title=f"Rapid spike: {int(initial)} → {int(peak)} mg/dL",
                subtitle=f"In {int(evt.get('duration_minutes', 0))} min",
                data={
                    "cgm_event_type": "rapid_spike",
                    "initial_glucose": initial,
                    "peak_glucose": peak,
                    "peak_time": str(evt.get("peak_glucose_time")),
                    "duration_minutes": evt.get("duration_minutes", 0),
                },
            ))

        hypo_stats = report.get("hypo_stats") or {}
        for evt in hypo_stats.get("hypo_events") or []:
            ts = self._parse_ts(evt.get("start_time"))
            if not ts:
                continue
            lowest = evt.get("lowest_glucose_mgdl", 0)
            duration = evt.get("duration_minutes", 0)
            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.CGM_EVENT,
                title=f"Low glucose: {int(lowest)} mg/dL",
                subtitle=f"Below 70 for {int(duration)} min",
                data={
                    "cgm_event_type": "hypo",
                    "lowest_glucose": lowest,
                    "duration_minutes": duration,
                    "start_time": str(evt.get("start_time")),
                    "end_time": str(evt.get("end_time")),
                },
            ))

        for evt in (hypo_stats.get("rapid_drop_stats") or {}).get("drop_events") or []:
            ts = self._parse_ts(evt.get("start_time"))
            if not ts:
                continue
            initial = evt.get("initial_glucose_mgdl", 0)
            lowest = evt.get("lowest_glucose_mgdl", 0)
            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.CGM_EVENT,
                title=f"Rapid drop: {int(initial)} → {int(lowest)} mg/dL",
                subtitle=f"In {int(evt.get('duration_minutes', 0))} min",
                data={
                    "cgm_event_type": "rapid_drop",
                    "initial_glucose": initial,
                    "lowest_glucose": lowest,
                    "lowest_time": str(evt.get("lowest_glucose_time")),
                    "duration_minutes": evt.get("duration_minutes", 0),
                },
            ))

        return events

    # ── Postgres (sequential on single session) ─────────────────────────

    async def _get_postgres_events(
        self,
        patient_id: str,
        selected_date: date,
        session: AsyncSession,
    ) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []
        pid = UUID(patient_id)
        day_start = datetime.combine(selected_date, time.min)
        day_end = datetime.combine(selected_date + timedelta(days=1), time.min)

        events.extend(await self._query_meals(pid, selected_date, session))
        events.extend(await self._query_moods(pid, day_start, day_end, session))
        events.extend(await self._query_sleep(pid, selected_date, session))
        events.extend(await self._query_symptoms(pid, day_start, day_end, session))
        events.extend(await self._query_smbg(pid, day_start, day_end, session))
        events.extend(await self._query_workouts(pid, selected_date, session))
        events.extend(await self._query_medications(pid, selected_date, session))
        return events

    async def _query_meals(
        self, pid: UUID, selected_date: date, session: AsyncSession,
    ) -> list[TimelineEvent]:
        rows = (
            await session.execute(
                select(PatientMeal)
                .where(PatientMeal.patient_id == pid, PatientMeal.date == selected_date)
                .options(selectinload(PatientMeal.total_macro_nutritional_value))
                .order_by(PatientMeal.time)
            )
        ).scalars().all()

        events: list[TimelineEvent] = []
        for meal in rows:
            ts = datetime.combine(meal.date, meal.time)
            data: dict = {"meal_type": meal.type}
            if meal.image_urls:
                data["image_url"] = meal.image_urls[0]
            if meal.score is not None:
                data["score"] = meal.score

            macros = meal.total_macro_nutritional_value
            if macros:
                data["calories"] = macros.calories

            title = (meal.type or "Meal").replace("_", " ").title()
            subtitle = meal.description[:100] if meal.description else None

            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.MEAL,
                title=title,
                subtitle=subtitle,
                data=data,
                entity_id=str(meal.id),
            ))
        return events

    async def _query_moods(
        self, pid: UUID, day_start: datetime, day_end: datetime, session: AsyncSession,
    ) -> list[TimelineEvent]:
        rows = (
            await session.execute(
                select(MoodEntry)
                .where(
                    MoodEntry.patient_id == pid,
                    MoodEntry.recorded_at >= day_start,
                    MoodEntry.recorded_at < day_end,
                )
                .order_by(MoodEntry.recorded_at)
            )
        ).scalars().all()

        MOOD_LABELS = {1: "Very Bad", 2: "Bad", 3: "Neutral", 4: "Good", 5: "Great"}
        events: list[TimelineEvent] = []
        for mood in rows:
            label = MOOD_LABELS.get(mood.level, f"Level {mood.level}")
            data: dict = {"level": mood.level, "emoji": mood.emoji}
            if mood.tags:
                data["tags"] = mood.tags

            events.append(TimelineEvent(
                timestamp=mood.recorded_at,
                type=TimelineEventType.MOOD,
                title=f"Mood: {label}",
                subtitle=", ".join(mood.tags) if mood.tags else None,
                data=data,
                entity_id=str(mood.id),
            ))
        return events

    async def _query_sleep(
        self, pid: UUID, selected_date: date, session: AsyncSession,
    ) -> list[TimelineEvent]:
        row = (
            await session.execute(
                select(SleepCheckin)
                .where(
                    SleepCheckin.patient_id == pid,
                    SleepCheckin.checkin_date == selected_date,
                )
            )
        ).scalars().first()

        if not row:
            return []

        data: dict = {
            "quality": row.quality,
            "hours_slept": row.hours_slept,
        }
        if row.bed_time:
            data["bed_time"] = row.bed_time
        if row.wake_time:
            data["wake_time"] = row.wake_time

        # Hours only; quality renders as its own chip from data["quality"].
        subtitle_parts = [f"{row.hours_slept:.1f} hrs"] if row.hours_slept else []

        ts = datetime.combine(selected_date, time.min)
        if row.wake_time:
            try:
                h, m = map(int, row.wake_time.split(":"))
                ts = datetime.combine(selected_date, time(h, m))
            except (ValueError, AttributeError):
                pass

        return [TimelineEvent(
            timestamp=ts,
            type=TimelineEventType.SLEEP,
            title="Sleep",
            subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
            data=data,
            entity_id=str(row.id),
        )]

    async def _query_symptoms(
        self, pid: UUID, day_start: datetime, day_end: datetime, session: AsyncSession,
    ) -> list[TimelineEvent]:
        rows = (
            await session.execute(
                select(SymptomEntry)
                .where(
                    SymptomEntry.patient_id == pid,
                    SymptomEntry.recorded_at >= day_start,
                    SymptomEntry.recorded_at < day_end,
                )
                .options(selectinload(SymptomEntry.items))
                .order_by(SymptomEntry.recorded_at)
            )
        ).scalars().all()

        events: list[TimelineEvent] = []
        for entry in rows:
            items = entry.items or []
            names = [i.custom_label or i.symptom_name for i in items]
            max_severity = max((i.severity for i in items), default=0)

            data: dict = {
                "symptoms": [
                    {"name": i.custom_label or i.symptom_name, "severity": i.severity}
                    for i in items
                ],
            }

            events.append(TimelineEvent(
                timestamp=entry.recorded_at,
                type=TimelineEventType.SYMPTOM,
                title=", ".join(names[:3]) if names else "Symptoms",
                subtitle=f"Severity {max_severity}/5" if max_severity else None,
                data=data,
                entity_id=str(entry.id),
            ))
        return events

    async def _query_smbg(
        self, pid: UUID, day_start: datetime, day_end: datetime, session: AsyncSession,
    ) -> list[TimelineEvent]:
        rows = (
            await session.execute(
                select(PatientSMBG)
                .where(
                    PatientSMBG.patient_id == pid,
                    PatientSMBG.reading_time >= day_start,
                    PatientSMBG.reading_time < day_end,
                )
                .order_by(PatientSMBG.reading_time)
            )
        ).scalars().all()

        events: list[TimelineEvent] = []
        for reading in rows:
            reading_type = (reading.type or "").replace("_", " ").title()
            data: dict = {
                "glucose_level": reading.glucose_level,
                "unit": "mg/dL",
            }
            if reading.type:
                data["reading_type"] = reading.type

            events.append(TimelineEvent(
                timestamp=reading.reading_time,
                type=TimelineEventType.SMBG,
                title=f"Glucose: {int(reading.glucose_level)} mg/dL",
                subtitle=reading_type if reading_type else None,
                data=data,
                entity_id=str(reading.id),
            ))
        return events

    async def _query_workouts(
        self, pid: UUID, selected_date: date, session: AsyncSession,
    ) -> list[TimelineEvent]:
        rows = (
            await session.execute(
                select(PatientWorkout)
                .where(
                    PatientWorkout.patient_id == pid,
                    PatientWorkout.date == selected_date,
                )
                .options(selectinload(PatientWorkout.segments))
            )
        ).scalars().all()

        events: list[TimelineEvent] = []
        for workout in rows:
            ts = datetime.combine(workout.date, workout.time or time(12, 0))

            segments = workout.segments or []
            types: set[str] = set()
            total_duration = 0
            for seg in segments:
                total_duration += seg.duration_minutes or 0
                if seg.type:
                    types.add(seg.type)

            if not total_duration:
                total_duration = workout.duration_minutes or 0
            if not types and workout.type:
                types.add(workout.type)

            data: dict = {
                "duration_minutes": total_duration,
                "types": sorted(types),
            }
            if workout.calories_burned:
                data["calories_burned"] = workout.calories_burned

            subtitle_parts: list[str] = []
            if total_duration:
                subtitle_parts.append(f"{total_duration} min")
            if workout.calories_burned:
                subtitle_parts.append(f"{int(workout.calories_burned)} cal")

            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.WORKOUT,
                title=", ".join(sorted(types)).title() if types else "Workout",
                subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
                data=data,
                entity_id=str(workout.id),
            ))
        return events

    async def _query_medications(
        self, pid: UUID, selected_date: date, session: AsyncSession,
    ) -> list[TimelineEvent]:
        rows = (
            await session.execute(
                select(DailyTask)
                .where(
                    DailyTask.patient_id == pid,
                    DailyTask.task_date == selected_date,
                    DailyTask.source_type == "MEDICATION",
                )
                .order_by(DailyTask.completed_at.nulls_last())
            )
        ).scalars().all()

        SLOT_HOURS = {"MORNING": 9, "AFTERNOON": 14, "EVENING": 20, "NIGHT": 22}
        events: list[TimelineEvent] = []
        for task in rows:
            is_taken = task.status == "completed" and task.completed_at is not None

            if is_taken:
                ts = task.completed_at
                event_type = TimelineEventType.MEDICATION_TAKEN
                title = f"Took {task.title or 'medication'}"
            else:
                slot = (task.task_type or "").replace("TAKE_MEDICATION_", "").upper()
                hour = SLOT_HOURS.get(slot, 12)
                ts = datetime.combine(selected_date, time(hour, 0))
                event_type = TimelineEventType.MEDICATION_MISSED
                title = f"Missed {task.title or 'medication'}"

            data: dict = {
                "task_type": task.task_type,
                "status": task.status,
            }
            if task.description:
                data["description"] = task.description

            events.append(TimelineEvent(
                timestamp=ts,
                type=event_type,
                title=title,
                subtitle=task.description,
                data=data,
                entity_id=str(task.task_id),
            ))
        return events

    # ── ClickHouse (vitals) ──────────────────────────────────────────────

    async def _fetch_vitals_rows(
        self, patient_id: str, selected_date: date,
    ) -> list[tuple]:
        """All of the day's vitals rows, fetched once. Feeds both the vital
        events and the HR/SpO2 summary — no second query for the aggregates."""
        query = f"""
        SELECT type, value, time
        FROM aihealth.vitals_data FINAL
        WHERE patient_id = '{patient_id}'
            AND toDate(time) = '{selected_date}'
        ORDER BY time
        """
        try:
            return self.clickhouse_store.client.execute(query)
        except Exception:
            return []

    def _build_vital_events(self, rows: list[tuple]) -> list[TimelineEvent]:
        # Keys are the `type` strings fitness_upload_service writes
        # (blood_oxygen / body_temperature, not spo2 / temperature) — mismatch
        # here silently drops the unit.
        VITAL_LABELS = {
            "systolic_bp": ("Systolic BP", "mmHg"),
            "diastolic_bp": ("Diastolic BP", "mmHg"),
            "blood_oxygen": ("SpO2", "%"),
            "body_temperature": ("Temperature", "°F"),
            "respiratory_rate": ("Respiratory Rate", "breaths/min"),
            "weight": ("Weight", "kg"),
        }

        bp_by_time: dict[datetime, dict[str, float]] = {}
        events: list[TimelineEvent] = []

        for vital_type, value, ts in rows:
            # HR is a continuous stream (~300 samples/day) — it goes to the
            # summary, not one feed event per reading.
            if vital_type in ("heart_rate", "resting_heart_rate"):
                continue

            if vital_type in ("systolic_bp", "diastolic_bp"):
                bp_by_time.setdefault(ts, {})[vital_type] = value
                continue

            label, unit = VITAL_LABELS.get(vital_type, (vital_type.replace("_", " ").title(), ""))
            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.VITAL,
                title=f"{label}: {value:.0f} {unit}".strip(),
                data={"vital_type": vital_type, "value": value, "unit": unit},
            ))

        for ts, bp in bp_by_time.items():
            sys_val = bp.get("systolic_bp")
            dia_val = bp.get("diastolic_bp")
            if sys_val is not None and dia_val is not None:
                title = f"Blood Pressure: {sys_val:.0f}/{dia_val:.0f} mmHg"
            elif sys_val is not None:
                title = f"Systolic BP: {sys_val:.0f} mmHg"
            else:
                title = f"Diastolic BP: {dia_val:.0f} mmHg"

            events.append(TimelineEvent(
                timestamp=ts,
                type=TimelineEventType.VITAL,
                title=title,
                data={"vital_type": "blood_pressure", **bp},
            ))

        return events

    # ── Ambient day summary (the dashboard strip) ────────────────────────

    def _build_summary(
        self,
        vitals_rows: list[tuple],
        fitness_report: dict | None,
        cgm_report: dict | None,
    ) -> DaySummary:
        """Derive the strip from sources already fetched — no query of its own.

        Steps/active come from the fitness report, NOT a raw fitness_data sum:
        the raw sum double-counts overlapping syncs and disagrees with Home.
        Sleep is set by the caller from the checkin (self-rating).
        """
        summary = DaySummary()

        if fitness_report:
            steps = fitness_report.get("steps")
            active = fitness_report.get("active_energy")
            if isinstance(steps, (int, float)) and steps > 0:
                summary.steps = int(steps)
            if isinstance(active, (int, float)) and active > 0:
                summary.active_energy_kcal = round(float(active), 1)

        hr_vals: list[float] = []
        spo2_vals: list[float] = []
        for vital_type, value, _ts in vitals_rows:
            if vital_type == "heart_rate":
                hr_vals.append(value)
            elif vital_type == "resting_heart_rate":
                summary.resting_hr = round(value)  # rows are time-ordered; last wins
            elif vital_type == "blood_oxygen":
                spo2_vals.append(value)
        if hr_vals:
            summary.avg_hr = round(sum(hr_vals) / len(hr_vals))
            summary.min_hr = round(min(hr_vals))
            summary.max_hr = round(max(hr_vals))
        if spo2_vals:
            summary.avg_spo2 = round(sum(spo2_vals) / len(spo2_vals), 1)

        if cgm_report:
            avg = (cgm_report.get("cgm_summary_stats") or {}).get("average_glucose_mgdl")
            tir = (cgm_report.get("cgm_range_stats") or {}).get("in_target_70_180_percent")
            if isinstance(avg, (int, float)) and avg > 0:
                summary.avg_glucose = round(avg)
            if isinstance(tir, (int, float)):
                summary.time_in_range = round(tir, 1)

        return summary

    # ── MongoDB (proactive insights) ─────────────────────────────────────

    async def _get_insight_events(
        self, patient_id: str, selected_date: date,
    ) -> list[TimelineEvent]:
        from_dt = datetime.combine(selected_date, time.min)
        to_dt = datetime.combine(selected_date + timedelta(days=1), time.min)

        try:
            # by_event_time: a retro-logged meal's insight belongs on the day
            # the meal happened, not the day the scan ran.
            docs = await self.insight_tracker.get_history(
                patient_id,
                limit=50,
                from_date=from_dt,
                to_date=to_dt,
                by_event_time=True,
            )
        except Exception:
            return []

        events: list[TimelineEvent] = []
        for doc in docs:
            if doc.get("category") == "engagement_drop":
                continue
            # Place at the source event's time when known; created_at is the
            # fallback for cron insights (no single source event).
            placed = self._parse_ts(doc.get("event_time")) or self._parse_ts(doc.get("created_at"))
            if not placed:
                continue

            data: dict = {
                "category": doc.get("category"),
                "severity": doc.get("severity"),
            }
            if doc.get("suggested_query"):
                data["suggested_query"] = doc["suggested_query"]
            if doc.get("trigger"):
                data["trigger"] = doc["trigger"]
            # Source entity link — lets anchoring snap to the exact event
            # instead of guessing by time proximity.
            if doc.get("entity_id"):
                data["source_entity_id"] = str(doc["entity_id"])

            events.append(TimelineEvent(
                timestamp=placed,
                type=TimelineEventType.AI_INSIGHT,
                title=doc.get("title") or doc.get("category", "Insight"),
                subtitle=doc.get("message") or None,
                data=data,
                entity_id=doc.get("insight_id"),
            ))
        return events

    # ── Insight anchoring ─────────────────────────────────────────────────

    _TRIGGER_TO_EVENT_TYPE = {
        "meal_logged": TimelineEventType.MEAL,
        "smbg_logged": TimelineEventType.SMBG,
        "symptom_logged": TimelineEventType.SYMPTOM,
        "medication_missed": TimelineEventType.MEDICATION_MISSED,
    }

    @staticmethod
    def _anchor_insights(
        insights: list[TimelineEvent], data_events: list[TimelineEvent],
    ) -> None:
        """Snap event-triggered insights directly under their source event.

        Exact entity_id match first (the insight record stores which meal/
        reading/symptom fired it); time proximity only as a fallback for
        older records without the link. Proximity alone anchors to the
        wrong sibling when two events of the same type share a day.
        """
        for insight in insights:
            trigger = insight.data.get("trigger")
            target_type = PatientTimelineService._TRIGGER_TO_EVENT_TYPE.get(trigger)
            if not target_type:
                continue

            source_id = insight.data.get("source_entity_id")
            if source_id:
                exact = next(
                    (e for e in data_events
                     if e.type == target_type and str(e.entity_id) == source_id),
                    None,
                )
                if exact:
                    insight.timestamp = exact.timestamp + timedelta(seconds=1)
                    continue

            candidates = [e for e in data_events if e.type == target_type]
            if not candidates:
                continue
            closest = min(
                candidates,
                key=lambda e: abs((e.timestamp - insight.timestamp).total_seconds()),
            )
            insight.timestamp = closest.timestamp + timedelta(seconds=1)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_ts(value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
