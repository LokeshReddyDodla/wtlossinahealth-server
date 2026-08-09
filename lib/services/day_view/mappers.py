"""Pure report-dict → typed-payload mappers for the day view.

No I/O — every function takes an already-fetched report dict (or `None`) and
returns typed pieces of the `DayView` payload. This is where the exact report
key paths live, so the extraction is testable without a database.

All report dicts are `model_dump(exclude_none=True)`, so absent keys are the
norm — read with `.get()`, never index blindly.
"""

from dataclasses import dataclass
from datetime import datetime, time, timezone, tzinfo

from lib.ai_foundation.agents.proactive_monitor.contracts import InsightCategory
from lib.schemas.day_view import (
    ActivityRollup,
    DayAlert,
    DoseMarker,
    GlucoseRollup,
    InsightMarker,
    MealMarker,
    NutritionRollup,
    Point,
    SleepRollup,
    Spine,
    SpineEvent,
    SpineSource,
    StageSpan,
    StepsLane,
    VitalMarker,
    WorkoutMarker,
)

_STAGE_MINUTES = 60.0  # inactive_duration / durations are in minutes


def hour_of(value) -> float | None:
    """Decimal hour-of-day (0..24) from a datetime, time, or ISO/`HH:MM:SS` string.

    Times in this system are patient-local naive wall-clock, so the hour is read
    directly with no tz conversion.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            try:
                value = time.fromisoformat(value)
            except ValueError:
                return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return value.hour + value.minute / 60 + value.second / 3600
    return None


# ── Spine (CGM) ──────────────────────────────────────────────────────────────

def cgm_spine(report: dict | None, band: tuple[float, float] = (70.0, 180.0)) -> Spine | None:
    """The continuous glucose spine + excursion event spans, or None if no curve."""
    if not report:
        return None
    readings = report.get("cgm_readings") or []
    points: list[Point] = []
    for r in readings:
        h = hour_of(r.get("device_timestamp"))
        g = r.get("glucose_mgdl")
        if h is not None and g is not None:
            points.append((round(h, 4), float(g)))
    if not points:
        return None

    events: list[SpineEvent] = []
    for e in (report.get("hyper_stats") or {}).get("hyper_events") or []:
        start, end = hour_of(e.get("start_time")), hour_of(e.get("end_time"))
        if start is not None and end is not None:
            events.append(SpineEvent(type="hyper", start=round(start, 3),
                                     end=round(end, 3), peak=float(e.get("peak_glucose_mgdl") or 0)))
    for e in (report.get("hypo_stats") or {}).get("hypo_events") or []:
        start, end = hour_of(e.get("start_time")), hour_of(e.get("end_time"))
        if start is not None and end is not None:
            events.append(SpineEvent(type="hypo", start=round(start, 3),
                                     end=round(end, 3), peak=float(e.get("lowest_glucose_mgdl") or 0)))

    return Spine(source=SpineSource.cgm, unit="mg/dL", points=points, band=band, events=events)


def smbg_spine(points: list[Point], band: tuple[float, float] = (70.0, 180.0)) -> Spine:
    """Finger-stick dots — never joined into a line."""
    return Spine(source=SpineSource.smbg, unit="mg/dL", points=points, band=band)


def empty_spine() -> Spine:
    """No glucose device — behavioral day, no plot. HR still renders in its lane."""
    return Spine(source=SpineSource.none)


def select_spine(cgm_report: dict | None, smbg: list[Point],
                 band: tuple[float, float] = (70.0, 180.0)) -> Spine:
    """Glucose spine: CGM → SMBG dots → none. HR is never the spine — it has its
    own lane, and plotting meals on a heart-rate axis misleads. `band` is the
    profile's target range (63-140 in pregnancy) drawn as the chart target."""
    return (
        cgm_spine(cgm_report, band)
        or (smbg_spine(smbg, band) if smbg else None)
        or empty_spine()
    )


# ── Meals (on-curve) ─────────────────────────────────────────────────────────

def meal_markers(report: dict | None) -> list[MealMarker]:
    if not report:
        return []
    out: list[MealMarker] = []
    for m in report.get("meals") or []:
        h = hour_of(m.get("time"))
        if h is None:
            continue
        gr = m.get("glucose_response") or {}
        gc = m.get("glucose_comparison") or {}
        macros = m.get("total_macro_nutritional_value") or {}
        predicted = None
        lo, hi = gc.get("predicted_low"), gc.get("predicted_high")
        if lo is not None and hi is not None:
            predicted = (float(lo), float(hi))
        out.append(MealMarker(
            t=round(h, 3),
            name=(m.get("name") or (m.get("type") or "meal").replace("_", " ").title()),
            type=m.get("type"),
            delta_mgdl=gr.get("delta_mgdl"),
            score=m.get("score"),
            comparison=gc.get("outcome"),
            predicted=predicted,
            carbs_g=macros.get("carbohydrates"),
        ))
    return out


def workout_markers(report: dict | None) -> list[WorkoutMarker]:
    """Per-session workouts from the fitness report → on-curve glyphs, positioned
    by `start_time`."""
    if not report:
        return []
    out: list[WorkoutMarker] = []
    for w in report.get("workouts") or []:
        h = hour_of(w.get("start_time"))
        if h is None:
            continue
        dur = w.get("total_duration")
        out.append(WorkoutMarker(
            t=round(h, 3),
            type=w.get("type") or "Workout",
            minutes=int(dur) if dur else None,
            kcal=w.get("total_energy"),
        ))
    return out


# ── Heart-rate lane ──────────────────────────────────────────────────────────

def hr_hourly(points: list[Point]) -> list[Point]:
    """Raw HR samples → 24 hourly-average buckets (bpm) for the sparkline lane."""
    buckets: dict[int, list[float]] = {}
    for h, v in points:
        buckets.setdefault(int(h), []).append(v)
    return [(float(b), round(sum(vs) / len(vs), 1)) for b, vs in sorted(buckets.items())]


# ── Steps lane ───────────────────────────────────────────────────────────────

def steps_lane(report: dict | None) -> StepsLane:
    if not report:
        return StepsLane()
    hourly: list[Point] = []
    for h in report.get("hourly_stats") or []:
        hour, steps = h.get("hour"), h.get("steps")
        if hour is not None and steps is not None:
            hourly.append((float(hour), float(steps)))
    inactive = []
    for p in report.get("inactive_periods") or []:
        start, end = hour_of(p.get("start_time")), hour_of(p.get("end_time"))
        if start is not None and end is not None:
            inactive.append((round(start, 3), round(end, 3)))
    return StepsLane(hourly=hourly, inactive=inactive)


# ── Header rollups ───────────────────────────────────────────────────────────

def glucose_rollup(report: dict | None, preg: bool = False) -> GlucoseRollup:
    if not report:
        return GlucoseRollup()
    rng = report.get("cgm_range_stats") or {}
    summ = report.get("cgm_summary_stats") or {}
    # `bands` describes the same window as tir_pct so every bar matches its number:
    # 4 pregnancy bands (63-140) or the canonical 5 (70-180).
    if preg:
        band_keys = ["below_54_percent", "below_63_above_54_percent",
                     "in_target_63_140_percent", "above_140_percent"]
        tir_key = "in_target_63_140_percent"
    else:
        band_keys = ["below_54_percent", "below_70_above_54_percent", "in_target_70_180_percent",
                     "above_180_below_250_percent", "above_250_percent"]
        tir_key = "in_target_70_180_percent"
    raw = [rng.get(k) for k in band_keys]
    bands = [float(b or 0) for b in raw] if any(b is not None for b in raw) else None
    if preg and rng.get("in_target_63_140_percent") is None:
        bands = None   # pregnancy report not yet regenerated with the 63-140 bands
    return GlucoseRollup(
        tir_pct=rng.get(tir_key),
        avg=summ.get("average_glucose_mgdl"),
        gri=summ.get("gri"),
        cv_pct=summ.get("coefficient_of_variation_percent"),
        low_mgdl=summ.get("lowest_glucose_mgdl"),
        high_mgdl=summ.get("highest_glucose_mgdl"),
        bands=bands,
        tir_preg_pct=rng.get("in_target_63_140_percent"),
        tbr_54_63_pct=rng.get("below_63_above_54_percent"),
        tar_140_pct=rng.get("above_140_percent"),
    )


def nutrition_rollup(report: dict | None) -> NutritionRollup:
    if not report:
        return NutritionRollup()
    target = (report.get("diet_recommendations") or {}).get("calories")
    return NutritionRollup(
        kcal=report.get("calories"),
        kcal_target=target or None,
        meals=report.get("meal_count"),
    )


def sleep_rollup(report: dict | None) -> tuple[SleepRollup, float | None, float | None]:
    """Returns (header rollup, asleep_h, efficiency) — the lane reuses the latter two."""
    if not report:
        return SleepRollup(), None, None
    total_min = (report.get("duration") or {}).get("total_duration")
    eff = (report.get("quality") or {}).get("sleep_efficiency")
    asleep_h = round(total_min / _STAGE_MINUTES, 2) if total_min else None
    return SleepRollup(asleep_h=asleep_h, efficiency=eff), asleep_h, eff


def _to_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def sleep_stages_from_report(
    report: dict | None, day_start: datetime
) -> list[StageSpan]:
    """The sleep report's hypnogram → hour-of-day spans relative to day_start,
    clipped to [0, 24]. Empty when the report predates the hypnogram field — the
    resolver then falls back to the raw sleep_data query."""
    if not report:
        return []
    spans: list[StageSpan] = []
    for seg in report.get("hypnogram") or []:
        start = _to_dt(seg.get("start"))
        end = _to_dt(seg.get("end"))
        stage = seg.get("stage")
        if start is None or end is None or not stage:
            continue
        start_h = max(0.0, (start - day_start).total_seconds() / 3600)
        end_h = min(24.0, (end - day_start).total_seconds() / 3600)
        if end_h <= start_h:
            continue
        spans.append((round(start_h, 3), round(end_h, 3), stage))
    return spans


def activity_rollup(report: dict | None, steps_goal: int | None = None) -> ActivityRollup:
    if not report:
        return ActivityRollup()
    steps = report.get("steps")
    # session_count can exceed 1 (type-aggregated rows), so sum, don't count.
    workouts = sum((w.get("session_count") or 1) for w in (report.get("workouts") or []))
    return ActivityRollup(
        steps=int(steps) if isinstance(steps, (int, float)) else None,
        steps_goal=steps_goal,
        workouts=workouts or None,
    )


# ── Proactive insights ───────────────────────────────────────────────────────

_PROVIDER_HIDDEN = (
    InsightCategory.COACHING_HABIT,
    InsightCategory.COACHING_CELEBRATION,
    InsightCategory.COACHING_CORRECTION,
    InsightCategory.COACHING_MEDICATION,
    InsightCategory.MEAL_MISSED,
    InsightCategory.ENGAGEMENT_DROP,
    InsightCategory.GENERAL,
)
_HIDDEN_CATEGORY_VALUES = frozenset(c.value for c in _PROVIDER_HIDDEN)


def insight_markers(docs: list[dict], tz: tzinfo) -> list[InsightMarker]:
    """Proactive-monitor insights placed at their source event's local hour.

    Stored UTC-aware in Mongo (unlike the other day-view series), so `t` is a real
    conversion into `tz`, not a wall-clock read.
    """
    markers: list[InsightMarker] = []
    for doc in docs:
        if doc.get("category") in _HIDDEN_CATEGORY_VALUES:
            continue
        placed = doc.get("event_time") or doc.get("created_at")
        if not isinstance(placed, datetime):
            continue
        if placed.tzinfo is None:
            placed = placed.replace(tzinfo=timezone.utc)
        local = placed.astimezone(tz)
        streak = doc.get("consecutive_days")
        markers.append(InsightMarker(
            t=round(local.hour + local.minute / 60 + local.second / 3600, 4),
            insight_id=doc.get("insight_id"),
            severity=doc.get("severity") or "info",
            category=doc.get("category") or "",
            title=doc.get("title"),
            message=doc.get("message") or "",
            suggested_query=doc.get("suggested_query"),
            entity_type=doc.get("entity_type"),
            entity_id=str(doc["entity_id"]) if doc.get("entity_id") else None,
            recurring_days=streak if isinstance(streak, int) and streak > 1 else None,
        ))
    markers.sort(key=lambda m: m.t)
    return markers


# ── Clinical alerts (2019 International Consensus on Time in Range) ────────────

_SEVERITY_ORDER = {"critical": 0, "attention": 1, "info": 2}
_CV_MAX = 36.0  # glucose-stability ceiling (CV%), constant across tiers


@dataclass(frozen=True)
class GlucoseTargets:
    """Per-population CGM targets as % of day. Battelino et al., Diabetes Care
    2019;42:1593-1603, Table 1. Severity labels are ours; the numbers are not."""

    tier: str
    tir_min: float                  # in-range floor
    tbr_l1_max: float               # time below the L1 low edge, ceiling
    tbr_l2_max: float               # time <54 ceiling
    tar_max: float                  # time above the high edge, ceiling
    tbr_l1_edge: int                # mg/dL edge for the L1 low band (70; 63 in pregnancy)
    tar_edge: int                   # mg/dL edge for the high band (250; 140 in pregnancy)
    in_range: tuple[float, float]   # the chart target band + the headline TIR window


_STANDARD = GlucoseTargets("standard", tir_min=70, tbr_l1_max=4, tbr_l2_max=1, tar_max=5, tbr_l1_edge=70, tar_edge=250, in_range=(70.0, 180.0))
_OLDER = GlucoseTargets("older_high_risk", tir_min=50, tbr_l1_max=1, tbr_l2_max=1, tar_max=10, tbr_l1_edge=70, tar_edge=250, in_range=(70.0, 180.0))
_PREGNANCY = GlucoseTargets("pregnancy", tir_min=70, tbr_l1_max=4, tbr_l2_max=1, tar_max=25, tbr_l1_edge=63, tar_edge=140, in_range=(63.0, 140.0))


def select_glucose_targets(age: float | None, is_pregnant: bool) -> GlucoseTargets:
    """The consensus target tier for a patient — pregnancy (63-140 range) and
    older/high-risk each carry their own targets in the 2019 consensus."""
    if is_pregnant:
        return _PREGNANCY
    if age is not None and age >= 65:
        return _OLDER
    return _STANDARD


def _glucose_alerts(g: GlucoseRollup, t: GlucoseTargets) -> list[DayAlert]:
    """Compare the pre-computed CGM percentages to the tier's consensus targets.
    Pregnancy reads the 63-140 bands; every other tier the canonical 70-180."""
    if t.tier == "pregnancy" and g.tir_preg_pct is None:
        return [DayAlert(severity="info", category="glucose_targets_unsupported",
                         label="Glucose targets need a report refresh")]
    if g.bands is None:
        return []

    tbr_l2 = g.bands[0]                               # <54, every tier
    if t.tier == "pregnancy":
        tbr_l1 = tbr_l2 + (g.tbr_54_63_pct or 0.0)   # <63
        tir, tar = g.tir_preg_pct, (g.tar_140_pct or 0.0)
    else:
        tbr_l1 = tbr_l2 + g.bands[1]                  # <70
        tir, tar = g.tir_pct, g.bands[4]             # >250

    low = f" · low {int(g.low_mgdl)}" if g.low_mgdl is not None else ""
    high = f" · peak {int(g.high_mgdl)}" if g.high_mgdl is not None else ""

    out: list[DayAlert] = []
    if tbr_l2 > t.tbr_l2_max:
        out.append(DayAlert(severity="critical", category="tbr_l2",
                            label=f"Serious lows · {tbr_l2:.0f}% of day below 54{low}"))
    elif tbr_l1 > t.tbr_l1_max:
        out.append(DayAlert(severity="attention", category="tbr_l1",
                            label=f"Lows · {tbr_l1:.0f}% of day below {t.tbr_l1_edge}{low}"))

    if tar > t.tar_max:
        out.append(DayAlert(severity="attention", category="tar_high",
                            label=f"Very high · {tar:.0f}% of day above {t.tar_edge}{high}"))

    if tir is not None and tir < t.tir_min:
        out.append(DayAlert(severity="attention", category="tir_low",
                            label=f"Time in range {tir:.0f}% (target >{t.tir_min:.0f}%)"))

    if g.cv_pct is not None and g.cv_pct > _CV_MAX:
        out.append(DayAlert(severity="attention", category="glucose_cv",
                            label=f"Glucose swings · CV {g.cv_pct:.0f}%"))
    return out


def day_alerts(
    glucose: GlucoseRollup,
    spine: Spine,
    bp: list[VitalMarker],
    doses: list[DoseMarker],
    targets: GlucoseTargets,
) -> list[DayAlert]:
    """Provider-facing clinical flags for the day, most-severe first.

    Reads only pre-computed values — the CGM range/summary percentages, BP
    readings, dose statuses — and compares them to `targets`, the consensus tier
    chosen from the patient profile. No clinical stat is re-derived here.
    """
    out: list[DayAlert] = []

    if spine.source == SpineSource.none:
        out.append(DayAlert(severity="info", category="no_glucose", label="No glucose data"))
    else:
        out += _glucose_alerts(glucose, targets)

    crisis = [v for v in bp if (v.systolic is not None and v.systolic >= 180)
              or (v.diastolic is not None and v.diastolic >= 120)]
    highs = [v for v in bp if (v.systolic is not None and v.systolic >= 140)
             or (v.diastolic is not None and v.diastolic >= 90)]
    if crisis:
        worst = max(crisis, key=lambda v: v.systolic or 0)
        out.append(DayAlert(severity="critical", category="bp_high",
                            label=f"Hypertensive crisis · BP {int(worst.systolic or 0)}/{int(worst.diastolic or 0)}",
                            t=worst.t))
    elif highs:
        worst = max(highs, key=lambda v: v.systolic or 0)
        out.append(DayAlert(severity="attention", category="bp_high",
                            label=f"BP {int(worst.systolic or 0)}/{int(worst.diastolic or 0)}", t=worst.t))

    missed = sum(1 for d in doses if d.status == "missed")
    if missed > 0:
        out.append(DayAlert(severity="attention", category="doses_missed",
                            label=f"{missed} dose{'s' if missed != 1 else ''} missed"))

    out.sort(key=lambda a: _SEVERITY_ORDER.get(a.severity, 3))
    return out
