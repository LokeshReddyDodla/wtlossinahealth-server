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
from lib.schemas.patient_fitness_plan import PatientFitnessPlan
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
    "/{fitness_plan_id}",
    response_model=SuccessResponse,
)
async def get_fitness_plan(
    fitness_plan_id: str,
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
    """Get a specific fitness plan by ID."""

    try:
        fitness_plan = await plan_service.get_fitness_plan(fitness_plan_id)

        if not fitness_plan:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Fitness plan not found",
            )

        # Verify patient access
        await resolve_patient_access(
            actor=current_actor,
            patient_id=fitness_plan.patient_id,
            care_provider_access_service=care_provider_access_service,
        )

        return SuccessResponse(
            data=PatientFitnessPlan.model_validate(fitness_plan),
            message="Fitness plan retrieved successfully",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
