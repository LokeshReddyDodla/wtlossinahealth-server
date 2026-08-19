from fastapi import HTTPException
from uuid import UUID

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_fitness_plan_service,
)
from lib.dependencies.patient_access import (
    resolve_patient_access,
)
from lib.schemas.patient_fitness_plan import PatientFitnessPlan
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_fitness_plan_service import PatientFitnessPlanService
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
async def get_active_fitness_plan(
    patient_id: str,
    plan_service: PatientFitnessPlanService = Depends(get_patient_fitness_plan_service),
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
    """Get the currently active fitness plan for a patient."""

    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        fitness_plan = await plan_service.get_active_fitness_plan(
            str(target_patient_id)
        )

        if not fitness_plan:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No active fitness plan found",
            )

        return SuccessResponse(
            data=PatientFitnessPlan.model_validate(fitness_plan),
            message="Active fitness plan retrieved successfully",
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
async def get_default_fitness_plan(
    patient_id: str,
    plan_service: PatientFitnessPlanService = Depends(get_patient_fitness_plan_service),
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
    """Get the default fitness plan created during patient onboarding."""

    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        fitness_plan = await plan_service.get_default_fitness_plan(
            str(target_patient_id)
        )

        if not fitness_plan:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No default fitness plan found",
            )

        return SuccessResponse(
            data=PatientFitnessPlan.model_validate(fitness_plan),
            message="Default fitness plan retrieved successfully",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
