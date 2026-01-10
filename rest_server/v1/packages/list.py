import asyncio
from typing import List, Literal, Optional

from fastapi import Depends, HTTPException, Query, status as fastapi_status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_package_query_service
from lib.queries.package_query import PackageQuery
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.package import Package as PackageSchema
from lib.services.package_query_service import PackageQueryService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import (
    get_effective_care_provider_id,
    get_effective_health_facility_id,
)

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_packages(
    limit: Optional[int] = Query(None, description="Limit number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    search: Optional[str] = Query(None, description="Search term"),
    status: Optional[List[str]] = Query(None, description="Filter by status"),
    type: Optional[List[str]] = Query(None, description="Filter by package type"),
    order_by: Optional[Literal["name", "duration_days", "price", "created_at"]] = Query(
        "created_at", description="Order by field"
    ),
    order: Literal["asc", "desc"] = Query("desc", description="Order direction"),
    query_service: PackageQueryService = Depends(get_package_query_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.PACKAGES,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        effective_health_facility_id = get_effective_health_facility_id(
            current_actor=current_actor,
        )
        effective_care_provider_id = get_effective_care_provider_id(
            current_actor=current_actor,
        )

        query = PackageQuery(
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            type=type,
            health_facility_id=effective_health_facility_id,
            care_provider_id=effective_care_provider_id,
            order_by=order_by,
            order=order,
        )

        # Fetch packages and total count in parallel
        packages, total = await asyncio.gather(
            query_service.fetch(query),
            query_service.count(query),
        )

        response_data = []
        for pkg in packages:
            package_dict = PackageSchema.from_orm(pkg).model_dump()
            
            # Add health facility if available
            if pkg.health_facility:
                package_dict["health_facility"] = HealthFacilitySchema.from_orm(
                    pkg.health_facility
                ).model_dump()
            
            # Add care providers if available
            if pkg.care_providers:
                package_dict["care_providers"] = [
                    CareProviderSchema.from_orm(cp).model_dump()
                    for cp in pkg.care_providers
                ]
            
            # Add patients from patient_assignments if available
            if pkg.patient_assignments:
                package_dict["patients"] = [
                    PatientSchema.from_orm(assignment.patient).model_dump()
                    for assignment in pkg.patient_assignments
                    if assignment.patient
                ]
            
            response_data.append(package_dict)

        return SuccessResponse(
            version="v1",
            message="Packages fetched successfully.",
            data={
                "total": total,
                "items": response_data,
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )

