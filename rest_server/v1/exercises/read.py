"""GET /exercises — search, detail, facets over the seeded exercise catalog."""

from typing import Optional

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_exercise_service
from lib.services.exercise_service import ExerciseService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_READ_ROLES = [
    ProfileTypeEnum.ADMIN,
    ProfileTypeEnum.CARE_PROVIDER,
    ProfileTypeEnum.PATIENT,
]


@router.get("/search", response_model=SuccessResponse)
async def search_exercises(
    q: Optional[str] = Query(None, description="Full-text query on name/muscles/equipment"),
    muscle: Optional[str] = Query(None, description="Filter by primary muscle, e.g. 'chest'"),
    equipment: Optional[str] = Query(None, description="Filter by equipment, e.g. 'barbell'"),
    category: Optional[str] = Query(None, description="strength, cardio, stretching, ..."),
    level: Optional[str] = Query(None, description="beginner, intermediate, expert"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    exercise_service: ExerciseService = Depends(get_exercise_service),
    current_actor: Actor = Depends(get_current_actor(allowed_roles=_READ_ROLES)),
):
    """Search the exercise catalog. All filters are optional and combine via AND."""
    result = await exercise_service.search(
        q=q,
        muscle=muscle,
        equipment=equipment,
        category=category,
        level=level,
        limit=limit,
        offset=offset,
    )
    return SuccessResponse(
        message="Exercises retrieved",
        data=result.model_dump(mode="json"),
    )


@router.get("/facets", response_model=SuccessResponse)
async def get_exercise_facets(
    exercise_service: ExerciseService = Depends(get_exercise_service),
    current_actor: Actor = Depends(get_current_actor(allowed_roles=_READ_ROLES)),
):
    """Return distinct muscle/equipment/category/level values — useful for filter dropdowns."""
    facets = await exercise_service.get_facets()
    return SuccessResponse(
        message="Exercise facets retrieved",
        data=facets.model_dump(mode="json"),
    )


@router.get("/{exercise_id}", response_model=SuccessResponse)
async def get_exercise(
    exercise_id: str,
    exercise_service: ExerciseService = Depends(get_exercise_service),
    current_actor: Actor = Depends(get_current_actor(allowed_roles=_READ_ROLES)),
):
    """Get a single exercise by id (slug, e.g. 'Barbell_Bench_Press_-_Medium_Grip')."""
    ex = await exercise_service.get_by_id(exercise_id)
    if not ex:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Exercise not found",
        )
    return SuccessResponse(
        message="Exercise retrieved",
        data=ex.model_dump(mode="json"),
    )
