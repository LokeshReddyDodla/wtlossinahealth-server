from lib.models.patient_care_provider import (
    PatientCareProvider as PatientCareProviderModel,
)
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select
from lib.schemas.patient_care_provider import (
    PatientCareProvider as PatientCareProviderSchema,
    PatientCareProviderCreate,
)
from sqlalchemy.exc import IntegrityError
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.delete("/{patient_care_provider_id}", response_model=SuccessResponse)
async def delete_patient_care_provider(
    request: Request, patient_care_provider_id: str
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(PatientCareProviderModel).where(
                    PatientCareProviderModel.patient_care_provider_id
                    == patient_care_provider_id
                )
            )
            patient_care_provider = result.scalars().first()

            if not patient_care_provider:
                raise HTTPException(
                    status_code=404,
                    detail="Patient care provider association not found.",
                )

            await session.delete(patient_care_provider)
            await session.commit()

            return SuccessResponse(
                message="Patient care provider association deleted successfully."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
