from lib.models.health_facility import HealthFacility
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.exc import IntegrityError

from lib.schemas.health_facility import (
    HealthFacilityCreate,
    HealthFacility as HealthFacilitySchema,
)


from rest_server.health_facility.api_schema import HealthFacilityResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.post("", response_model=HealthFacilityResponse)
async def create_health_facility(
    request: Request, health_facility: HealthFacilityCreate
) -> Union[HealthFacilityResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_health_facility = HealthFacility(**health_facility.dict())
            session.add(new_health_facility)
            await session.commit()
            await session.refresh(new_health_facility)

            return HealthFacilityResponse(
                message="Health facility created successfully",
                data=HealthFacilitySchema.from_orm(new_health_facility),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=400, detail="Health facility already exists."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
