
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.service_dependencies import get_health_facility_service
from lib.models.admin import Admin
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/basic-info", response_model=SuccessResponse)
async def get_basic_health_facility_info(
    health_facility_id: str,
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
):
    try:
        health_facility = await health_facility_service.fetch_health_facility(
            health_facility_id, detailed=False
        )

        basic_info = {
            "name": health_facility.name,
            "logo_url": health_facility.logo_url,
            "contact_info": health_facility.contact_info,
        }

        return SuccessResponse(
            message="Health facility basic info fetched successfully",
            data=basic_info,
        )
    except HTTPException as http_exc:
        raise http_exc
    except SQLAlchemyError as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("", response_model=SuccessResponse)
async def get_health_facility(
    request: Request,
    health_facility_id: str,
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        health_facility = await health_facility_service.fetch_health_facility(
            health_facility_id, detailed=True
        )
        return SuccessResponse(
            message="Health facility fetched successfully",
            data=HealthFacilitySchema.from_orm(health_facility),
        )
    except HTTPException as http_exc:
        raise http_exc
    except SQLAlchemyError as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/validate-health-facility", response_model=SuccessResponse)
async def validate_health_facility(
    request: Request,
    domain: str,
    subdomain: str,
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
):
    try:
        health_facility = (
            await health_facility_service.fetch_health_facility_by_domain(
                subdomain=subdomain, custom_domain=domain
            )
        )
        return SuccessResponse(
            message="Health facility fetched successfully",
            data={"health_facility_id": health_facility.health_facility_id},
        )
    except HTTPException as http_exc:
        raise http_exc
    except SQLAlchemyError as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
