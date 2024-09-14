from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.models.health_facility import HealthFacility
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from typing import List, Optional, Union
from sqlalchemy.future import select
from lib.schemas.health_facility import (
    HealthFacility as HealthFacilitySchema,
    HealthFacilityUpdate,
)
from lib.services.health_facility_service import HealthFacilityService
from rest_server.health_facility.api_schema import HealthFacilityResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.put("/{health_facility_id}", response_model=HealthFacilityResponse)
async def update_health_facility(
    request: Request,
    health_facility_id: str,
    health_facility_update: HealthFacilityUpdate,
    current_admin: Admin = Depends(get_current_admin),
) -> Union[HealthFacilityResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = HealthFacilityService(session)
        try:
            updated_health_facility = await service.update_health_facility(
                health_facility_id, health_facility_update
            )

            return HealthFacilityResponse(
                message="Health facility updated successfully",
                data=HealthFacilitySchema.from_orm(updated_health_facility),
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
