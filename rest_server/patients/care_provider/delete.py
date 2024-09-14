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
from lib.services.patient_care_provider_service import (
    PatientCareProviderService,
)
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.delete("/{patient_care_provider_id}", response_model=SuccessResponse)
async def delete_patient_care_provider(
    request: Request, patient_care_provider_id: str
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = PatientCareProviderService(session)
        message = await service.delete_patient_care_provider(
            patient_care_provider_id
        )
        return SuccessResponse(message=message)
