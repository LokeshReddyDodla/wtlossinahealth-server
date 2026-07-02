"""V1 SMBG API — paginated blood glucose readings, accessible by all profile types."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.database import get_postgres_session
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_smbg_service,
)
from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.schemas.patient_smbg import PatientSMBGCreate
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_ACTOR_DEPS = dict(
    allowed_roles=[
        ProfileTypeEnum.PATIENT,
        ProfileTypeEnum.CARE_PROVIDER,
        ProfileTypeEnum.ADMIN,
    ],
    check_permissions=False,
)


@router.get("/{patient_id}/smbg", response_model=SuccessResponse)
async def get_patient_smbg(
    patient_id: str,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    start_date: Optional[datetime] = Query(
        None, description="Filter: reading_time >= (ISO 8601)"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Filter: reading_time <= (ISO 8601)"
    ),
    session: AsyncSession = Depends(get_postgres_session),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Paginated SMBG (blood glucose) readings for a patient."""
    try:
        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        base_query = select(PatientSMBGModel).where(
            PatientSMBGModel.patient_id == str(verified_pid)
        )
        if start_date:
            base_query = base_query.where(
                PatientSMBGModel.reading_time >= start_date
            )
        if end_date:
            base_query = base_query.where(
                PatientSMBGModel.reading_time <= end_date
            )

        total_result = await session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = total_result.scalar() or 0

        result = await session.execute(
            base_query.order_by(PatientSMBGModel.reading_time.desc())
            .limit(limit)
            .offset(offset)
        )
        records = result.scalars().all()

        data = [
            {
                "id": str(r.id),
                "patient_id": str(r.patient_id),
                "glucose_level": r.glucose_level,
                "reading_time": r.reading_time,
                "type": r.type,
                "source_name": r.source_name,
                "source_platform": r.source_platform,
                "notes": r.notes,
            }
            for r in records
        ]

        return SuccessResponse(
            message=f"{len(data)} SMBG readings fetched.",
            data={
                "readings": data,
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.put("/{patient_id}/smbg/{smbg_id}", response_model=SuccessResponse)
async def update_smbg(
    patient_id: str,
    smbg_id: str,
    body: PatientSMBGCreate,
    service: PatientSmbgService = Depends(get_patient_smbg_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Update an SMBG reading."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    record = await service.update_smbg(smbg_id, str(verified_pid), body)
    return SuccessResponse(
        message="SMBG reading updated",
        data={
            "id": str(record.id),
            "patient_id": str(record.patient_id),
            "glucose_level": record.glucose_level,
            "reading_time": record.reading_time,
            "type": record.type,
            "source_name": record.source_name,
            "source_platform": record.source_platform,
            "notes": record.notes,
        },
    )


@router.delete("/{patient_id}/smbg/{smbg_id}", response_model=SuccessResponse)
async def delete_smbg(
    patient_id: str,
    smbg_id: str,
    service: PatientSmbgService = Depends(get_patient_smbg_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Delete an SMBG reading."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    await service.delete_smbg(smbg_id, str(verified_pid))
    return SuccessResponse(message="SMBG reading deleted")
