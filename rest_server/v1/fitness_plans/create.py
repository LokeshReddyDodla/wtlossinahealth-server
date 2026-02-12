from http.client import HTTPException
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
from lib.schemas.patient_fitness_plan import (
    PatientFitnessPlan,
    PatientFitnessPlanCreate,
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


@router.post(
    "/{patient_id}",
    response_model=SuccessResponse,
)
async def create_fitness_plan(
    patient_id: str,
    payload: PatientFitnessPlanCreate,
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
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
):
    """Create a new fitness plan for a patient."""

    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        if not target_patient_id:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Patient not found",
            )

        fitness_plan = await plan_service.create_fitness_plan(
            patient_id=str(target_patient_id),
            fitness_plan_data=payload,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_default=payload.is_default,
            status=payload.status,
            plan_reason=payload.plan_reason,
        )  # type: ignore

        return SuccessResponse(
            data=PatientFitnessPlan.model_validate(fitness_plan),
            message="Fitness plan created successfully",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
