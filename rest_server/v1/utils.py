from typing import Optional, Tuple
from fastapi import status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider as CareProviderModel
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

    print("🚀 ~ health_facility_id:", health_facility_id)
    print("🚀 ~ is_admin:", is_admin)
    print("🚀 ~ current_actor.role:", current_actor.role)

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

    print("🚀 ~ care_provider_id:", care_provider_id)
    print("🚀 ~ is_admin:", is_admin)
    print("🚀 ~ current_actor.role:", current_actor.role)
    
    if current_actor.role == ProfileTypeEnum.ADMIN:
        # Global admin sees all patients
        return None
    
    if is_admin or current_actor.role == ProfileTypeEnum.ADMIN.value:
        # Facility admin sees all patients in their facility
        return None
    
    # Regular care provider - only see their own patients
    return care_provider_id

