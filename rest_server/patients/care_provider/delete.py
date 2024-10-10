import traceback
from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import \
    get_patient_care_provider_service
from lib.models.patient_care_provider import \
    PatientCareProvider as PatientCareProviderModel
from lib.schemas.patient_care_provider import \
    PatientCareProvider as PatientCareProviderSchema
from lib.schemas.patient_care_provider import PatientCareProviderCreate
from lib.services.patient_care_provider_service import \
    PatientCareProviderService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete("/{patient_care_provider_id}", response_model=SuccessResponse)
async def delete_patient_care_provider(
    request: Request,
    patient_care_provider_id: str,
    patient_care_provider_service: PatientCareProviderService = Depends(
        get_patient_care_provider_service
    ),
):
    try:
        await patient_care_provider_service.delete_patient_care_provider(
            patient_care_provider_id
        )
        return SuccessResponse(
            message="Patient care provider association deleted successfully."
        )
    except HTTPException as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print("🚀 ~ error_message:", error_message)
        print("🚀 ~ traceback_message:", traceback_message)
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
