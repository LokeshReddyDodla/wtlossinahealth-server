from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.models.health_facility import HealthFacility
from lib.services.health_facility_service import HealthFacilityService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete("/{health_facility_id}", response_model=SuccessResponse)
async def delete_health_facility(
    request: Request,
    health_facility_id: str,
    session: AsyncSession = Depends(get_postgres_session),
    current_admin: Admin = Depends(get_current_admin),
):
        service = HealthFacilityService(session)
        try:
            await service.delete_health_facility(health_facility_id)

            return SuccessResponse(
                message="Health facility deleted successfully."
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
