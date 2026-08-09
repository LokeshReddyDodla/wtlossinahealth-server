"""Day-view resolver — compose on read, no materialized doc.

One `asyncio.gather` over the four domain reports (Mongo `$lookup`, via the
existing report services), the raw ClickHouse series, and a Postgres bundle;
then select the spine by what data exists and assemble the typed `DayView`.

Spec: docs/day-timeline-resolver.md
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from lib.schemas.day_view import (
    CareRollup,
    DayView,
    Header,
    Lanes,
    OnCurve,
    SleepLane,
    SpineSource,
    VitalsRollup,
)
from lib.services.day_view import mappers
from lib.services.day_view.repository import DayViewRepository
from lib.services.gamification.time_utils import (
    get_patient_timezone,
    resolve_timezone_name,
)
from lib.services.reports.cgm.service import CGMReportService
from lib.services.reports.fitness.service import FitnessReportService
from lib.services.reports.meal.service import MealReportService
from lib.services.reports.sleep.service import SleepReportService
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)

# Drill-down domains that resolve to a Mongo daily report.
_REPORT_DOMAINS = frozenset({"glucose", "meal", "sleep", "fitness"})


class DayViewService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
        cgm_report_service: CGMReportService,
        meal_report_service: MealReportService,
        sleep_report_service: SleepReportService,
        fitness_report_service: FitnessReportService,
        insight_tracker: InsightTracker,
    ):
        self.postgres_store = postgres_store
        self.repo = DayViewRepository(clickhouse_store)
        self.cgm_report_service = cgm_report_service
        self.meal_report_service = meal_report_service
        self.sleep_report_service = sleep_report_service
        self.fitness_report_service = fitness_report_service
        self.insight_tracker = insight_tracker

    @with_postgres_session
    async def resolve(
        self, patient_id: str, day: date, *, postgres_session: AsyncSession
    ) -> DayView:
        tz_name = resolve_timezone_name(
            await get_patient_timezone(patient_id, postgres_session)
        )
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        # `day` is the patient-local calendar date; columns are local-naive, so we
        # bound directly (matches the feed service — see docs, tz item is parked).
        day_start = datetime.combine(day, time.min)
        day_end = datetime.combine(day + timedelta(days=1), time.min)
        # Insights are the exception — stored UTC-aware in Mongo, so the local day
        # must be converted to a real UTC window to select and place them.
        insight_from = day_start.replace(tzinfo=tz).astimezone(timezone.utc)
        insight_to = day_end.replace(tzinfo=tz).astimezone(timezone.utc)
        pid = UUID(patient_id)

        (
            cgm_rep, meal_rep, sleep_rep, fit_rep,
            hr, bp, pg, insight_docs,
        ) = await asyncio.gather(
            self._safe(self.cgm_report_service.fetch_daily_report, patient_id, day),
            self._safe(self.meal_report_service.fetch_daily_report, patient_id, day),
            self._safe(self.sleep_report_service.fetch_daily_report, patient_id, day),
            self._safe(self.fitness_report_service.fetch_daily_report, patient_id, day),
            self.repo.hr_series(patient_id, day),
            self.repo.bp_readings(patient_id, day),
            self._postgres_bundle(pid, day, day_start, day_end, postgres_session),
            self._fetch_insights(patient_id, insight_from, insight_to),
        )
        moods, symptoms, smbg, care = pg
        dose_markers, doses_taken, doses_total, tasks_done, tasks_total, task_items = care

        # Spine degrades to the highest-fidelity series present.
        spine = mappers.select_spine(cgm_rep, smbg, hr)

        sleep_roll, asleep_h, efficiency = mappers.sleep_rollup(sleep_rep)
        # Prefer the report's timed hypnogram; fall back to a raw sleep_data query
        # only for reports that predate the hypnogram field (transitional — heals
        # on the next sleep-report regeneration).
        sleep_stages = mappers.sleep_stages_from_report(sleep_rep, day_start)
        if not sleep_stages:
            sleep_stages = await self.repo.sleep_stage_spans(
                patient_id, day_start, day_end
            )
        hr_avg = round(sum(v for _, v in hr) / len(hr)) if hr else None
        bp_latest = None
        if bp and bp[-1].systolic is not None and bp[-1].diastolic is not None:
            bp_latest = f"{int(bp[-1].systolic)}/{int(bp[-1].diastolic)}"

        header = Header(
            glucose=mappers.glucose_rollup(cgm_rep),
            nutrition=mappers.nutrition_rollup(meal_rep),
            sleep=sleep_roll,
            activity=mappers.activity_rollup(fit_rep),
            vitals=VitalsRollup(bp_latest=bp_latest, hr_avg=hr_avg),
            care=CareRollup(doses_taken=doses_taken, doses_total=doses_total,
                            tasks_done=tasks_done, tasks_total=tasks_total),
        )
        on_curve = OnCurve(
            meals=mappers.meal_markers(meal_rep),
            symptoms=symptoms,
            workouts=mappers.workout_markers(fit_rep),
        )
        lanes = Lanes(
            steps=mappers.steps_lane(fit_rep),
            sleep=SleepLane(stages=sleep_stages, asleep_h=asleep_h, efficiency=efficiency),
            doses=dose_markers,
            mood=moods,
            vitals=bp,
            hr=mappers.hr_hourly(hr) if spine.source != SpineSource.hr else [],
        )
        return DayView(date=day, tz=tz_name, spine=spine,
                       on_curve=on_curve, lanes=lanes, header=header,
                       insights=mappers.insight_markers(insight_docs, tz), tasks=task_items)

    @with_postgres_session
    async def fetch_domain_report(
        self, patient_id: str, day: date, domain: str, *, postgres_session: AsyncSession
    ) -> dict | None:
        """Drill-down: the full pre-computed report for one domain, by (domain, date)."""
        if domain == "vitals":
            return await self.repo.vitals_detail(patient_id, day)
        service = {
            "glucose": self.cgm_report_service,
            "meal": self.meal_report_service,
            "sleep": self.sleep_report_service,
            "fitness": self.fitness_report_service,
        }.get(domain)
        if service is None:
            return None
        return await self._safe(service.fetch_daily_report, patient_id, day)

    # ── internals ────────────────────────────────────────────────────────────

    async def _postgres_bundle(
        self, pid: UUID, day: date, day_start: datetime, day_end: datetime,
        session: AsyncSession,
    ):
        # One AsyncSession can't run concurrent queries — sequential by design.
        # Workouts are not fetched here — they come from the fitness report.
        moods = await self.repo.moods(pid, day_start, day_end, session)
        symptoms = await self.repo.symptoms(pid, day_start, day_end, session)
        smbg = await self.repo.smbg_points(pid, day_start, day_end, session)
        care = await self.repo.care(pid, day, session)
        return moods, symptoms, smbg, care

    async def _fetch_insights(
        self, patient_id: str, from_utc: datetime, to_utc: datetime,
    ) -> list[dict]:
        # by_event_time places a retro-logged meal's insight on the day the meal
        # happened, not the day the scan ran. get_history already drops the
        # dedup-only records that carry no insight_id.
        try:
            return await self.insight_tracker.get_history(
                patient_id, limit=50, from_date=from_utc, to_date=to_utc,
                by_event_time=True,
            )
        except Exception:
            logger.exception("day-view insight fetch failed")
            return []

    @staticmethod
    async def _safe(fetch_fn, *args):
        try:
            return await fetch_fn(*args)
        except Exception:
            logger.exception("day-view report fetch failed")
            return None
