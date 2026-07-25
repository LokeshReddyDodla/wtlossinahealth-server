from __future__ import annotations

from uuid import UUID

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.http_exceptions import raise_http_exception


async def resolve_patient_access(
    *,
    actor: Actor,
    patient_id: UUID | None,
    care_provider_access_service: CareProviderAccessService,
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
        is_assigned = await care_provider_access_service.is_patient_assigned(
            care_provider_id=actor.model.care_provider_id,
            patient_id=patient_id,
        )  # type: ignore
        if not is_assigned:
            raise_http_exception(
                status_code=403,
                message="You do not have access to this patient",
            )

    return patient_id
