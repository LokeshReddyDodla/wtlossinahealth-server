from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_health_facility_service
from lib.models.admin import Admin
from lib.models.health_facility import HealthFacility
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete("", response_model=SuccessResponse)
async def delete_health_facility(
    request: Request,
    health_facility_id: str,
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        await health_facility_service.delete_health_facility(
            health_facility_id
        )

        return SuccessResponse(message="Health facility deleted successfully.")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
