import asyncio
from typing import List, Literal, Optional

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_care_provider_query_service,
    get_user_device_service,
)
from lib.queries.care_provider_query import CareProviderQuery
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.patient import Patient as PatientSchema
from lib.services.care_provider_query_service import CareProviderQueryService
from lib.services.user_device_service import UserDeviceService
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
    search: Optional[str] = Query(None, description="Search term"),
    role: Optional[List[str]] = Query(None, description="Filter by role"),
    order_by: Optional[
        Literal[
            "first_name",
            "last_name",
            "email",
            "role",
            "created_at",
            "is_verified",
            "last_active_at",
        ]
    ] = Query(None, description="Order by field"),
    order: Literal["asc", "desc"] = Query("desc", description="Order direction"),
    query_service: CareProviderQueryService = Depends(get_care_provider_query_service),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
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

        query = CareProviderQuery(
            limit=limit,
            offset=offset,
            search=search,
            role=role,
            health_facility_id=effective_health_facility_id,
            order_by=order_by,
            order=order,
        )

        # Fetch care providers and total count in parallel
        care_providers, total = await asyncio.gather(
            query_service.fetch(query),
            query_service.count(query),
        )

        # Get last_active_at for all care providers
        user_ids = [str(cp.care_provider_id) for cp in care_providers]
        last_active_map = await user_device_service.get_last_active_map(
            user_ids=user_ids,
            profile_type=ProfileTypeEnum.CARE_PROVIDER.value,
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
                    PackageSchema.from_orm(pkg).model_dump() for pkg in cp.packages
                ]

            # Add last_active_at
            care_provider_dict["last_active_at"] = last_active_map.get(
                str(cp.care_provider_id)
            )

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
