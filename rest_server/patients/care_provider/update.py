from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import \
    get_patient_care_provider_service
from lib.models.patient_care_provider import \
    PatientCareProvider as PatientCareProviderModel
from lib.schemas.patient_care_provider import \
    PatientCareProvider as PatientCareProviderSchema
from lib.schemas.patient_care_provider import (PatientCareProviderCreate,
                                               PatientCareProviderUpdate)
from lib.services.patient_care_provider_service import \
    PatientCareProviderService
from rest_server.patients.care_provider.api_schema import \
    PatientCareProviderResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.put(
    "/{patient_care_provider_id}", response_model=PatientCareProviderResponse
)
async def update_patient_care_provider(
    request: Request,
    patient_care_provider_id: str,
    patient_care_provider_update: PatientCareProviderUpdate,
    patient_care_provider_service: PatientCareProviderService = Depends(
        get_patient_care_provider_service
    ),
):
    try:
        updates = patient_care_provider_update.dict(exclude_unset=True)
        patient_care_provider = (
            await patient_care_provider_service.update_patient_care_provider(
                patient_care_provider_id, updates
            )
        )
        return PatientCareProviderResponse(
            message="Patient care provider updated successfully",
            data=PatientCareProviderSchema.from_orm(patient_care_provider),
        )
    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
