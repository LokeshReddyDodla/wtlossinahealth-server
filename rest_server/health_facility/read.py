from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider
from lib.models.health_facility import HealthFacility
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.services.health_facility_service import HealthFacilityService
from rest_server.health_facility.api_schema import HealthFacilityResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("/{health_facility_id}", response_model=HealthFacilityResponse)
async def get_health_facility(
    request: Request,
    health_facility_id: str,
    session: AsyncSession = Depends(get_postgres_session),
    current_admin: Admin = Depends(get_current_admin),
) -> Union[HealthFacilityResponse, HTTPException]:
    service = HealthFacilityService(session)
    health_facility = await service.fetch_health_facility(
        health_facility_id, detailed=True
    )
    return HealthFacilityResponse(
        message="Health facility fetched successfully",
        data=HealthFacilitySchema.from_orm(health_facility),
    )
