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
)
from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


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
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            check_permissions=False,
        )
    ),
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
