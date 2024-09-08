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
from rest_server.patients.care_provider.api_schema import (
    PatientCareProviderResponse,
)
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.post("", response_model=PatientCareProviderResponse)
async def create_patient_care_provider(
    request: Request, patient_care_provider: PatientCareProviderCreate
) -> Union[PatientCareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_patient_care_provider = PatientCareProviderModel(
                **patient_care_provider.dict()
            )
            session.add(new_patient_care_provider)
            await session.commit()
            await session.refresh(new_patient_care_provider)

            return PatientCareProviderResponse(
                message="Patient care provider created successfully",
                data=PatientCareProviderSchema.from_orm(
                    new_patient_care_provider
                ),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=400,
                detail="Patient care provider association already exists.",
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
