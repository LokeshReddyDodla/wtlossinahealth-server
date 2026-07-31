from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.service_dependencies import get_health_facility_service
from lib.models.admin import Admin
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("/all", response_model=SuccessResponse)
async def list_health_facilities(
    request: Request,
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
    current_admin: Admin = Depends(get_current_admin),
):
    """Flat id+name list for admin pickers (e.g. per-facility AI toggles)."""
    try:
        facilities = await health_facility_service.fetch_health_facilities()
        return SuccessResponse(
            message="Health facilities fetched successfully",
            data=[
                {
                    "health_facility_id": str(f.health_facility_id),
                    "name": f.name,
                }
                for f in facilities
            ],
        )
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
