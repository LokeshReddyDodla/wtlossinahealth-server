"""POST /patients/{patient_id}/transfer-facility — admin endpoint to migrate patient to new facility."""

from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_patient_facility_transfer_service,
)
from lib.services.patient_facility_transfer_service import (
    PatientFacilityTransferService,
)
from rest_server.response_models import SuccessResponse

from .router import router


class TransferFacilityRequest(BaseModel):
    new_facility_id: UUID


@router.post(
    "/{patient_id}/transfer-facility",
    response_model=SuccessResponse,
)
async def transfer_patient_facility(
    patient_id: UUID,
    payload: TransferFacilityRequest,
    service: PatientFacilityTransferService = Depends(
        get_patient_facility_transfer_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(allowed_roles=[ProfileTypeEnum.ADMIN])
    ),
):
    """Atomically transfer a patient to a new facility.

    Cleans up:
    - All buddy relationships (different facility = can't be buddies)
    - Memberships in old facility's groups
    - Direct participations in old facility's challenges

    Preserves:
    - Patient's gamification profile (XP, level, streaks)
    - Achievements, daily tasks, weekly quests
    - Health data (meals, glucose, sleep, mood, medications)
    - Diet/fitness plans
    - Patient-created groups (if not facility-scoped)
    """
    summary = await service.transfer_patient(
        patient_id=patient_id,
        new_facility_id=payload.new_facility_id,
    )
    return SuccessResponse(
        message="Patient transferred to new facility",
        data=summary,
    )
