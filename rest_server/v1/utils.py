from typing import Optional, Tuple
from uuid import UUID
from fastapi import status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.http_exceptions import raise_http_exception


def resolve_actor_scope(
    current_actor: Actor,
    require_health_facility: bool = False,
) -> Tuple[Optional[str], Optional[str], bool]:
    if current_actor.role == ProfileTypeEnum.ADMIN:
        # Global admin - no health facility or care provider ID
        return None, None, True
    
    elif current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        care_provider = current_actor.model  # type: ignore
        if not isinstance(care_provider, CareProviderModel):
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Invalid actor model type for care provider.",
            )
        
        health_facility_id = (
            str(care_provider.health_facility_id)
            if care_provider.health_facility_id
            else None
        )
        
        if require_health_facility and not health_facility_id:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No health facility associated with the care provider.",
            )
        
        care_provider_id = (
            str(care_provider.care_provider_id)
            if care_provider.care_provider_id
            else None
        )
        
        return health_facility_id, care_provider_id, care_provider.is_admin
    
    else:
        raise_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            message=f"Unsupported role: {current_actor.role}",
        )


def get_effective_health_facility_id(
    current_actor: Actor,
) -> Optional[str]:
    health_facility_id, _, is_admin = resolve_actor_scope(
        current_actor, require_health_facility=True
    )

    if is_admin and current_actor.role == ProfileTypeEnum.ADMIN.value:
        # Admin sees all facilities
        return None
    
    # Care provider - always use their own health facility
    return health_facility_id


def get_effective_care_provider_id(
    current_actor: Actor,
) -> Optional[str]:
    _, care_provider_id, is_admin = resolve_actor_scope(
        current_actor, require_health_facility=False
    )
    
    if current_actor.role == ProfileTypeEnum.ADMIN:
        # Global admin sees all patients
        return None
    
    if is_admin or current_actor.role == ProfileTypeEnum.ADMIN.value:
        # Facility admin sees all patients in their facility
        return None
    
    # Regular care provider - only see their own patients
    return care_provider_id


async def resolve_patient_ids_for_query(
    current_actor: Actor,
    provided_patient_ids: Optional[list[str]] = None,
    care_provider_access_service: Optional[CareProviderAccessService] = None,
) -> list[str]:
    user_id = current_actor.id
    
    if current_actor.role == ProfileTypeEnum.PATIENT:
        if provided_patient_ids is None:
            return [user_id]
        elif provided_patient_ids != [user_id]:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Patients can only access their own data",
            )
        return provided_patient_ids
    
    elif current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        if not provided_patient_ids or len(provided_patient_ids) == 0:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="patient_ids is required for care provider queries",
            )
        
        if not care_provider_access_service:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Access validation service not available",
            )
        
        # Batch validate all requested patients against care provider's access
        patient_uuids = [UUID(pid) for pid in provided_patient_ids]
        accessible_patient_ids = await care_provider_access_service.get_accessible_patients(
            care_provider_id=UUID(current_actor.id),
            patient_ids=patient_uuids,
        )
        
        # Check if all requested patients are accessible
        if len(accessible_patient_ids) != len(patient_uuids):
            inaccessible_patients = set(patient_uuids) - set(accessible_patient_ids)
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message=f"Care provider does not have access to requested patients: {inaccessible_patients}",
            )
        
        return provided_patient_ids
    
    elif current_actor.role == ProfileTypeEnum.ADMIN:
        # Admin can query any patient(s) or all if None
        return provided_patient_ids or []
    
    else:
        raise_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            message=f"Unsupported role: {current_actor.role}",
        )

