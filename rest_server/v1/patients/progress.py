from uuid import UUID

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_progress_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.progress.bucketing import _MONTHS
from lib.services.progress.resolver import ProgressService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}/progress", response_model=SuccessResponse)
async def get_patient_progress(
    patient_id: str,
    range_key: str = Query("6M", alias="range", description="1M | 3M | 6M | 1Y"),
    progress_service: ProgressService = Depends(get_progress_service),
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
    if range_key not in _MONTHS:
        raise_http_exception(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=f"range must be one of {', '.join(_MONTHS)}",
        )

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

    progress = await progress_service.resolve(
        patient_id=str(target_patient_id), range_key=range_key
    )
    return SuccessResponse(
        message="Progress retrieved successfully",
        data=progress.model_dump(mode="json"),
    )
