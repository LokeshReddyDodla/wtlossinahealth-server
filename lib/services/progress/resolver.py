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
    Composition,
    CompositionSegment,
    Engagement,
    IntentAdherence,
    MetricSeries,
    Outcome,
    ProgressView,
    TrendPoint,
)
from lib.services.day_view.mappers import select_glucose_targets
from lib.services.gamification.time_utils import (
    get_patient_timezone,
    resolve_timezone_name,
)
from lib.services.progress.bucketing import bucketize, months_ago, window_for
from lib.services.progress.repository import ProgressRepository
from lib.services.reports.cgm.service import CGMReportService
from lib.services.reports.fitness.service import FitnessReportService
from lib.services.reports.meal.service import MealReportService
from lib.services.reports.sleep.service import SleepReportService
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)

# clickhouse vital type → (category, label, unit, improvement direction, target)
_VITALS: dict[str, tuple[str, str, str, str, float | None]] = {
    "weight": ("Labs & vitals", "Weight", "kg", "down", None),
    "a1c": ("Labs & vitals", "HbA1c", "%", "down", 7.0),
    "systolic_bp": ("Labs & vitals", "Systolic BP", "mmHg", "down", 130.0),
    "diastolic_bp": ("Labs & vitals", "Diastolic BP", "mmHg", "down", 80.0),
    # Average daily HR has no clear improving direction; resting HR carries that.
    "heart_rate": ("Labs & vitals", "Heart rate", "bpm", "flat", None),
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


def _flat(key: str):
    return lambda r: r.get(key) if isinstance(r, dict) else None


def _minutes_to_hours(get):
    def wrapped(r):
        v = get(r)
        return round(v / 60, 2) if v is not None else None
    return wrapped


def _workout_count(r):
    # session_count can exceed 1 (type-aggregated rows), so sum, don't count.
    return sum((w.get("session_count") or 1) for w in (r.get("workouts") or []))


def _range_sum(*keys: str):
    """Sum CGM range-coverage percentages (below-range = <54 + 54–70, etc.)."""
    def get(report: dict):
        stats = (report or {}).get("cgm_range_stats") or {}
        vals = [stats.get(k) for k in keys]
        vals = [float(v) for v in vals if v is not None]
        return round(sum(vals), 1) if vals else None
    return get


def _meal_type_cal(meal_type: str):
    """Sum a day's logged calories for one meal slot (breakfast/lunch/…)."""
    def get(report: dict):
        total, seen = 0.0, False
        for m in (report or {}).get("meals") or []:
            if str(m.get("type") or "").strip().lower().rstrip("s") != meal_type:
                continue
            cal = (m.get("total_macro_nutritional_value") or {}).get("calories")
            if cal is not None:
                total, seen = total + float(cal), True
        return round(total, 1) if seen else None
    return get


# HbA1c / GMI target by glucose-tier (2019 consensus / ADA): standard <7%,
# older/high-risk relaxes to <8%, pregnancy tightens to <6%.
_A1C_TARGET_BY_TIER = {"standard": 7.0, "older_high_risk": 8.0, "pregnancy": 6.0}


def _glucose_defs(targets, a1c_target):
    """Per-patient glucose metrics — pregnancy reads the 63–140 in-range field and
    tighter A1c; older/high-risk relaxes the TIR floor and A1c. key, label, unit,
    direction, target, extractor(report_dict)."""
    preg = targets.in_range == (63.0, 140.0)
    tir_field = "in_target_63_140_percent" if preg else "in_target_70_180_percent"
    tir_label = "Time in range (63–140)" if preg else "Time in range"
    return [
        ("tir", tir_label, "%", "up", targets.tir_min,
         _nested(["cgm_range_stats", tir_field])),
        ("gmi", "Est. A1c (GMI)", "%", "down", a1c_target,
         _nested(["cgm_summary_stats", "gmi"])),
        ("avg_glucose", "Avg glucose", "mg/dL", "down", None,
         _nested(["cgm_summary_stats", "average_glucose_mgdl"])),
        ("cv", "Variability (CV)", "%", "down", 36.0,
         _nested(["cgm_summary_stats", "coefficient_of_variation_percent"])),
    ]

_SLEEP = [
    ("sleep_duration", "Sleep duration", "h", "up", 7.0,
     _minutes_to_hours(_nested(["duration", "per_day_average_duration"]))),
    ("sleep_efficiency", "Efficiency", "%", "up", 85.0,
     _nested(["quality", "sleep_efficiency"])),
    ("awakenings", "Awakenings /night", "", "down", None,
     _nested(["quality", "average_awakenings"])),
    ("sleep_debt", "Sleep debt", "min", "down", None,
     _nested(["consistency", "sleep_debt_minutes"])),
]


def _sleep_light(r: dict):
    """Light-sleep share = the remainder once deep and REM are removed."""
    deep = _nested(["quality", "deep_sleep_percentage"])(r)
    rem = _nested(["quality", "rem_sleep_percentage"])(r)
    if deep is None and rem is None:
        return None
    return round(max(0.0, 100 - (deep or 0) - (rem or 0)), 1)

# Diabetes types where reducing dietary carbs is a care goal.
_CARB_REDUCE_DX = {"T2", "PRE", "GESTATIONAL", "LADA", "MODY"}


def _meal_defs(bmi, diabetes_type):
    """Per-patient intake metrics. Fewer calories is only "better" with a
    weight-reduction indication (overweight or a glycemic condition); for an
    underweight patient more is better, otherwise intake trends neutral. Fiber
    and protein are goods regardless. key, label, unit, dir, target, extractor."""
    carb_sensitive = (diabetes_type or "").upper() in _CARB_REDUCE_DX
    overweight = bmi is not None and bmi >= 25
    underweight = bmi is not None and bmi < 18.5
    cal_dir = "up" if underweight else ("down" if (overweight or carb_sensitive) else "flat")
    carb_dir = "down" if (carb_sensitive and not underweight) else "flat"
    return [
        ("calories", "Calories", "kcal", cal_dir, None, _flat("calories")),
        ("carbs", "Carbs", "g", carb_dir, None, _flat("carbohydrates")),
        ("fiber", "Fiber", "g", "up", 25.0, _flat("fiber")),
        ("protein", "Protein", "g", "up", None, _flat("proteins")),
        ("fat", "Fat", "g", "flat", None, _flat("fats")),
    ]

_FITNESS = [
    ("steps", "Steps /day", "", "up", 8000.0, _flat("steps")),
    ("active_energy", "Active energy", "kcal", "up", None, _flat("active_energy")),
    # exercise_time is the Apple exercise-ring minute count; active_duration sums
    # raw session spans and over-counts, so it's not the "active minutes" a provider means.
    ("active_minutes", "Active minutes", "min", "up", 30.0, _flat("exercise_time")),
    ("workouts", "Workouts /period", "", "up", None, _workout_count),
]


# Categories where a value is expected most days, so a low share of days-with-
# data means the trend reflects logging cadence more than the metric. Labs &
# vitals are point-in-time (a lab isn't taken daily), so they're never gated —
# their caveat is recency (latest) and reading count, not density.
_DENSITY_CATEGORIES = {"Glucose", "Sleep", "Nutrition", "Activity", "SMBG", "Engagement"}
_MIN_COVERAGE = 0.4  # heuristic: below this share of period days, withhold delta
# CGM metrics follow the 2019 consensus: a TIR/GMI trend is reliable only with
# ~70% sensor wear across the window.
_CGM_MIN_COVERAGE = 0.7

# A CGM day worn below this floor reads 0/100% on a few readings, not a real day.
# total_readings is the fallback when sensor_active_percent is absent.
_MIN_CGM_ACTIVE_PCT = 30.0
_MIN_CGM_READINGS = 24
# A daily mean glucose below this is not a real day but a sensor artifact
# (e.g. zero-value readings); a genuine all-high day has a plausible mean and stays.
_MIN_PLAUSIBLE_GLUCOSE = 54.0

# Raw daily scatter ships only for short ranges; longer ranges bucket to bound payload.
_DAILY_MAX_PERIOD_DAYS = 100

# Finger-stick reading tags (PatientSMBG.type) → provider-facing label. Order
# leads with fasting, the most day-to-day-comparable line.
_SMBG_TAGS = [
    ("fasting", "Fasting (SMBG)"),
    ("before_meal", "Before meal (SMBG)"),
    ("after_meal", "After meal (SMBG)"),
    ("random", "Random (SMBG)"),
]

# One-line methodology caveat per metric key — what the number means and where
# it can mislead, in the provider's own explaining-to-the-patient voice.
_NOTES: dict[str, str] = {
    "tir": "Share of CGM readings in 70–180 mg/dL. Reliable only when the **sensor was worn most days**.",
    "gmi": "A1c estimated from CGM — **not a lab value**; it can differ from a lab HbA1c.",
    "avg_glucose": "Mean of all CGM readings in the period.",
    "cv": "Glucose variability; lower is steadier. **Under 36%** is considered stable.",
    "task_completion": "Share of **assigned care-plan tasks** the patient completed.",
    "calories": "Sum of logged meals per day — **reflects what was logged**, not necessarily total intake.",
    "carbs": "Carbohydrates from logged meals per day.",
    "fiber": "Fiber from logged meals per day.",
    "protein": "Protein from logged meals per day.",
    "fat": "Fat from logged meals per day.",
    "a1c": "Lab HbA1c — **point-in-time**, not continuous. Check the latest date before quoting it.",
    "weight": "Logged or device weight.",
    "sleep_duration": "Average sleep per **tracked night** — nights the device wasn't worn are excluded.",
    "sleep_efficiency": "Time asleep vs time in bed, per tracked night.",
    "steps": "Average steps on days with activity data; **may undercount** when the device isn't carried.",
    "smbg_avg": "Average of all finger-sticks — **mixes fasting and post-meal**, so read the tagged splits below for a cleaner picture.",
    "smbg_fasting": "Average of fasting finger-sticks — the **most comparable** day-to-day glucose line.",
    "smbg_before_meal": "Average of pre-meal finger-sticks.",
    "smbg_after_meal": "Average of post-meal finger-sticks — **expected to run higher** than fasting.",
    "smbg_random": "Average of untagged/random finger-sticks.",
    "tir_ranges": "Where glucose readings fall across the target bands for the **most recent period** — matching the Time-in-range value beside it.",
    "meal_slots": "How each day's logged calories split across meals — **reflects what was logged**, not total intake.",
    "sleep_stages": "Average share of the night in each stage. **Wearable estimates**, not a clinical sleep study.",
}


# A daily report is written even for a day with no synced data; skip those so an
# unsynced day doesn't count as a zero and tank the baseline.
def _empty_sleep(r):
    return ((r.get("metadata") or {}).get("total_sessions") or 0) == 0


def _empty_meal(r):
    return not r.get("meal_count")


def _empty_fitness(r):
    return ((r.get("metadata") or {}).get("days_with_data") or 0) == 0


def _empty_cgm(r):
    # Gate on wear and plausibility, never on in-range % itself, so a fully-worn
    # genuinely-all-out-of-range day still counts.
    meta = r.get("metadata") or {}
    active = meta.get("sensor_active_percent")
    if active is not None:
        if active < _MIN_CGM_ACTIVE_PCT:
            return True
    else:
        readings = meta.get("total_readings")
        if readings is not None and readings < _MIN_CGM_READINGS:
            return True
    avg = (r.get("cgm_summary_stats") or {}).get("average_glucose_mgdl")
    return avg is not None and avg < _MIN_PLAUSIBLE_GLUCOSE


def _glucose_range_segments(preg: bool):
    """The stacked bar's bands must match the tier the headline TIR uses: 63–140
    for pregnancy, 70–180 otherwise. (label, tone, extractor)."""
    if preg:
        return [
            ("Below 63", "bad", _range_sum("below_54_percent", "below_63_above_54_percent")),
            ("In range", "good", _nested(["cgm_range_stats", "in_target_63_140_percent"])),
            ("Above 140", "warn", _range_sum("above_140_percent")),
        ]
    return [
        ("Below 70", "bad", _range_sum("below_54_percent", "below_70_above_54_percent")),
        ("In range", "good", _nested(["cgm_range_stats", "in_target_70_180_percent"])),
        ("Above 180", "warn", _range_sum("above_180_below_250_percent", "above_250_percent")),
    ]


# Related metrics that are slices of one whole → one stacked bar each, instead
# of separate trend lines. (category, key, label, unit, segments, empty) where
# each segment is (label, tone, extractor).
def _composition_defs(preg: bool):
    return [
        ("Glucose", "tir_ranges", "Time in ranges", "%", _glucose_range_segments(preg), _empty_cgm),
        ("Nutrition", "meal_slots", "Calories by meal", "kcal", [
            ("Breakfast", "neutral", _meal_type_cal("breakfast")),
            ("Lunch", "neutral", _meal_type_cal("lunch")),
            ("Dinner", "neutral", _meal_type_cal("dinner")),
            ("Snack", "neutral", _meal_type_cal("snack")),
        ], _empty_meal),
        ("Sleep", "sleep_stages", "Sleep stages", "%", [
            ("Deep", "neutral", _nested(["quality", "deep_sleep_percentage"])),
            ("REM", "neutral", _nested(["quality", "rem_sleep_percentage"])),
            ("Light", "neutral", _sleep_light),
        ], _empty_sleep),
    ]


def _improved(direction: str, delta: float | None) -> bool | None:
    if delta is None:
        return None
    if abs(delta) < 1e-9:
        return None  # no change reads neutral, not bad
    if direction == "up":
        return delta > 0
    if direction == "down":
        return delta < 0
    return abs(delta) < 0.1  # flat: stable is good


def _report_date(report: dict) -> date | None:
    # Meal reports key the day at top-level `date`; the rest use metadata.date_range.
    r = report or {}
    raw = r.get("date") or ((r.get("metadata") or {}).get("date_range") or {}).get("start")
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
        sleep_report_service: SleepReportService,
        meal_report_service: MealReportService,
        fitness_report_service: FitnessReportService,
    ):
        self.postgres_store = postgres_store
        self.repo = ProgressRepository(clickhouse_store)
        self.cgm_report_service = cgm_report_service
        self.sleep_report_service = sleep_report_service
        self.meal_report_service = meal_report_service
        self.fitness_report_service = fitness_report_service

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
        period_days = (end - start).days
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end + timedelta(days=1), time.min)
        pid = UUID(patient_id)

        # Only the session coroutine touches the AsyncSession; the report/vitals
        # sources use ClickHouse/Mongo, so all fan out concurrently. Sleep/meal/
        # fitness range-fetches take dates; CGM takes datetimes.
        (
            vitals_rows, glucose_reports, sleep_reports, meal_reports,
            fitness_reports, session_bundle,
        ) = await asyncio.gather(
            self.repo.vitals_daily(patient_id, start_dt, end_dt),
            self._safe(self.cgm_report_service.fetch_daily_reports, patient_id, start_dt, end_dt),
            self._safe(self.sleep_report_service.fetch_daily_reports_in_range, patient_id, start, end),
            self._safe(self.meal_report_service.fetch_daily_reports_in_range, patient_id, start, end),
            self._safe(self.fitness_report_service.fetch_daily_reports_in_range, patient_id, start, end),
            self._session_bundle(pid, start_dt, end_dt, start, end, postgres_session),
        )
        completion, (cur_streak, longest_streak), adherence, smbg, smbg_by_type, profile = session_bundle
        age, is_pregnant, diabetes_type, bmi = profile
        targets = select_glucose_targets(age, is_pregnant)
        a1c_target = _A1C_TARGET_BY_TIER.get(targets.tier, 7.0)

        metrics: list[MetricSeries] = []

        # ── vitals & labs (ClickHouse daily summary) ─────────────────────────
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
            if vtype == "a1c":
                target = a1c_target
            s = self._build(cat, vtype, label, unit, direction, target,
                            vitals_points.get(vtype, []), resolution, period_days)
            if s:
                metrics.append(s)

        # ── report-backed categories (stored daily reports) ──────────────────
        metrics += self._collect(glucose_reports, "Glucose", _glucose_defs(targets, a1c_target), resolution, period_days, _empty_cgm)
        metrics += self._collect(sleep_reports, "Sleep", _SLEEP, resolution, period_days, _empty_sleep)
        metrics += self._collect(meal_reports, "Nutrition", _meal_defs(bmi, diabetes_type), resolution, period_days, _empty_meal)
        metrics += self._collect(fitness_reports, "Activity", _FITNESS, resolution, period_days, _empty_fitness)

        # ── SMBG (finger-stick glucose, Postgres — for non-CGM patients) ─────
        # Fasting is the cleanest day-to-day line; the blend is kept for context.
        smbg_series = self._build("SMBG", "smbg_avg", "Avg glucose (SMBG)", "mg/dL",
                                  "down", None, smbg, resolution, period_days)
        if smbg_series:
            metrics.append(smbg_series)
        for tag, label in _SMBG_TAGS:
            s = self._build("SMBG", f"smbg_{tag}", label, "mg/dL", "down", None,
                            smbg_by_type.get(tag, []), resolution, period_days)
            if s:
                metrics.append(s)

        # Task completion trends like any metric, so a thin-coverage delta is
        # withheld by the same gating rather than shown as progress.
        eng_metric = self._build("Engagement", "task_completion", "Task completion",
                                 "%", "up", 80.0, completion, resolution, period_days)
        if eng_metric:
            metrics.append(eng_metric)

        # ── compositions (slices of one whole → one stacked bar) ─────────────
        reports_by_cat = {
            "Glucose": glucose_reports, "Nutrition": meal_reports, "Sleep": sleep_reports,
        }
        compositions = []
        for cat, key, label, unit, segdefs, empty in _composition_defs(is_pregnant):
            comp = self._compose(reports_by_cat.get(cat) or [], cat, key, label, unit,
                                 segdefs, resolution, period_days, empty)
            if comp:
                compositions.append(comp)

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
            metrics=metrics, engagement=engagement, compositions=compositions,
            care_intents=[IntentAdherence(**a) for a in adherence],
        )

    # ── internals ────────────────────────────────────────────────────────────

    async def _session_bundle(self, pid, start_dt, end_dt, start, end, session):
        # One AsyncSession can't run concurrent queries — sequential by design.
        completion = await self.repo.task_completion_daily(pid, start, end, session)
        streak = await self.repo.streak(pid, session)
        adherence = await self.repo.care_intent_adherence(pid, start, end, session)
        smbg = await self.repo.smbg_daily(pid, start_dt, end_dt, session)
        smbg_by_type = await self.repo.smbg_by_type_daily(pid, start_dt, end_dt, session)
        profile = await self.repo.clinical_profile(pid, session)
        return completion, streak, adherence, smbg, smbg_by_type, profile

    @staticmethod
    def _collect(reports, category, defs, resolution, period_days, empty=None) -> list[MetricSeries]:
        """Group each metric's daily points across a report stream, then build.
        `empty(report)` drops no-data days so they don't count as zeros."""
        points: dict[str, list[tuple[date, float]]] = {}
        for report in reports or []:
            d = _report_date(report)
            if d is None or (empty and empty(report)):
                continue
            for key, _l, _u, _dir, _t, extract in defs:
                val = extract(report)
                if val is not None:
                    points.setdefault(key, []).append((d, val))
        out: list[MetricSeries] = []
        for key, label, unit, direction, target, _ex in defs:
            s = ProgressService._build(category, key, label, unit, direction, target,
                                       points.get(key, []), resolution, period_days)
            if s:
                out.append(s)
        return out

    @staticmethod
    def _build(category, key, label, unit, direction, target, daily_points, resolution, period_days):
        pts = bucketize(daily_points, resolution)
        if not pts or not any(v != 0 for _, v in pts):
            return None  # no data, or an all-zero series that was never synced
        points = [TrendPoint(t=t, value=v) for t, v in pts]
        # Daily scatter for the client trend line — short ranges only, to bound
        # payload size. Dedupe by day (last wins) so a canonicalized-after-
        # GROUP-BY vital can't emit two points for one day.
        daily: list[TrendPoint] = []
        if period_days <= _DAILY_MAX_PERIOD_DAYS:
            by_day: dict[date, float] = {}
            for d, v in daily_points:
                if v is not None:
                    by_day[d] = float(v)
            daily = [
                TrendPoint(t=d.isoformat(), value=round(v, 2))
                for d, v in sorted(by_day.items())
            ]
        baseline, current = points[0].value, points[-1].value
        days = {d for d, _ in daily_points}
        coverage_days = len(days)
        min_cov = _CGM_MIN_COVERAGE if category == "Glucose" else _MIN_COVERAGE
        low_coverage = (
            category in _DENSITY_CATEGORIES
            and period_days > 0
            and coverage_days / period_days < min_cov
        )
        # No delta when there's a single bucket (no baseline to diff) or when
        # coverage is thin — a "vs start" over sparse data tracks logging cadence,
        # not the metric. The value still shows; only the trend is withheld.
        delta = (
            round(current - baseline, 2)
            if len(points) >= 2 and not low_coverage
            else None
        )
        return MetricSeries(
            category=category, key=key, label=label, unit=unit, dir=direction,
            target=target, points=points, daily=daily, current=current, baseline=baseline,
            delta=delta, note=_NOTES.get(key), coverage_days=coverage_days,
            period_days=period_days, latest=max(days) if days else None,
            low_coverage=low_coverage,
        )

    @staticmethod
    def _compose(reports, category, key, label, unit, segdefs, resolution, period_days, empty=None):
        """One stacked-bar composition. Each segment is reduced the same way as a
        metric headline (latest bucket via bucketize), so the bar's "In range"
        equals the Time-in-range value shown beside it instead of a period mean."""
        seg_daily: dict[str, list[tuple[date, float]]] = {sl: [] for sl, _t, _ex in segdefs}
        days: set[date] = set()
        for report in reports or []:
            d = _report_date(report)
            if d is None or (empty and empty(report)):
                continue
            got = False
            for sl, _tone, ex in segdefs:
                v = ex(report)
                if v is not None:
                    seg_daily[sl].append((d, float(v)))
                    got = True
            if got:
                days.add(d)
        if not days:
            return None
        segments = []
        for sl, tone, _ex in segdefs:
            buckets = bucketize(seg_daily[sl], resolution)
            segments.append(CompositionSegment(
                label=sl, tone=tone, value=round(buckets[-1][1], 1) if buckets else 0.0,
            ))
        if not any(s.value for s in segments):
            return None
        coverage_days = len(days)
        min_cov = _CGM_MIN_COVERAGE if category == "Glucose" else _MIN_COVERAGE
        low_coverage = (
            category in _DENSITY_CATEGORIES
            and period_days > 0
            and coverage_days / period_days < min_cov
        )
        return Composition(
            category=category, key=key, label=label, unit=unit, segments=segments,
            note=_NOTES.get(key), coverage_days=coverage_days, period_days=period_days,
            latest=max(days), low_coverage=low_coverage,
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
            val = round(m.current) if abs(m.current) >= 100 else round(m.current, 1)
            out.append(Outcome(key=key, label=label, value=f"{val:g}{unit}",
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
