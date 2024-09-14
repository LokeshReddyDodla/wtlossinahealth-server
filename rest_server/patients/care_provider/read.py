from lib.models.patient_care_provider import (
    PatientCareProvider as PatientCareProviderModel,
)
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from lib.schemas.patient_care_provider import (
    PatientCareProvider as PatientCareProviderSchema,
    PatientCareProviderCreate,
)
from sqlalchemy.exc import IntegrityError
from lib.services.patient_care_provider_service import (
    PatientCareProviderService,
)
from rest_server.patients.care_provider.api_schema import (
    PatientCareProviderResponse,
)
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.get(
    "/{patient_care_provider_id}", response_model=PatientCareProviderResponse
)
async def get_patient_care_provider(
    request: Request, patient_care_provider_id: str
) -> Union[PatientCareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = PatientCareProviderService(session)
        try:
            patient_care_provider = await service.fetch_patient_care_provider(
                patient_care_provider_id
            )
            return PatientCareProviderResponse(
                message="Patient care provider retrieved successfully",
                data=PatientCareProviderSchema.from_orm(patient_care_provider),
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
