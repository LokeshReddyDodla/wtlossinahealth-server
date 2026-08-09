from fastapi import HTTPException
from typing import Optional
from uuid import UUID

from fastapi import Depends, status as responseStatus, Query

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
    "/patient/{patient_id}",
    response_model=SuccessResponse,
)
async def list_fitness_plans(
    patient_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status"),
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
    """Get all fitness plans for a patient with optional status filtering."""

    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=patient_id,
            care_provider_access_service=care_provider_access_service,
        )

        fitness_plans = await plan_service.get_patient_fitness_plans(
            patient_id=str(target_patient_id),
            status_filter=status,
        )  # type: ignore

        return SuccessResponse(
            data=[PatientFitnessPlan.model_validate(plan) for plan in fitness_plans],
            message=f"Retrieved {len(fitness_plans)} fitness plan(s)",
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
