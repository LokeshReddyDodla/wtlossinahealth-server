"""GET /patients/{patient_id}/checkins/history — unified check-in timeline."""

from datetime import date
from typing import Optional

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_checkin_history_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.checkin_history_service import CheckinHistoryService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/{patient_id}/checkins/history",
    response_model=SuccessResponse,
)
async def get_checkin_history(
    patient_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: CheckinHistoryService = Depends(get_checkin_history_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Unified check-in history — sleep, mood, symptoms merged by date with gamification data."""
    try:
        from uuid import UUID

        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        result = await service.get_history(
            patient_id=str(verified_pid),
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message="Check-in history retrieved",
            data=result.model_dump(mode="json"),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch check-in history",
            detail=str(e),
        )
