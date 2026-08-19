from fastapi import HTTPException

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_diet_plan_service,
)
from lib.dependencies.patient_access import (
    resolve_patient_access,
)
from lib.schemas.patient_diet_plan import PatientDietPlan
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_diet_plan_service import PatientDietPlanService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/{diet_plan_id}",
    response_model=SuccessResponse,
)
async def get_diet_plan(
    diet_plan_id: str,
    plan_service: PatientDietPlanService = Depends(get_patient_diet_plan_service),
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
    """Get a specific diet plan by ID."""
    try:
        diet_plan = await plan_service.get_diet_plan(diet_plan_id)

        if not diet_plan:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Diet plan not found",
            )

        # Verify patient access
        await resolve_patient_access(
            actor=current_actor,
            patient_id=diet_plan.patient_id,
            care_provider_access_service=care_provider_access_service,
        )

        return SuccessResponse(
            data=PatientDietPlan.model_validate(diet_plan),
            message="Diet plan retrieved successfully",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
