
from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.service_dependencies import get_health_facility_service
from lib.models.admin import Admin
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.health_facility import HealthFacilityUpdate
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.put("", response_model=SuccessResponse)
async def update_health_facility(
    request: Request,
    health_facility_id: str,
    health_facility_update: HealthFacilityUpdate,
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        updated_health_facility = (
            await health_facility_service.update_health_facility(
                health_facility_id, health_facility_update
            )
        )

        return SuccessResponse(
            message="Health facility updated successfully",
            data=HealthFacilitySchema.from_orm(updated_health_facility),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
