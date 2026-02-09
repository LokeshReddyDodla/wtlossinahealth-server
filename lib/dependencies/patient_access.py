from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor
from lib.services.care_provider_profile_service import CareProviderProfileService
from lib.utils.http_exceptions import raise_http_exception

if TYPE_CHECKING:
    from lib.services.weight_loss_agent_service import WeightLossAgentService


async def resolve_patient_access(
    *,
    actor: Actor,
    patient_id: Optional[UUID],
    care_provider_service: CareProviderProfileService,
) -> UUID:
    """Ensure the caller may act on *patient_id*.

    • Patient  → always returns **own** patient_id (ignores the argument).
    • Care-provider → checks the assignment link; raises **403** if missing.
    """
    if actor.role == ProfileTypeEnum.PATIENT:
        return actor.model.patient_id

    if not patient_id:
        raise_http_exception(
            status_code=400,
            message="patient_id is required",
        )

    if actor.role == ProfileTypeEnum.CARE_PROVIDER:
        if not await care_provider_service.is_patient_assigned(
            care_provider_id=actor.model.care_provider_id,
            patient_id=patient_id,
        ):
            raise_http_exception(
                status_code=403,
                message="You do not have access to this patient",
            )

    return patient_id


async def verify_enrollment_access(
    *,
    enrollment_id: UUID,
    actor: Actor,
    weight_loss_service: "WeightLossAgentService",
    care_provider_service: CareProviderProfileService,
) -> dict:
    """Load an enrollment and ensure the caller may access it.

    Workflow:
      1. Fetch the enrollment from MongoDB.
      2. Extract its ``patient_id``.
      3. Delegate to :func:`resolve_patient_access` which enforces
         patient==self **or** verified provider→patient link.
      4. Return the enrollment dict so the caller can reuse it.

    Raises:
      404 – enrollment not found.
      403 – caller has no access to the enrollment's patient.
    """
    enrollment = await weight_loss_service.get_patient_enrollment(
        enrollment_id
    )
    if not enrollment:
        raise_http_exception(
            status_code=404,
            message="Enrollment not found",
        )

    raw_patient_id = enrollment.get("patient_id")
    if not raw_patient_id:
        raise_http_exception(
            status_code=404,
            message="Enrollment has no associated patient",
        )

    patient_uuid = (
        UUID(raw_patient_id)
        if isinstance(raw_patient_id, str)
        else raw_patient_id
    )

    await resolve_patient_access(
        actor=actor,
        patient_id=patient_uuid,
        care_provider_service=care_provider_service,
    )

    return enrollment


async def verify_enrollment_access_for_care_provider(
    *,
    enrollment_id: UUID,
    care_provider: object,
    weight_loss_service: "WeightLossAgentService",
    care_provider_service: CareProviderProfileService,
) -> dict:
    """Same as *verify_enrollment_access* but for CP-only routes.

    Uses the care-provider model directly (from ``get_current_care_provider``)
    instead of requiring a full ``Actor`` instance.
    """
    enrollment = await weight_loss_service.get_patient_enrollment(
        enrollment_id
    )
    if not enrollment:
        raise_http_exception(
            status_code=404,
            message="Enrollment not found",
        )

    raw_patient_id = enrollment.get("patient_id")
    if not raw_patient_id:
        raise_http_exception(
            status_code=404,
            message="Enrollment has no associated patient",
        )

    patient_uuid = (
        UUID(raw_patient_id)
        if isinstance(raw_patient_id, str)
        else raw_patient_id
    )

    if not await care_provider_service.is_patient_assigned(
        care_provider_id=care_provider.care_provider_id,  # type: ignore[attr-defined]
        patient_id=patient_uuid,
    ):
        raise_http_exception(
            status_code=403,
            message="You do not have access to this patient",
        )

    return enrollment
