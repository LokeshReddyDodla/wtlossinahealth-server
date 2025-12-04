"""Endpoints for GLP-1 weekly symptom submissions."""

from fastapi import APIRouter, Depends, HTTPException, status

from lib.dependencies.service_dependencies import get_glp1_symptoms_service
from lib.schemas.weightloss_agent.symptoms import (
    WeeklySymptomsCreate,
    WeeklySymptomsRecord,
)
from lib.services.weightloss_agent.glp1_symptoms_service import (
    Glp1SymptomsService,
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
    symptoms_service: Glp1SymptomsService = Depends(
        get_glp1_symptoms_service
    ),
) -> SuccessResponse[WeeklySymptomsRecord]:
    try:
        record = await symptoms_service.log_weekly_symptoms(payload)
    except Exception as exc:  # pragma: no cover - defensive logging
        # Surface underlying error to help diagnose 500s in non-debug environments
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"GLP1 symptoms processing failed: {exc}",
        )
    return SuccessResponse(
        message="Weekly symptoms recorded",
        data=record,
    )
