from http.client import HTTPException
from uuid import UUID

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_plan_service,
)
from lib.dependencies.patient_access import (
    resolve_patient_access,
)
from lib.schemas.patient_diet_plan import PatientDietPlan
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_plan_service import PatientPlanService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/patient/{patient_id}/active",
    response_model=SuccessResponse,
)
async def get_active_diet_plan(
    patient_id: str,
    plan_service: PatientPlanService = Depends(get_patient_plan_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    """Get the currently active diet plan for a patient."""

    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        diet_plan = await plan_service.get_active_diet_plan(str(target_patient_id))

        if not diet_plan:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No active diet plan found",
            )

        return SuccessResponse(
            data=PatientDietPlan.model_validate(diet_plan),
            message="Active diet plan retrieved successfully",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/patient/{patient_id}/default",
    response_model=SuccessResponse,
)
async def get_default_diet_plan(
    patient_id: str,
    plan_service: PatientPlanService = Depends(get_patient_plan_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    """Get the default diet plan created during patient onboarding."""

    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        diet_plan = await plan_service.get_default_diet_plan(str(target_patient_id))

        if not diet_plan:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No default diet plan found",
            )

        return SuccessResponse(
            data=PatientDietPlan.model_validate(diet_plan),
            message="Default diet plan retrieved successfully",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
