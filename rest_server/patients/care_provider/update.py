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
    PatientCareProviderUpdate,
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


@router.put(
    "/{patient_care_provider_id}", response_model=PatientCareProviderResponse
)
async def update_patient_care_provider(
    request: Request,
    patient_care_provider_id: str,
    patient_care_provider_update: PatientCareProviderUpdate,
) -> Union[PatientCareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = PatientCareProviderService(session)
        updates = patient_care_provider_update.dict(exclude_unset=True)
        patient_care_provider = await service.update_patient_care_provider(
            patient_care_provider_id, updates
        )
        return PatientCareProviderResponse(
            message="Patient care provider updated successfully",
            data=patient_care_provider,
        )
