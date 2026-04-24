"""GET /patients/{patient_id}/fitness-report — unified fitness report."""

from datetime import date
from typing import Optional

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_fitness_report_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_fitness_report_service import PatientFitnessReportService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}/fitness-report", response_model=SuccessResponse)
async def get_fitness_report(
    patient_id: str,
    date_param: Optional[date] = Query(
        None, alias="date", description="Single day (YYYY-MM-DD)"
    ),
    start_date: Optional[date] = Query(None, description="Range start (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Range end (YYYY-MM-DD)"),
    service: PatientFitnessReportService = Depends(get_patient_fitness_report_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    target_patient_id = await resolve_patient_access(
        actor=current_actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )

    # Resolve date params
    if date_param:
        sd = ed = date_param
    elif start_date and end_date:
        sd, ed = start_date, end_date
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'date' or both 'start_date' and 'end_date'.",
        )

    if ed < sd:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date must be >= start_date.",
        )
    if (ed - sd).days > 31:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date range cannot exceed 31 days.",
        )

    report = await service.get_report(str(target_patient_id), sd, ed)
    return SuccessResponse(
        message="Fitness report",
        data=report.model_dump(mode="json"),
    )
