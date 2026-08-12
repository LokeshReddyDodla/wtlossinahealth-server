"""Progress resolver — compose on read, no materialized doc.

Mirrors the day-view resolver: one `asyncio.gather` over the sources (ClickHouse
vitals summary, stored daily CGM reports, Postgres engagement), then bucket each
daily series to the range's resolution and assemble the typed `ProgressView`.

Extending: add a `(category, label, unit, dir, target, extractor)` row to a
registry below — sleep/meal/fitness reports and the efficacy/care-intent blocks
slot in the same way, no resolver changes.
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from lib.schemas.progress import (
    Engagement,
    IntentAdherence,
    MetricSeries,
    Outcome,
    ProgressView,
    TrendPoint,
)
from lib.services.gamification.time_utils import (
    get_patient_timezone,
    resolve_timezone_name,
)
from lib.services.progress.bucketing import bucketize, months_ago, window_for
from lib.services.progress.repository import ProgressRepository
from lib.services.reports.cgm.service import CGMReportService
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)

# clickhouse vital type → (category, label, unit, improvement direction, target)
_VITALS: dict[str, tuple[str, str, str, str, float | None]] = {
    "weight": ("Labs & vitals", "Weight", "kg", "down", None),
    "a1c": ("Labs & vitals", "HbA1c", "%", "down", 7.0),
    "systolic_bp": ("Labs & vitals", "Systolic BP", "mmHg", "down", 130.0),
    "diastolic_bp": ("Labs & vitals", "Diastolic BP", "mmHg", "down", 80.0),
    "heart_rate": ("Labs & vitals", "Heart rate", "bpm", "down", None),
    "resting_heart_rate": ("Labs & vitals", "Resting HR", "bpm", "down", None),
    "spo2": ("Labs & vitals", "SpO₂", "%", "up", None),
    "blood_oxygen": ("Labs & vitals", "SpO₂", "%", "up", None),
    "creatinine": ("Labs & vitals", "Creatinine", "mg/dL", "flat", None),
    "ketones": ("Labs & vitals", "Ketones", "mmol/L", "down", None),
}


def _nested(path: list[str]):
    def get(report: dict):
        cur = report
        for k in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur
    return get


# key, label, unit, direction, target, extractor(report_dict)
_GLUCOSE = [
    ("tir", "Time in range", "%", "up", 70.0,
     _nested(["cgm_range_stats", "in_target_70_180_percent"])),
    ("gmi", "Est. A1c (GMI)", "%", "down", 7.0,
     _nested(["cgm_summary_stats", "gmi"])),
    ("avg_glucose", "Avg glucose", "mg/dL", "down", None,
     _nested(["cgm_summary_stats", "average_glucose_mgdl"])),
    ("cv", "Variability (CV)", "%", "down", 36.0,
     _nested(["cgm_summary_stats", "coefficient_of_variation_percent"])),
]


def _improved(direction: str, delta: float | None) -> bool | None:
    if delta is None:
        return None
    if direction == "up":
        return delta > 0
    if direction == "down":
        return delta < 0
    return abs(delta) < 0.1  # flat: stable is good


def _report_date(report: dict) -> date | None:
    raw = (((report or {}).get("metadata") or {}).get("date_range") or {}).get("start")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


class ProgressService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
        cgm_report_service: CGMReportService,
    ):
        self.postgres_store = postgres_store
        self.repo = ProgressRepository(clickhouse_store)
        self.cgm_report_service = cgm_report_service

    @with_postgres_session
    async def resolve(
        self, patient_id: str, range_key: str, *, postgres_session: AsyncSession
    ) -> ProgressView:
        months, resolution = window_for(range_key)
        tz_name = resolve_timezone_name(
            await get_patient_timezone(patient_id, postgres_session)
        )
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        end = datetime.now(tz).date()
        start = months_ago(end, months)
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end + timedelta(days=1), time.min)
        pid = UUID(patient_id)

        # Only the engagement coroutine touches the session (its two queries run
        # sequentially inside it); vitals and glucose use ClickHouse/Mongo, so the
        # three fan out concurrently.
        vitals_rows, glucose_reports, session_bundle = await asyncio.gather(
            self.repo.vitals_daily(patient_id, start_dt, end_dt),
            self._safe(
                self.cgm_report_service.fetch_daily_reports,
                patient_id, start_dt, end_dt,
            ),
            self._session_bundle(pid, start, end, postgres_session),
        )
        completion, (cur_streak, longest_streak), adherence = session_bundle

        metrics: list[MetricSeries] = []

        # ── vitals & labs ────────────────────────────────────────────────────
        vitals_points: dict[str, list[tuple[date, float]]] = {}
        for row in vitals_rows or []:
            vtype = row.get("type")
            if vtype not in _VITALS:
                continue
            try:
                d = date.fromisoformat(str(row["date"]))
            except (ValueError, KeyError):
                continue
            vitals_points.setdefault(vtype, []).append((d, row["avg"]))
        for vtype, (cat, label, unit, direction, target) in _VITALS.items():
            s = self._build(cat, vtype, label, unit, direction, target,
                            vitals_points.get(vtype, []), resolution)
            if s:
                metrics.append(s)

        # ── glucose (stored daily CGM reports) ───────────────────────────────
        glucose_points: dict[str, list[tuple[date, float]]] = {}
        for report in glucose_reports or []:
            d = _report_date(report)
            if d is None:
                continue
            for key, _l, _u, _dir, _t, extract in _GLUCOSE:
                val = extract(report)
                if val is not None:
                    glucose_points.setdefault(key, []).append((d, val))
        for key, label, unit, direction, target, _ex in _GLUCOSE:
            s = self._build("Glucose", key, label, unit, direction, target,
                            glucose_points.get(key, []), resolution)
            if s:
                metrics.append(s)

        engagement = Engagement(
            current_streak=cur_streak,
            longest_streak=longest_streak,
            completion_points=[TrendPoint(t=t, value=v)
                               for t, v in bucketize(completion, resolution)],
        )
        if engagement.completion_points:
            engagement.completion_pct = engagement.completion_points[-1].value

        return ProgressView(
            range=range_key, resolution=resolution, start=start, end=end,
            outcomes=self._outcomes(metrics, engagement),
            metrics=metrics, engagement=engagement,
            care_intents=[IntentAdherence(**a) for a in adherence],
        )

    # ── internals ────────────────────────────────────────────────────────────

    async def _session_bundle(self, pid, start, end, session):
        # One AsyncSession can't run concurrent queries — sequential by design.
        completion = await self.repo.task_completion_daily(pid, start, end, session)
        streak = await self.repo.streak(pid, session)
        adherence = await self.repo.care_intent_adherence(pid, start, end, session)
        return completion, streak, adherence

    @staticmethod
    def _build(category, key, label, unit, direction, target, daily_points, resolution):
        pts = bucketize(daily_points, resolution)
        if not pts:
            return None
        points = [TrendPoint(t=t, value=v) for t, v in pts]
        baseline, current = points[0].value, points[-1].value
        return MetricSeries(
            category=category, key=key, label=label, unit=unit, dir=direction,
            target=target, points=points, current=current, baseline=baseline,
            delta=round(current - baseline, 2),
        )

    @staticmethod
    def _outcomes(metrics: list[MetricSeries], engagement: Engagement) -> list[Outcome]:
        by_key = {m.key: m for m in metrics}
        out: list[Outcome] = []

        def add(key: str, label: str, unit: str, delta_unit: str):
            m = by_key.get(key)
            if not m or m.current is None:
                return
            delta_txt = None
            if m.delta is not None:
                sign = "+" if m.delta > 0 else ""
                delta_txt = f"{sign}{round(m.delta, 1):g}{delta_unit}"
            out.append(Outcome(key=key, label=label, value=f"{m.current:g}{unit}",
                               delta=delta_txt, good=_improved(m.dir, m.delta)))

        add("weight", "Weight", " kg", " kg")
        add("tir", "Time in range", "%", " pts")
        add("a1c", "HbA1c", "%", "")
        streak_delta = f"{engagement.completion_pct:g}% tasks" if engagement.completion_pct is not None else None
        out.append(Outcome(key="engagement", label="Engagement",
                           value=f"{engagement.current_streak}-day streak",
                           delta=streak_delta,
                           good=engagement.current_streak > 0))
        return out

    @staticmethod
    async def _safe(fetch_fn, *args):
        try:
            return await fetch_fn(*args)
        except Exception:
            logger.exception("progress report fetch failed")
            return []
