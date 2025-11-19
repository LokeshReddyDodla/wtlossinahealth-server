"""HTTP endpoints for capturing weightloss intake forms."""

from fastapi import APIRouter, Depends, status

from lib.dependencies.service_dependencies import get_intake_service
from lib.schemas.weightloss_agent.intake import (
    ExercisePreferencesCreate,
    ExercisePreferencesRecord,
    FitnessScreenCreate,
    FitnessScreenRecord,
    WillingnessCommitmentCreate,
    WillingnessCommitmentRecord,
)
from lib.services.weightloss_agent.intake_service import IntakeService
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/intake", tags=["Intake"])


@router.post(
    "/exercise-preferences",
    response_model=SuccessResponse[ExercisePreferencesRecord],
    status_code=status.HTTP_201_CREATED,
)
async def submit_exercise_preferences(
    payload: ExercisePreferencesCreate,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[ExercisePreferencesRecord]:
    record = await intake_service.save_exercise_preferences(payload)
    return SuccessResponse(
        message="Exercise preferences stored",
        data=record,
    )


@router.post(
    "/fitness-screen",
    response_model=SuccessResponse[FitnessScreenRecord],
    status_code=status.HTTP_201_CREATED,
)
async def submit_fitness_screen(
    payload: FitnessScreenCreate,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[FitnessScreenRecord]:
    record = await intake_service.save_fitness_screen(payload)
    return SuccessResponse(
        message="Fitness screen stored",
        data=record,
    )


@router.post(
    "/willingness",
    response_model=SuccessResponse[WillingnessCommitmentRecord],
    status_code=status.HTTP_201_CREATED,
)
async def submit_willingness_commitment(
    payload: WillingnessCommitmentCreate,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[WillingnessCommitmentRecord]:
    record = await intake_service.save_willingness_commitment(payload)
    return SuccessResponse(
        message="Willingness commitment stored",
        data=record,
    )
