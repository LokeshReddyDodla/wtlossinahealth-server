from typing import Optional

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_care_provider_profile_service
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.patient import Patient as PatientSchema
from lib.services.care_provider_profile_service import CareProviderProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import get_effective_health_facility_id

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_care_providers(
    limit: Optional[int] = Query(None, description="Limit number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    care_provider_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.CARE_PROVIDERS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        effective_health_facility_id = get_effective_health_facility_id(
            current_actor=current_actor,
        )

        care_providers = await care_provider_service.fetch_care_providers(
            health_facility_id=effective_health_facility_id,
            limit=limit,
            offset=offset,
        )

        total = await care_provider_service.count_care_providers(
            health_facility_id=effective_health_facility_id,
        )

        response_data = []
        for cp in care_providers:
            care_provider_dict = CareProviderSchema.from_orm(cp).model_dump()
            
            # Add health facility if available
            if cp.health_facility:
                care_provider_dict["health_facility"] = HealthFacilitySchema.from_orm(
                    cp.health_facility
                ).model_dump()
            
            # Add patients if available
            if cp.patients:
                care_provider_dict["patients"] = [
                    PatientSchema.from_orm(patient).model_dump()
                    for patient in cp.patients
                ]
            
            # Add packages if available
            if cp.packages:
                from lib.schemas.package import Package as PackageSchema
                care_provider_dict["packages"] = [
                    PackageSchema.from_orm(pkg).model_dump()
                    for pkg in cp.packages
                ]
            
            response_data.append(care_provider_dict)

        return SuccessResponse(
            version="v1",
            message="Care providers fetched successfully.",
            data={
                "total": total,
                "items": response_data,
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )

