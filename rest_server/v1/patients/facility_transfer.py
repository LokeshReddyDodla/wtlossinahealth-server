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
    """Atomically transfer a patient to a new facility (admin only).

    ## What happens (single transaction)

    1. Validates patient + new facility exist, no-op guard if same facility
    2. Removes all active/pending buddy relationships (sets status="removed")
    3. Leaves all groups tied to old facility (sets is_active=False, left_at=now)
    4. Expires today's pending challenge tasks for those groups
    5. Withdraws from direct challenge participations in old facility
       (sets status="withdrawn")
    6. Expires today's pending challenge tasks for withdrawn challenges
    7. Updates patient.health_facility_id
    8. Single commit — all-or-nothing
    9. Post-commit: FCM notifications to the patient and each removed
       buddy (best-effort, failures don't roll back)

    ## What's preserved

    - Gamification profile (XP, level, streaks, buddy_code)
    - Achievements, daily tasks (non-challenge), weekly quests
    - All health data (meals, glucose, sleep, mood, symptoms, vitals)
    - Medications and prescriptions
    - Diet and fitness plans
    - Patient-created groups (no facility_id)
    - Care provider access via explicit assignment (many-to-many)

    ## What auto-updates without action

    - Facility leaderboards (refreshed daily — patient appears in new,
      disappears from old)
    - Care provider admin access (computed at request time — new facility
      admins gain access, old lose it)

    ## Response

    Returns a summary of the migration:
    ```json
    {
      "patient_id": "uuid",
      "old_facility_id": "uuid",
      "new_facility_id": "uuid",
      "buddies_removed": 3,
      "groups_left": 2,
      "challenges_withdrawn": 1,
      "removed_buddy_partner_ids": ["uuid", "uuid", "uuid"]
    }
    ```
    """
    summary = await service.transfer_patient(
        patient_id=patient_id,
        new_facility_id=payload.new_facility_id,
    )
    return SuccessResponse(
        message="Patient transferred to new facility",
        data=summary,
    )
