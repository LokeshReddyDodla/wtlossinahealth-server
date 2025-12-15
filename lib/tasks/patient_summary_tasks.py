from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Tuple

from celery import shared_task


def _as_utc_range(start: date, end: date) -> Tuple[datetime, datetime]:
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    return start_dt, end_dt


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(
        d.day,
        [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][
            month - 1
        ],
    )
    return date(year, month, day)


def _week_bounds(ref: date) -> Tuple[date, date]:
    start = ref - timedelta(days=ref.weekday())
    end = start + timedelta(days=6)
    return start, end


def _build_periods(reference_dt: datetime | None = None) -> List[Tuple[str, datetime, datetime]]:
    """
    Builds the requested period windows relative to "now" (UTC).
    Periods end at the close of yesterday to avoid partial-day data.
    """

    now = reference_dt or datetime.now(timezone.utc)
    today = now.date()
    yesterday = today - timedelta(days=1)

    this_week_start, this_week_end = _week_bounds(yesterday)
    last_week_end = this_week_start - timedelta(days=1)
    last_week_start, _ = _week_bounds(last_week_end)

    this_month_start = _month_start(yesterday)
    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = _month_start(last_month_end)

    three_month_start = _month_start(_add_months(this_month_start, -2))

    return [
        ("yesterday", *_as_utc_range(yesterday, yesterday)),
        # ("this_week", *_as_utc_range(this_week_start, this_week_end)),
        # ("last_week", *_as_utc_range(last_week_start, last_week_end)),
        # ("this_month", *_as_utc_range(this_month_start, yesterday)),
        # ("last_month", *_as_utc_range(last_month_start, last_month_end)),
        # ("last_3_months", *_as_utc_range(three_month_start, yesterday)),
    ]


@shared_task(queue="default")
async def generate_patient_summary_for_patient(patient_id: str) -> None:
    try:
        from lib.dependencies.service_dependencies import get_patient_summary_service

        service = get_patient_summary_service()
        periods = _build_periods()
        await service.summarize_periods(patient_id, periods)
        print(f"✅ Generated patient summary for {patient_id}")
    except Exception as e:
        print(f"❌ Failed to generate patient summary for {patient_id}. Error: {e}")


@shared_task(queue="default")
async def schedule_daily_patient_summaries() -> None:
    try:
        from lib.dependencies.service_dependencies import get_active_patient_service

        service = get_active_patient_service()
        patient_ids = await service.get_active_patients(days=3)
        
        for patient_id in patient_ids:
            generate_patient_summary_for_patient.delay(patient_id)
        
        print(f"✅ Scheduled patient summaries for {len(patient_ids)} active patients")
    except Exception as e:
        print(f"❌ Failed to schedule daily patient summaries. Error: {e}")

