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
from rest_server.health_facility.api_schema import HealthFacilityResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.put("/{health_facility_id}", response_model=HealthFacilityResponse)
async def update_health_facility(
    request: Request,
    health_facility_id: str,
    health_facility_update: HealthFacilityUpdate,
) -> Union[HealthFacilityResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(HealthFacility).where(
                    HealthFacility.health_facility_id == health_facility_id
                )
            )
            health_facility = result.scalars().first()

            if not health_facility:
                raise HTTPException(
                    status_code=404, detail="Health facility not found."
                )

            for key, value in health_facility_update.dict(
                exclude_unset=True
            ).items():
                setattr(health_facility, key, value)

            session.add(health_facility)
            await session.commit()
            await session.refresh(health_facility)

            return HealthFacilityResponse(
                message="Health facility created successfully",
                data=HealthFacilitySchema.from_orm(health_facility),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=400, detail="Health facility already exists."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
