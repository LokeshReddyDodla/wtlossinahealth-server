"""V1 Check-in endpoints — sleep check-ins and mood entries."""

from datetime import date, datetime
from typing import Optional

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_daily_checkin_service,
)
from lib.schemas.daily_checkin import (
    MoodEntryInput,
    MoodEntryResponse,
    SleepCheckinInput,
    SleepCheckinResponse,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.daily_checkin_service import DailyCheckinService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_ACTOR_DEPS = dict(
    allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
    check_permissions=False,
)


# ── Sleep ──────────────────────────────────────────────────────────────────


@router.post("/{patient_id}/checkins/sleep", response_model=SuccessResponse)
async def upsert_sleep_checkin(
    patient_id: str,
    body: SleepCheckinInput,
    service: DailyCheckinService = Depends(get_daily_checkin_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        record = await service.upsert_sleep(str(verified_pid), body)
        return SuccessResponse(
            message="Sleep check-in saved.",
            data=SleepCheckinResponse(
                id=str(record.id),
                patient_id=str(record.patient_id),
                checkin_date=record.checkin_date,
                quality=record.quality,
                hours_slept=record.hours_slept,
                bed_time=record.bed_time,
                wake_time=record.wake_time,
                notes=record.notes,
                created_at=record.created_at,
                updated_at=record.updated_at,
            ),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/{patient_id}/checkins/sleep", response_model=SuccessResponse)
async def get_sleep_history(
    patient_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: DailyCheckinService = Depends(get_daily_checkin_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        records, total = await service.get_sleep_history(
            str(verified_pid), start_date=start_date, end_date=end_date,
            limit=limit, offset=offset,
        )
        checkins = [
            SleepCheckinResponse(
                id=str(r.id), patient_id=str(r.patient_id),
                checkin_date=r.checkin_date, quality=r.quality,
                hours_slept=r.hours_slept, bed_time=r.bed_time,
                wake_time=r.wake_time, notes=r.notes,
                created_at=r.created_at, updated_at=r.updated_at,
            )
            for r in records
        ]
        return SuccessResponse(
            message=f"{len(checkins)} sleep check-ins fetched.",
            data={"checkins": checkins, "total": total, "limit": limit, "offset": offset},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/{patient_id}/checkins/sleep/trends", response_model=SuccessResponse)
async def get_sleep_trends(
    patient_id: str,
    period: str = Query("weekly", regex="^(weekly|monthly)$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    service: DailyCheckinService = Depends(get_daily_checkin_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        trends = await service.get_sleep_trends(
            str(verified_pid), period=period,
            start_date=start_date, end_date=end_date,
        )
        return SuccessResponse(message="Sleep trends.", data=trends)
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


# ── Mood ───────────────────────────────────────────────────────────────────


@router.post("/{patient_id}/checkins/mood", response_model=SuccessResponse)
async def add_mood_entry(
    patient_id: str,
    body: MoodEntryInput,
    service: DailyCheckinService = Depends(get_daily_checkin_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        record = await service.add_mood(str(verified_pid), body)
        return SuccessResponse(
            message="Mood entry saved.",
            data=MoodEntryResponse(
                id=str(record.id),
                patient_id=str(record.patient_id),
                level=record.level,
                emoji=record.emoji,
                tags=record.tags or [],
                notes=record.notes,
                recorded_at=record.recorded_at,
                created_at=record.created_at,
            ),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/{patient_id}/checkins/mood", response_model=SuccessResponse)
async def get_mood_history(
    patient_id: str,
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: DailyCheckinService = Depends(get_daily_checkin_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        records, total = await service.get_mood_history(
            str(verified_pid), start_date=start_date, end_date=end_date,
            limit=limit, offset=offset,
        )
        entries = [
            MoodEntryResponse(
                id=str(r.id), patient_id=str(r.patient_id),
                level=r.level, emoji=r.emoji, tags=r.tags or [],
                notes=r.notes, recorded_at=r.recorded_at,
                created_at=r.created_at,
            )
            for r in records
        ]
        return SuccessResponse(
            message=f"{len(entries)} mood entries fetched.",
            data={"entries": entries, "total": total, "limit": limit, "offset": offset},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/{patient_id}/checkins/mood/trends", response_model=SuccessResponse)
async def get_mood_trends(
    patient_id: str,
    period: str = Query("weekly", regex="^(weekly|monthly)$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    service: DailyCheckinService = Depends(get_daily_checkin_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        trends = await service.get_mood_trends(
            str(verified_pid), period=period,
            start_date=start_date, end_date=end_date,
        )
        return SuccessResponse(message="Mood trends.", data=trends)
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
