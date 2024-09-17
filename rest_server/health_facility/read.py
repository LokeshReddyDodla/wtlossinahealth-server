from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider
from lib.models.health_facility import HealthFacility
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select
from lib.schemas.health_facility import (
    HealthFacility as HealthFacilitySchema,
)
from lib.services.health_facility_service import HealthFacilityService
from rest_server.health_facility.api_schema import HealthFacilityResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from sqlalchemy.orm import selectinload
from .router import router


@router.get("/{health_facility_id}", response_model=HealthFacilityResponse)
async def get_health_facility(
    request: Request,
    health_facility_id: str,
    current_admin: Admin = Depends(get_current_admin),
) -> Union[HealthFacilityResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = HealthFacilityService(session)
        health_facility = await service.fetch_health_facility(
            health_facility_id, detailed=True
        )
        return HealthFacilityResponse(
            message="Health facility fetched successfully",
            data=HealthFacilitySchema.from_orm(health_facility),
        )
