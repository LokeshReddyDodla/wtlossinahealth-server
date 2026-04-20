"""V1 Patient workout endpoints — log and manage gym/exercise sessions."""

from datetime import date as date_type
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_workout_service,
)
from lib.schemas.patient_workout import (
    PatientWorkoutCreate,
    PatientWorkoutUpdate,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_workout_service import PatientWorkoutService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_ACTOR_DEPS = dict(
    allowed_roles=[
        ProfileTypeEnum.PATIENT,
        ProfileTypeEnum.CARE_PROVIDER,
        ProfileTypeEnum.ADMIN,
    ],
    check_permissions=False,
)


@router.post("/{patient_id}/workouts", response_model=SuccessResponse)
async def create_workout(
    patient_id: str,
    body: PatientWorkoutCreate,
    service: PatientWorkoutService = Depends(get_patient_workout_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Log a new workout session with its exercise line items."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    workout = await service.create(str(verified_pid), body)
    return SuccessResponse(
        message="Workout logged",
        data=workout.model_dump(mode="json"),
    )


@router.get("/{patient_id}/workouts", response_model=SuccessResponse)
async def list_workouts(
    patient_id: str,
    start_date: Optional[date_type] = Query(None, description="Default: 30 days ago"),
    end_date: Optional[date_type] = Query(None, description="Default: today"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: PatientWorkoutService = Depends(get_patient_workout_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """List workouts in a date range (most recent first)."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    result = await service.list(
        str(verified_pid),
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return SuccessResponse(
        message="Workouts retrieved",
        data=result.model_dump(mode="json"),
    )


@router.get(
    "/{patient_id}/workouts/{workout_id}", response_model=SuccessResponse
)
async def get_workout(
    patient_id: str,
    workout_id: str,
    service: PatientWorkoutService = Depends(get_patient_workout_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get a single workout with its exercises."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    workout = await service.get(str(verified_pid), workout_id)
    if not workout:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Workout not found",
        )
    return SuccessResponse(
        message="Workout retrieved",
        data=workout.model_dump(mode="json"),
    )


@router.patch(
    "/{patient_id}/workouts/{workout_id}", response_model=SuccessResponse
)
async def update_workout(
    patient_id: str,
    workout_id: str,
    body: PatientWorkoutUpdate,
    service: PatientWorkoutService = Depends(get_patient_workout_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Update a workout. If `exercises` is provided, the list is fully replaced."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    workout = await service.update(str(verified_pid), workout_id, body)
    if not workout:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Workout not found",
        )
    return SuccessResponse(
        message="Workout updated",
        data=workout.model_dump(mode="json"),
    )


@router.delete(
    "/{patient_id}/workouts/{workout_id}", response_model=SuccessResponse
)
async def delete_workout(
    patient_id: str,
    workout_id: str,
    service: PatientWorkoutService = Depends(get_patient_workout_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    deleted = await service.delete(str(verified_pid), workout_id)
    if not deleted:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Workout not found",
        )
    return SuccessResponse(message="Workout deleted")
