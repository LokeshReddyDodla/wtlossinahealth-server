from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
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
from lib.services.chat_service import ChatService
from lib.services.patient_care_provider_service import (
    PatientCareProviderService,
)
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
        service = PatientCareProviderService(session)
        try:
            result = await service.create_patient_care_provider(
                patient_care_provider
            )

            return PatientCareProviderResponse(
                message="Patient care provider created successfully",
                data=result,
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
