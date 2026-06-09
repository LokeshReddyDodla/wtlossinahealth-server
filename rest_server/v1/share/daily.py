from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import Depends, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (
    get_patient_daily_overview_service,
)
from lib.models.mood_entry import MoodEntry
from lib.models.sleep_checkin import SleepCheckin
from lib.services.patient_daily_overview_service import PatientDailyOverviewService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import (
    ALL_PILLAR_KEYS,
    ShareDailyResponse,
    ShareMetric,
    SharePillar,
    SharePillarKey,
)
from .router import router


def _safe_pct_delta(current: float, previous: Optional[float]) -> Optional[float]:
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _build_nutrition_pillar(overview) -> Optional[SharePillar]:
    m = overview.meals.daily
    if m.calories == 0 and m.proteins == 0:
        return None
    return SharePillar(
        key=SharePillarKey.NUTRITION,
        primary=ShareMetric(label="Calories", value=round(m.calories), unit="kcal"),
        secondary=[
            ShareMetric(label="Protein", value=round(m.proteins), unit="g"),
            ShareMetric(label="Carbs", value=round(m.carbohydrates), unit="g"),
            ShareMetric(label="Fat", value=round(m.fats), unit="g"),
            ShareMetric(label="Fiber", value=round(m.fiber), unit="g"),
        ],
    )


def _build_movement_pillar(overview) -> Optional[SharePillar]:
    f = overview.fitness
    if f.steps == 0 and f.active_energy == 0:
        return None
    delta = _safe_pct_delta(float(f.steps), float(overview.previous.steps) if overview.previous.steps else None)
    return SharePillar(
        key=SharePillarKey.MOVEMENT,
        primary=ShareMetric(label="Steps", value=f.steps, unit=""),
        secondary=[
            ShareMetric(label="Active", value=f.active_duration, unit="min"),
            ShareMetric(label="Energy", value=round(f.active_energy), unit="kcal"),
        ],
        delta_percent=delta,
    )


def _build_sleep_pillar(overview, sleep_checkin: Optional["SleepCheckin"] = None) -> Optional[SharePillar]:
    s = overview.sleep
    has_synced = s.duration > 0
    has_checkin = sleep_checkin is not None

    if not has_synced and not has_checkin:
        return None

    if has_synced:
        primary = ShareMetric(label="Sleep", value=round(s.duration, 1), unit="h")
    else:
        primary = ShareMetric(label="Sleep", value=round(sleep_checkin.hours_slept, 1), unit="h")

    secondary = []
    if has_checkin:
        quality_labels = {1: "Very Poor", 2: "Poor", 3: "Fair", 4: "Good", 5: "Great"}
        secondary.append(
            ShareMetric(label="Quality", value=quality_labels.get(sleep_checkin.quality, ""), unit="")
        )
        if sleep_checkin.bed_time and sleep_checkin.wake_time:
            secondary.append(
                ShareMetric(label="Bed", value=sleep_checkin.bed_time, unit="")
            )
            secondary.append(
                ShareMetric(label="Wake", value=sleep_checkin.wake_time, unit="")
            )
        if has_synced:
            secondary.append(
                ShareMetric(label="Self-reported", value=round(sleep_checkin.hours_slept, 1), unit="h")
            )

    delta = _safe_pct_delta(
        primary.value if isinstance(primary.value, (int, float)) else 0,
        overview.previous.sleep_duration,
    )
    return SharePillar(
        key=SharePillarKey.SLEEP,
        primary=primary,
        secondary=secondary,
        delta_percent=delta,
    )


def _build_glucose_pillar(overview) -> Optional[SharePillar]:
    g = overview.glucose
    if g.time_in_range == 0 and g.average_glucose == 0:
        return None
    delta = _safe_pct_delta(g.time_in_range, overview.previous.time_in_range)
    below = round(g.range.below_54 + g.range.below_70)
    above = round(g.range.above_180 + g.range.above_250)
    in_range = round(g.range.in_target)
    return SharePillar(
        key=SharePillarKey.GLUCOSE,
        primary=ShareMetric(label="Time in range", value=round(g.time_in_range), unit="%"),
        secondary=[
            ShareMetric(label="Below range", value=below, unit="%"),
            ShareMetric(label="In range", value=in_range, unit="%"),
            ShareMetric(label="Above range", value=above, unit="%"),
        ],
        delta_percent=delta,
    )


def _build_mood_pillar(mood_entry: MoodEntry) -> SharePillar:
    emoji_map = {
        "very_bad": "\U0001f629",
        "bad": "\U0001f641",
        "neutral": "\U0001f610",
        "good": "\U0001f642",
        "great": "\U0001f60a",
    }
    label_map = {
        "very_bad": "Very Bad",
        "bad": "Bad",
        "neutral": "Neutral",
        "good": "Good",
        "great": "Great",
    }
    return SharePillar(
        key=SharePillarKey.MOOD,
        primary=ShareMetric(
            label="Mood",
            value=f"{emoji_map.get(mood_entry.emoji, '')} {label_map.get(mood_entry.emoji, mood_entry.emoji)}",
            unit="",
        ),
    )


def _build_workouts_pillar(overview) -> Optional[SharePillar]:
    w = overview.workouts
    if w.session_count == 0:
        return None
    secondary = [
        ShareMetric(label="Duration", value=w.total_duration_minutes, unit="min"),
        ShareMetric(label="Burned", value=round(w.total_calories), unit="kcal"),
    ]
    if w.types:
        secondary.append(ShareMetric(label="Types", value=", ".join(w.types), unit=""))
    return SharePillar(
        key=SharePillarKey.WORKOUTS,
        primary=ShareMetric(label="Workouts", value=w.session_count, unit="sessions"),
        secondary=secondary,
    )


def _build_vitals_pillar(overview) -> Optional[SharePillar]:
    v = overview.vitals
    if v.resting_heart_rate is None and v.blood_pressure.systolic is None:
        return None
    secondary = []
    if v.blood_pressure.systolic is not None and v.blood_pressure.diastolic is not None:
        secondary.append(
            ShareMetric(
                label="BP",
                value=f"{int(v.blood_pressure.systolic)}/{int(v.blood_pressure.diastolic)}",
                unit="mmHg",
            )
        )
    primary_value: float | str = ""
    primary_label = "Heart Rate"
    primary_unit = "bpm"
    if v.resting_heart_rate is not None:
        primary_value = round(v.resting_heart_rate)
    elif v.blood_pressure.systolic is not None:
        primary_label = "BP"
        primary_value = f"{int(v.blood_pressure.systolic)}/{int(v.blood_pressure.diastolic)}"
        primary_unit = "mmHg"
        secondary = []
    return SharePillar(
        key=SharePillarKey.VITALS,
        primary=ShareMetric(label=primary_label, value=primary_value, unit=primary_unit),
        secondary=secondary,
    )


PILLAR_BUILDERS = {
    SharePillarKey.NUTRITION: _build_nutrition_pillar,
    SharePillarKey.MOVEMENT: _build_movement_pillar,
    SharePillarKey.GLUCOSE: _build_glucose_pillar,
    SharePillarKey.WORKOUTS: _build_workouts_pillar,
    SharePillarKey.VITALS: _build_vitals_pillar,
}


@router.get("/daily", response_model=SuccessResponse)
async def get_share_daily(
    date: date = Query(..., description="Date for the daily snapshot"),
    include: Optional[str] = Query(
        None,
        description="Comma-separated pillar keys to include (e.g. nutrition,movement,sleep). "
        "Omit to include all available pillars.",
    ),
    overview_service: PatientDailyOverviewService = Depends(
        get_patient_daily_overview_service
    ),
    session: AsyncSession = Depends(get_postgres_session),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT],
        )
    ),
):
    requested_keys: set[str] | None = None
    if include:
        requested_keys = {k.strip().lower() for k in include.split(",")}
        invalid = requested_keys - ALL_PILLAR_KEYS
        if invalid:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"Unknown pillar keys: {', '.join(sorted(invalid))}. "
                f"Valid keys: {', '.join(sorted(ALL_PILLAR_KEYS))}",
            )

    patient_id = current_actor.id

    overview = await overview_service.get_daily_overview(
        patient_id=patient_id,
        selected_date=date,
    )

    pillars: list[SharePillar] = []

    for key, builder in PILLAR_BUILDERS.items():
        if requested_keys and key.value not in requested_keys:
            continue
        pillar = builder(overview)
        if pillar:
            pillars.append(pillar)

    if requested_keys is None or SharePillarKey.SLEEP.value in requested_keys:
        checkin_result = await session.execute(
            select(SleepCheckin).where(
                and_(
                    SleepCheckin.patient_id == patient_id,
                    SleepCheckin.checkin_date == date,
                )
            )
        )
        sleep_checkin = checkin_result.scalars().first()
        sleep_pillar = _build_sleep_pillar(overview, sleep_checkin)
        if sleep_pillar:
            pillars.append(sleep_pillar)

    if requested_keys is None or SharePillarKey.MOOD.value in requested_keys:
        day_start = datetime.combine(date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        result = await session.execute(
            select(MoodEntry)
            .where(
                and_(
                    MoodEntry.patient_id == patient_id,
                    MoodEntry.recorded_at >= day_start,
                    MoodEntry.recorded_at < day_end,
                )
            )
            .order_by(MoodEntry.recorded_at.desc())
            .limit(1)
        )
        mood_entry = result.scalars().first()
        if mood_entry:
            pillars.append(_build_mood_pillar(mood_entry))

    return SuccessResponse(
        message="Daily share snapshot",
        data=ShareDailyResponse(
            date=str(date),
            pillars=pillars,
        ).model_dump(),
    )
