"""HTTP endpoints for weightloss intake forms (exercise, fitness, willingness)."""

from typing import Optional
from uuid import UUID

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
async def save_exercise_preferences(
    payload: ExercisePreferencesCreate,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[ExercisePreferencesRecord]:
    record = await intake_service.save_exercise_preferences(payload)
    return SuccessResponse(
        message="Exercise preferences saved",
        data=record,
    )


@router.post(
    "/fitness-screen",
    response_model=SuccessResponse[FitnessScreenRecord],
    status_code=status.HTTP_201_CREATED,
)
async def save_fitness_screen(
    payload: FitnessScreenCreate,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[FitnessScreenRecord]:
    record = await intake_service.save_fitness_screen(payload)
    return SuccessResponse(
        message="Fitness screen saved",
        data=record,
    )


@router.post(
    "/willingness-commitment",
    response_model=SuccessResponse[WillingnessCommitmentRecord],
    status_code=status.HTTP_201_CREATED,
)
async def save_willingness_commitment(
    payload: WillingnessCommitmentCreate,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[WillingnessCommitmentRecord]:
    record = await intake_service.save_willingness_commitment(payload)
    return SuccessResponse(
        message="Willingness commitment saved",
        data=record,
    )


@router.get(
    "/latest/exercise-preferences/{patient_id}",
    response_model=SuccessResponse[Optional[ExercisePreferencesRecord]],
    status_code=status.HTTP_200_OK,
)
async def get_latest_exercise_preferences(
    patient_id: UUID,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[Optional[ExercisePreferencesRecord]]:
    record = await intake_service.get_latest_exercise_preferences(patient_id)
    return SuccessResponse(
        message="Latest exercise preferences fetched",
        data=record,
    )


@router.get(
    "/latest/fitness-screen/{patient_id}",
    response_model=SuccessResponse[Optional[FitnessScreenRecord]],
    status_code=status.HTTP_200_OK,
)
async def get_latest_fitness_screen(
    patient_id: UUID,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[Optional[FitnessScreenRecord]]:
    record = await intake_service.get_latest_fitness_screen(patient_id)
    return SuccessResponse(
        message="Latest fitness screen fetched",
        data=record,
    )


@router.get(
    "/latest/willingness-commitment/{patient_id}",
    response_model=SuccessResponse[Optional[WillingnessCommitmentRecord]],
    status_code=status.HTTP_200_OK,
)
async def get_latest_willingness_commitment(
    patient_id: UUID,
    intake_service: IntakeService = Depends(get_intake_service),
) -> SuccessResponse[Optional[WillingnessCommitmentRecord]]:
    record = await intake_service.get_latest_willingness(patient_id)
    return SuccessResponse(
        message="Latest willingness commitment fetched",
        data=record,
    )
