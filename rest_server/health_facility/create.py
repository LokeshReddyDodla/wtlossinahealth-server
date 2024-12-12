from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_health_facility_service
from lib.models.admin import Admin
from lib.models.health_facility import HealthFacility
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.health_facility import HealthFacilityCreate
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("", response_model=SuccessResponse)
async def create_health_facility(
    request: Request,
    health_facility: HealthFacilityCreate,
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        new_health_facility = (
            await health_facility_service.create_health_facility(
                health_facility
            )
        )

        return SuccessResponse(
            message="Health facility created successfully",
            data=HealthFacilitySchema.from_orm(new_health_facility),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
