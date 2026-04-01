from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_vital_service,
)
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_vital_service import PatientVitalService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}/vitals", response_model=SuccessResponse)
async def get_patient_vitals(
    patient_id: str,
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    start_date: Optional[datetime] = Query(None, description="Filter: test_time >= start_date (ISO 8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter: test_time <= end_date (ISO 8601)"),
    patient_vital_service: PatientVitalService = Depends(get_patient_vital_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get vitals for a patient with pagination and optional date filtering.

    Patients see their own vitals, care providers see assigned patients' vitals.
    """
    try:
        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        vital_records, total = await patient_vital_service.get_patient_vitals(
            str(verified_pid),
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
        )

        vitals = [PatientVitalSchema.model_validate(record) for record in vital_records]

        return SuccessResponse(
            message=f"{len(vitals)} vitals fetched.",
            data={
                "vitals": vitals,
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
