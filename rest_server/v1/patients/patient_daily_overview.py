from datetime import date
from uuid import UUID

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_daily_overview_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_daily_overview_service import PatientDailyOverviewService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}/daily-overview", response_model=SuccessResponse)
async def get_patient_daily_overview(
    patient_id: str,
    date: date = Query(..., description="The date to fetch daily overview data for"),
    patient_daily_overview_service: PatientDailyOverviewService = Depends(
        get_patient_daily_overview_service
    ),
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
    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id) if patient_id else None,
            care_provider_access_service=care_provider_access_service,
        )

        if not target_patient_id:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Patient not found",
            )

        # Get daily overview data
        overview_data = await patient_daily_overview_service.get_daily_overview(  # type: ignore
            patient_id=str(target_patient_id),
            selected_date=date,
        )

        return SuccessResponse(
            message="Patient daily overview retrieved successfully",
            data=overview_data.dict(),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f"Error retrieving daily overview: {str(e)}",
        )
