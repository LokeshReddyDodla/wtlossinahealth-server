"""V1 Vitals API — ClickHouse-backed endpoints for patient vitals."""

from datetime import datetime
from typing import Optional

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_vital_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_vital_service import PatientVitalService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_ACTOR_DEPS = dict(
    allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
    check_permissions=False,
)


@router.get("/{patient_id}/vitals", response_model=SuccessResponse)
async def get_patient_vitals(
    patient_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_date: Optional[datetime] = Query(None, description="Filter: time >= (ISO 8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter: time <= (ISO 8601)"),
    patient_vital_service: PatientVitalService = Depends(get_patient_vital_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Paginated vitals list from ClickHouse."""
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        vitals, total = await patient_vital_service.get_patient_vitals(
            str(verified_pid), limit=limit, offset=offset,
            start_date=start_date, end_date=end_date,
        )
        return SuccessResponse(
            message=f"{len(vitals)} vitals fetched.",
            data={"vitals": vitals, "total": total, "limit": limit, "offset": offset},
        )
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, message="Internal Server Error", detail=str(e))


@router.get("/{patient_id}/vitals/summary", response_model=SuccessResponse)
async def get_vitals_summary(
    patient_id: str,
    start_date: datetime = Query(..., description="Start date (ISO 8601)"),
    end_date: datetime = Query(..., description="End date (ISO 8601)"),
    patient_vital_service: PatientVitalService = Depends(get_patient_vital_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Daily avg/min/max/count per vital type."""
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        summaries = await patient_vital_service.get_vitals_summary(
            str(verified_pid), start_date, end_date,
        )

        # Group by date for a cleaner response
        by_date: dict[str, dict] = {}
        for row in summaries:
            d = row["date"]
            if d not in by_date:
                by_date[d] = {"date": d}
            by_date[d][row["type"]] = {
                "avg": row["avg"], "min": row["min"],
                "max": row["max"], "count": row["count"],
            }

        return SuccessResponse(
            message=f"{len(by_date)} days of vitals.",
            data={"summaries": list(by_date.values())},
        )
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, message="Internal Server Error", detail=str(e))


@router.get("/{patient_id}/vitals/latest", response_model=SuccessResponse)
async def get_latest_vitals(
    patient_id: str,
    patient_vital_service: PatientVitalService = Depends(get_patient_vital_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Most recent reading per vital type."""
    try:
        from uuid import UUID
        verified_pid = await resolve_patient_access(
            actor=current_actor, patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        latest = await patient_vital_service.get_latest_vitals(str(verified_pid))
        return SuccessResponse(
            message=f"{len(latest)} vital types.",
            data={"vitals": latest},
        )
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, message="Internal Server Error", detail=str(e))
