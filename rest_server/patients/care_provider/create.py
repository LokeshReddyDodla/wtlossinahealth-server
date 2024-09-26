from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.models.patient_care_provider import \
    PatientCareProvider as PatientCareProviderModel
from lib.schemas.patient_care_provider import \
    PatientCareProvider as PatientCareProviderSchema
from lib.schemas.patient_care_provider import PatientCareProviderCreate
from lib.services.patient_care_provider_service import \
    PatientCareProviderService
from rest_server.patients.care_provider.api_schema import \
    PatientCareProviderResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("", response_model=PatientCareProviderResponse)
async def create_patient_care_provider(
    request: Request,
    patient_care_provider: PatientCareProviderCreate,
    session: AsyncSession = Depends(get_postgres_session),
) -> Union[PatientCareProviderResponse, HTTPException]:
    service = PatientCareProviderService(session)
    try:
        result = await service.create_patient_care_provider(
            patient_care_provider
        )

        return PatientCareProviderResponse(
            message="Patient care provider created successfully",
            data=PatientCareProviderSchema.from_orm(result),
        )
    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
