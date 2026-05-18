"""POST / PATCH / DELETE /exercises — care provider & admin exercise management."""

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_exercise_service
from lib.schemas.exercise import ExerciseCreate, ExerciseUpdate
from lib.services.exercise_service import ExerciseService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_WRITE_ROLES = [
    ProfileTypeEnum.ADMIN,
    ProfileTypeEnum.CARE_PROVIDER,
]


@router.post("", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED)
async def create_exercise(
    body: ExerciseCreate,
    exercise_service: ExerciseService = Depends(get_exercise_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.FITNESS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
):
    """Add a new exercise to the catalog."""
    exercise, created = await exercise_service.create(body)
    if not created:
        raise_http_exception(
            status_code=status.HTTP_409_CONFLICT,
            message=f"An exercise named '{body.name}' already exists (id: {exercise.id})",
        )
    return SuccessResponse(
        message="Exercise created", data=exercise.model_dump(mode="json")
    )


@router.patch("/{exercise_id}", response_model=SuccessResponse)
async def update_exercise(
    exercise_id: str,
    body: ExerciseUpdate,
    exercise_service: ExerciseService = Depends(get_exercise_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.FITNESS,
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
):
    """Update any fields of an exercise (name, level, muscles, instructions, etc.)."""
    exercise = await exercise_service.update(exercise_id, body)
    if not exercise:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Exercise not found",
        )
    return SuccessResponse(
        message="Exercise updated", data=exercise.model_dump(mode="json")
    )


@router.delete("/{exercise_id}", response_model=SuccessResponse)
async def delete_exercise(
    exercise_id: str,
    exercise_service: ExerciseService = Depends(get_exercise_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.FITNESS,
            care_provider_action=CareProviderPermissionAction.DELETE,
        )
    ),
):
    """Remove an exercise from the catalog."""
    deleted = await exercise_service.delete(exercise_id)
    if not deleted:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Exercise not found",
        )
    return SuccessResponse(message="Exercise deleted", data=None)
