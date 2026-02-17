"""Endpoints for GLP-1 weekly symptom submissions."""

from fastapi import APIRouter, Depends, HTTPException, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_glp1_symptoms_service,
)
from lib.schemas.weightloss_agent.symptoms import (
    WeeklySymptomsCreate,
    WeeklySymptomsRecord,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.weightloss_agent.glp1_symptoms_service import (
    Glp1SymptomsService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/symptoms", tags=["Symptoms"])


@router.post(
    "/weekly",
    response_model=SuccessResponse[WeeklySymptomsRecord],
    status_code=status.HTTP_201_CREATED,
)
async def log_weekly_symptoms(
    payload: WeeklySymptomsCreate,
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    symptoms_service: Glp1SymptomsService = Depends(
        get_glp1_symptoms_service
    ),
) -> SuccessResponse[WeeklySymptomsRecord]:
    patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=payload.user_id,
        care_provider_access_service=care_provider_access_service,
    )
    payload.user_id = patient_id
    try:
        record = await symptoms_service.log_weekly_symptoms(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GLP1 symptoms processing failed",
        )
    return SuccessResponse(
        message="Weekly symptoms recorded",
        data=record,
    )
