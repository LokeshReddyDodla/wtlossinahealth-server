from fastapi import HTTPException

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
from lib.schemas.patient_fitness_plan import (
    PatientFitnessPlan,
    PatientFitnessPlanUpdate,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_fitness_plan_service import PatientFitnessPlanService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.patch(
    "/{fitness_plan_id}",
    response_model=SuccessResponse,
)
async def update_fitness_plan(
    fitness_plan_id: str,
    payload: PatientFitnessPlanUpdate,
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
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
):
    """Update a fitness plan with new targets or status."""

    try:
        # Get existing fitness plan
        fitness_plan = await plan_service.get_fitness_plan(str(fitness_plan_id))

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

        # Update the fitness plan in the database
        update_data = payload.model_dump(exclude_unset=True)
        updated_plan = await plan_service.update_fitness_plan(
            fitness_plan_id=fitness_plan_id,
            update_data=update_data,
        ) # type: ignore

        return SuccessResponse(
            data=PatientFitnessPlan.model_validate(updated_plan),
            message="Fitness plan updated successfully",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
