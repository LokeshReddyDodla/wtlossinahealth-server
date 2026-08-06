from datetime import date
from uuid import UUID

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_day_view_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.day_view.resolver import DayViewService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


def _day_actor():
    # Same actor gate as the timeline route: admin / care-provider / patient, READ.
    return get_current_actor(
        allowed_roles=[
            ProfileTypeEnum.ADMIN,
            ProfileTypeEnum.CARE_PROVIDER,
            ProfileTypeEnum.PATIENT,
        ],
        care_provider_feature=CareProviderFeature.PATIENTS,
        care_provider_action=CareProviderPermissionAction.READ,
    )


@router.get("/{patient_id}/day", response_model=SuccessResponse)
async def get_patient_day(
    patient_id: str,
    date: date = Query(..., description="Patient-local date (YYYY-MM-DD)"),
    day_service: DayViewService = Depends(get_day_view_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(_day_actor()),
):
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

    day_view = await day_service.resolve(patient_id=str(target_patient_id), day=date)
    return SuccessResponse(
        message="Day view retrieved successfully",
        data=day_view.model_dump(mode="json"),
    )


@router.get("/{patient_id}/day/{domain}", response_model=SuccessResponse)
async def get_patient_day_domain(
    patient_id: str,
    domain: str,
    date: date = Query(..., description="Patient-local date (YYYY-MM-DD)"),
    day_service: DayViewService = Depends(get_day_view_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(_day_actor()),
):
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

    report = await day_service.fetch_domain_report(
        patient_id=str(target_patient_id), day=date, domain=domain
    )
    if report is None:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"No {domain} report available for that day",
        )

    return SuccessResponse(
        message=f"{domain.title()} report retrieved successfully",
        data=report,
    )
