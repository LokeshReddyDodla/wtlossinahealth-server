from datetime import date, timedelta

from fastapi import Depends, Query, status
from uuid import UUID

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_data_availability_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_data_availability_service import (
    PatientDataAvailabilityService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}/data-availability", response_model=SuccessResponse)
async def get_patient_data_availability(
    patient_id: str,
    target_date: date = Query(
        ..., description="The target date to check data availability around"
    ),
    days_before: int = Query(
        5, ge=0, le=30, description="Number of days before target date to include"
    ),
    days_after: int = Query(
        5, ge=0, le=30, description="Number of days after target date to include"
    ),
    patient_data_availability_service: PatientDataAvailabilityService = Depends(
        get_patient_data_availability_service
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

        # Validate that the requested "after" range does not go beyond today
        today = date.today()
        if target_date > today:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="target_date cannot be in the future",
            )

        # Clamp days_after so the range does not extend past today
        max_allowed_after = (today - target_date).days
        if days_after > max_allowed_after:
            days_after = max_allowed_after

        # Get data availability
        availability_data = (
            await patient_data_availability_service.get_data_availability(
                patient_id=str(target_patient_id),
                target_date=target_date,
                days_before=days_before,
                days_after=days_after,
            ) # type: ignore
        )

        return SuccessResponse(
            message="Patient data availability retrieved successfully",
            data=availability_data.dict(),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f"Error retrieving data availability: {str(e)}",
        )
