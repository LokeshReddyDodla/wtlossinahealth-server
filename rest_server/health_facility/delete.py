from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.models.health_facility import HealthFacility
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select

from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.delete("/{health_facility_id}", response_model=SuccessResponse)
async def delete_health_facility(
    request: Request,
    health_facility_id: str,
    current_admin: Admin = Depends(get_current_admin),
) -> Union[SuccessResponse, HTTPException]:
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

            await session.delete(health_facility)
            await session.commit()

            return SuccessResponse(
                message="Health facility deleted successfully."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
