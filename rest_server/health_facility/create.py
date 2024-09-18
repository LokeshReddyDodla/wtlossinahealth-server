from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.admin import Admin
from lib.models.health_facility import HealthFacility
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.health_facility import HealthFacilityCreate
from lib.services.health_facility_service import HealthFacilityService
from rest_server.health_facility.api_schema import HealthFacilityResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("", response_model=HealthFacilityResponse)
async def create_health_facility(
    request: Request,
    health_facility: HealthFacilityCreate,
    current_admin: Admin = Depends(get_current_admin),
) -> Union[HealthFacilityResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = HealthFacilityService(session)
        try:
            new_health_facility = await service.create_health_facility(
                health_facility
            )

            return HealthFacilityResponse(
                message="Health facility created successfully",
                data=HealthFacilitySchema.from_orm(new_health_facility),
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
