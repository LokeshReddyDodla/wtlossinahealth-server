"""Timezone helpers for gamification processing."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from lib.ai_foundation.config import settings

DEFAULT_TIMEZONE = settings.DEFAULT_PATIENT_TIMEZONE

logger = logging.getLogger(__name__)


def resolve_timezone_name(tz_name: str | None) -> str:
    """Return a valid IANA timezone name, falling back to DEFAULT_TIMEZONE."""
    candidate = tz_name or DEFAULT_TIMEZONE
    try:
        ZoneInfo(candidate)
        return candidate
    except Exception:
        logger.debug(
            "Invalid timezone %r; falling back to %s",
            tz_name,
            DEFAULT_TIMEZONE,
        )
        return DEFAULT_TIMEZONE


def resolve_timezone(tz_name: str | None) -> ZoneInfo:
    return ZoneInfo(resolve_timezone_name(tz_name))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_now(tz_name: str | None, *, now: datetime | None = None) -> datetime:
    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(resolve_timezone(tz_name))


def local_today(tz_name: str | None, *, now: datetime | None = None) -> date:
    return local_now(tz_name, now=now).date()


def matches_local_hour(
    tz_name: str | None,
    target_hour: int,
    *,
    now: datetime | None = None,
) -> bool:
    return local_now(tz_name, now=now).hour == target_hour


async def patient_today(patient_id, session) -> date:
    """Return the patient's local date. Shared across all gamification services."""
    tz = await get_patient_timezone(patient_id, session)
    return local_today(tz)


async def get_patient_timezone(
    patient_id,
    session,
) -> str | None:
    """Shared helper: fetch a patient's locale/timezone from the DB.

    Used by multiple gamification services — centralised here to avoid
    the same 4-line query being copy-pasted across 5+ files.
    """
    from sqlalchemy import select
    from lib.models.patient import Patient

    result = await session.execute(
        select(Patient.timezone).where(Patient.patient_id == patient_id)
    )
    return result.scalar()


def naive_day_bounds_for_local_date(
    target_date: date,
    tz_name: str | None,
) -> tuple[datetime, datetime]:
    """Return naive UTC timestamps matching a local calendar day.

    Stored timestamps in this codebase are mostly naive UTC values, so this
    helper converts local day boundaries to naive UTC boundaries for queries.
    """
    tz = resolve_timezone(tz_name)
    start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz)
    end_local = datetime.combine(target_date, datetime.max.time(), tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc
