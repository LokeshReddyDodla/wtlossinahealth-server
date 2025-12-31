from typing import Optional

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_health_facility_service
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.package import Package as PackageSchema
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import get_effective_health_facility_id

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_health_facilities(
    limit: Optional[int] = Query(None, description="Limit number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        effective_health_facility_id = get_effective_health_facility_id(
            current_actor=current_actor,
        )

        health_facilities = await health_facility_service.fetch_health_facilities(
            health_facility_id=effective_health_facility_id,
            limit=limit,
            offset=offset,
        )

        response_data = []
        for hf in health_facilities:
            health_facility_dict = HealthFacilitySchema.from_orm(hf).model_dump()
            
            # Add care providers if available
            if hf.care_providers:
                health_facility_dict["care_providers"] = [
                    CareProviderSchema.from_orm(cp).model_dump()
                    for cp in hf.care_providers
                ]
            
            # Add patients if available
            if hf.patients:
                health_facility_dict["patients"] = [
                    PatientSchema.from_orm(patient).model_dump()
                    for patient in hf.patients
                ]
            
            # Add packages if available
            if hf.packages:
                health_facility_dict["packages"] = [
                    PackageSchema.from_orm(pkg).model_dump()
                    for pkg in hf.packages
                ]
            
            response_data.append(health_facility_dict)

        return SuccessResponse(
            message="Health facilities fetched successfully.",
            data=response_data,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )

